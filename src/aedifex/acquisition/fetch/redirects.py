"""Redirect policy. Pure: resolves and judges a ``Location``, but never fetches anything.

The controller that loops over hops lives with the transport. What lives here is the decision, so
it can be tested exhaustively without a server: resolve a possibly-relative ``Location`` against
the URL that produced it, apply the hop cap, detect loops, and rule on transport downgrades.

**A redirect target is not validated by this module.** It returns a URL string, and the caller must
put that back through :func:`~aedifex.acquisition.fetch.guard.validate_url` to obtain a new
:class:`~aedifex.acquisition.fetch.guard.ValidatedTarget`. Validation of the first hop confers
nothing on later hops: the whole reason redirects are dangerous is that the second destination is
chosen by the remote server.

Transport downgrade is policy, not a library default. ``https`` → ``http`` moves evidence onto a
tamperable channel, so it is refused unless the source has explicitly accepted that (the same
``allow_insecure_transport`` flag the registry already requires for a plain-HTTP ``base_url``).
``http`` → ``https`` is always allowed: an upgrade needs no permission.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self
from urllib.parse import urljoin

from aedifex.acquisition.fetch.urls import RejectionReason, SsrfRejectionError
from aedifex.acquisition.registry.models import SourceDefinition

__all__ = [
    "REDIRECT_STATUSES",
    "RedirectDecision",
    "RedirectOutcome",
    "RedirectPolicy",
]

# Statuses that carry a Location we would follow. 300 (Multiple Choices) is excluded: it has no
# single canonical target, so following it means guessing.
REDIRECT_STATUSES: Final[frozenset[int]] = frozenset({301, 302, 303, 307, 308})

# 303 requires rewriting the method to GET. Recorded because it matters even though this fetcher
# only issues GET and HEAD, so the rewrite is currently a no-op — if POST is ever added, omitting
# it becomes a correctness bug.
_METHOD_REWRITING_STATUSES: Final[frozenset[int]] = frozenset({303})


class RedirectOutcome(StrEnum):
    """What to do with a redirect response."""

    FOLLOW = "follow"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class RedirectDecision:
    """The judgement on one ``Location`` header."""

    outcome: RedirectOutcome
    url: str | None
    """The absolute, resolved target when following; ``None`` when rejecting."""
    reason: str
    rewrite_method_to_get: bool = False

    @property
    def should_follow(self) -> bool:
        return self.outcome is RedirectOutcome.FOLLOW


@dataclass(frozen=True, slots=True)
class RedirectPolicy:
    """Rules for following redirects.

    Args:
        max_hops: Chain length limit. Five is enough for legitimate canonicalisation chains
            (http→https→www→trailing slash) and short enough to bound the work an attacker can
            make us do.
        allow_transport_downgrade: Whether ``https`` → ``http`` may be followed. Comes from the
            source's ``allow_insecure_transport``; default refuses.
    """

    max_hops: int = 5
    allow_transport_downgrade: bool = False

    def __post_init__(self) -> None:
        if self.max_hops < 1:
            raise ValueError(f"max_hops must be at least 1, got {self.max_hops}")

    @classmethod
    def from_source(cls, source: SourceDefinition, *, max_hops: int = 5) -> Self:
        """Derive the policy from a registry definition.

        Downgrade permission comes from the source's ``allow_insecure_transport`` — the same flag
        that already has to be set for a plain-HTTP ``base_url``. Reusing it means a source either
        accepts a tamperable channel or does not, rather than accepting it for its entry point and
        implicitly for redirects too.
        """
        return cls(max_hops=max_hops, allow_transport_downgrade=source.allow_insecure_transport)

    def evaluate(
        self,
        *,
        status_code: int,
        location: str | None,
        current_url: str,
        current_scheme: str,
        history: tuple[str, ...] = (),
    ) -> RedirectDecision:
        """Judge a redirect response.

        Args:
            status_code: The response status.
            location: Raw ``Location`` header, possibly relative, possibly absent or hostile.
            current_url: The absolute URL that produced this response; the base for resolution.
            current_scheme: Scheme of ``current_url``, for the downgrade check.
            history: Absolute URLs already visited in this chain, including ``current_url``.

        Returns:
            A :class:`RedirectDecision`. Following requires the caller to re-validate the URL.
        """
        if status_code not in REDIRECT_STATUSES:
            return RedirectDecision(
                RedirectOutcome.REJECT, None, f"HTTP {status_code} is not a followable redirect"
            )

        if location is None or not location.strip():
            # A redirect status with no target is a broken response, not an invitation to guess.
            return RedirectDecision(
                RedirectOutcome.REJECT, None, f"HTTP {status_code} carried no Location header"
            )

        # Count hops already taken. history includes the current URL, so a chain of one entry is
        # the original request and zero hops so far.
        hops_taken = max(0, len(history) - 1)
        if hops_taken >= self.max_hops:
            return RedirectDecision(
                RedirectOutcome.REJECT,
                None,
                f"redirect chain exceeded {self.max_hops} hops",
            )

        resolved = self._resolve(location.strip(), current_url)
        if resolved is None:
            return RedirectDecision(
                RedirectOutcome.REJECT,
                None,
                f"Location {location.strip()[:200]!r} could not be resolved to an absolute URL",
            )

        # Loop detection is explicit rather than left to the hop cap. Exhausting five hops around
        # a two-URL cycle wastes time and reports the wrong reason.
        if resolved in history:
            return RedirectDecision(
                RedirectOutcome.REJECT,
                None,
                f"redirect loop: {resolved} already visited in this chain",
            )

        downgrade_reason = self._check_downgrade(current_scheme, resolved)
        if downgrade_reason is not None:
            return RedirectDecision(RedirectOutcome.REJECT, None, downgrade_reason)

        return RedirectDecision(
            RedirectOutcome.FOLLOW,
            resolved,
            f"HTTP {status_code} to {resolved}; requires re-validation before connecting",
            rewrite_method_to_get=status_code in _METHOD_REWRITING_STATUSES,
        )

    def _resolve(self, location: str, current_url: str) -> str | None:
        """Resolve a possibly-relative ``Location`` to an absolute URL.

        Returns ``None`` when the result is not usable. Note that this deliberately does **not**
        validate the scheme, host, or port — that is the guard's job, and duplicating it here would
        create two places where the rules could drift apart.
        """
        if any(character in location for character in ("\n", "\r", "\x00")):
            # Header injection or a split response; never resolve it.
            return None
        try:
            resolved = urljoin(current_url, location)
        except ValueError:
            return None
        if not resolved or "://" not in resolved:
            # A scheme-relative or opaque target that urljoin could not complete.
            return None
        return resolved

    def _check_downgrade(self, current_scheme: str, resolved: str) -> str | None:
        """Return a rejection reason if the redirect downgrades transport, else ``None``."""
        target_scheme = resolved.split("://", 1)[0].lower()
        if current_scheme.lower() == "https" and target_scheme == "http":
            if not self.allow_transport_downgrade:
                return (
                    "redirect downgrades transport from https to http; evidence fetched over a "
                    "tamperable channel is weak evidence, so this requires the source to set "
                    "allow_insecure_transport"
                )
            return None
        return None

    def assert_can_follow(self, decision: RedirectDecision) -> str:
        """Return the target URL, or raise if the decision was to reject.

        Convenience for a controller that treats a rejected redirect as a hard failure, so the
        rejection carries the same typed error as every other refusal in this package.

        Raises:
            SsrfRejectionError: when ``decision`` rejects.
        """
        if decision.should_follow and decision.url is not None:
            return decision.url
        reason = (
            RejectionReason.REDIRECT_LOOP
            if "loop" in decision.reason
            else (
                RejectionReason.TOO_MANY_REDIRECTS
                if "exceeded" in decision.reason
                else RejectionReason.MALFORMED_URL
            )
        )
        raise SsrfRejectionError(reason, decision.reason)
