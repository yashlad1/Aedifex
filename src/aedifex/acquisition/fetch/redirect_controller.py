"""Following redirects without ever leaving the guard.

A redirect is not a continuation of a request. It is a new request, to a destination chosen by a
remote server, and treating it as anything else is how SSRF protection gets bypassed by a server
that answers ``302 Location: http://169.254.169.254/``. So every hop goes back to the beginning:

.. code-block:: text

    URL (untrusted, including the first one)
      ↓  validate_url  ── scheme, credentials, host allowlist, DNS, every address
    ValidatedTarget
      ↓  RetryController  ── rate-limit slot per attempt, one shared budget
    response
      ↓  3xx?
      ├── no   → hand the open stream to the caller
      └── yes  → RedirectPolicy: hop cap, loop, downgrade, resolve Location
                    ↓
                 back to the top, with the resolved URL

The first URL is validated by the same call as every subsequent one. That is deliberate: a design
where the caller validates the initial URL and the controller validates the rest has two code paths
where it needs one, and the one that gets forgotten is the one an attacker uses.

What this module adds over :class:`RedirectPolicy`, which already decides hop caps, loops, transport
downgrades, and relative resolution:

**Re-validation.** The policy returns a URL and explicitly does not grant permission to fetch it.
Only :func:`validate_url` does that, and it is called for every hop, with the source's own host
allowlist — so a redirect cannot walk to a host the source was never permitted (FR-111).

**A second, canonical loop check.** The policy compares resolved URL strings. Normalisation can make
two different strings the same destination — a default port, a case difference in the host — so the
canonical URL that validation produces is checked against the chain as well. Both checks reject, so
there is no risk of them disagreeing in a dangerous direction, and the cheap one catches the common
case first.

**Header rebuilding across hosts.** Caller-supplied headers are dropped when the hostname changes
(FR-114). Nothing sends credentials today, which is exactly when this is cheap to get right: the
rule is in place before there is anything valuable to leak to whichever host a redirect names.

**Chain provenance.** Every hop is recorded with the URL requested, the status, and the raw
``Location`` — so the requested URL and the URL that actually answered are both retained (FR-115).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from aedifex.acquisition.fetch.controller import (
    AttemptRecord,
    Cancellation,
    RetryController,
)
from aedifex.acquisition.fetch.guard import ValidatedTarget, validate_url
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.ratelimit import RateLimits
from aedifex.acquisition.fetch.redirects import (
    REDIRECT_STATUSES,
    RedirectPolicy,
)
from aedifex.acquisition.fetch.resolver import Resolver
from aedifex.acquisition.fetch.retry import AttemptOutcome
from aedifex.acquisition.fetch.timing import TimeoutBudget
from aedifex.acquisition.fetch.transport import (
    DEFAULT_MAX_RESPONSE_BYTES,
    RawResponse,
)
from aedifex.acquisition.fetch.urls import SsrfRejectionError
from aedifex.errors import AcquisitionError

__all__ = [
    "ChainResult",
    "RedirectController",
    "RedirectHop",
    "RedirectRejectedError",
]


@dataclass(frozen=True, slots=True)
class RedirectHop:
    """One request in a redirect chain, recorded whether it redirected or answered."""

    url: str
    """The canonical URL that was requested, as validation produced it."""
    status_code: int
    location: str | None = None
    """The raw ``Location`` header, kept verbatim. Untrusted, and never used unresolved."""
    attempts: tuple[AttemptRecord, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ChainResult:
    """The response that finally answered, plus everything it took to get there."""

    response: RawResponse
    requested_url: str
    """What the caller asked for."""
    final_url: str
    """What actually answered. Different from ``requested_url`` when redirects were followed."""
    chain: tuple[RedirectHop, ...] = field(default_factory=tuple)

    @property
    def attempts(self) -> tuple[AttemptRecord, ...]:
        """Every attempt across every hop, in order."""
        return tuple(attempt for hop in self.chain for attempt in hop.attempts)

    @property
    def hop_count(self) -> int:
        """Redirects followed. Zero when the first URL answered."""
        return max(0, len(self.chain) - 1)

    @property
    def was_redirected(self) -> bool:
        return self.hop_count > 0


class RedirectRejectedError(AcquisitionError):
    """A redirect was refused, or a hop failed validation.

    Carries the chain so far, because "rejected at hop 3 after two legitimate redirects" is a
    different diagnosis from "rejected immediately", and the difference matters when deciding
    whether a source is misconfigured or hostile.
    """

    def __init__(
        self,
        message: str,
        *,
        final_outcome: AttemptOutcome,
        chain: tuple[RedirectHop, ...],
    ) -> None:
        super().__init__(message)
        self.final_outcome = final_outcome
        self.chain = chain


class RedirectController:
    """Fetches a URL, following redirects, re-validating every destination."""

    def __init__(
        self,
        *,
        controller: RetryController,
        resolver: Resolver,
        policy: RedirectPolicy | None = None,
    ) -> None:
        self._controller = controller
        self._resolver = resolver
        self._policy = policy if policy is not None else RedirectPolicy()

    @contextmanager
    def fetch(
        self,
        url: str,
        *,
        host_policy: SourceHostPolicy,
        limits: RateLimits,
        budget: TimeoutBudget,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        cancellation: Cancellation | None = None,
        body: bytes | None = None,
    ) -> Iterator[ChainResult]:
        """Fetch ``url`` for ``host_policy``'s source, following redirects within policy.

        ``url`` is untrusted and is validated before anything connects, by the same call every hop
        uses.

        Raises:
            RedirectRejectedError: when a redirect is refused by policy, or a hop fails SSRF
                validation. Carries the chain.
            FetchFailedError: when a hop's own attempts were exhausted. It carries that hop's
                attempt history and names the hop in its message, but not the chain that led there:
                the failure belongs to the retry controller, and inventing a chain-carrying variant
                of it would give one condition two error types. A fetch that never produced a
                document has no provenance to record, so this is a diagnostic gap and not a
                correctness one.
        """
        chain: list[RedirectHop] = []
        visited: list[str] = []
        current_url = url
        current_method = method
        current_headers = headers
        current_body = body

        while True:
            target = self._validate(current_url, host_policy=host_policy, chain=tuple(chain))
            if target.url in visited:
                # Normalisation can turn two different strings into one destination, which a
                # string comparison against the raw Location would miss.
                raise RedirectRejectedError(
                    f"redirect loop: {target.url} was already requested in this chain",
                    final_outcome=AttemptOutcome.INVALID_REDIRECT,
                    chain=tuple(chain),
                )
            visited.append(target.url)

            with ExitStack() as stack:
                result = stack.enter_context(
                    self._controller.fetch(
                        target,
                        limits=limits,
                        # One budget for the whole chain, not one per hop. Five hops each with a
                        # fresh allowance is five times the timeout the caller asked for.
                        budget=budget,
                        method=current_method,
                        headers=current_headers,
                        max_response_bytes=max_response_bytes,
                        cancellation=cancellation,
                        body=current_body,
                    )
                )
                status = result.response.status_code

                if status not in REDIRECT_STATUSES:
                    chain.append(
                        RedirectHop(
                            url=target.url,
                            status_code=status,
                            attempts=result.attempts,
                        )
                    )
                    yield ChainResult(
                        response=result.response,
                        requested_url=url,
                        final_url=target.url,
                        chain=tuple(chain),
                    )
                    return

                location = result.response.headers.get("location")
                chain.append(
                    RedirectHop(
                        url=target.url,
                        status_code=status,
                        location=location,
                        attempts=result.attempts,
                    )
                )
                decision = self._policy.evaluate(
                    status_code=status,
                    location=location,
                    current_url=target.url,
                    current_scheme=target.scheme,
                    history=tuple(visited),
                )
                if not decision.should_follow or decision.url is None:
                    raise RedirectRejectedError(
                        f"redirect from {target.url} refused: {decision.reason}",
                        final_outcome=AttemptOutcome.INVALID_REDIRECT,
                        chain=tuple(chain),
                    )
                next_url = decision.url
                rewrite_to_get = decision.rewrite_method_to_get

            # Outside the stack: this hop's response is closed and its slot returned before the
            # next hop asks for capacity.
            if rewrite_to_get:
                # 303 means "fetch this other thing instead", so the method becomes GET and the
                # body goes with it. redirects.py predicted that omitting this would become a
                # correctness bug once POST existed. It exists now, and a body carried onto a GET is
                # rejected by the transport at best, and sent to a server that never asked for it at
                # worst.
                current_method = "GET"
                current_body = None
            if _crosses_host(target.hostname, next_url):
                # Rebuilt, not carried over. A header set for one host has no business being sent
                # to another one that a remote server chose (FR-114).
                current_headers = None
                # And neither does a body. A remote server that answers a POST with a redirect to a
                # host of its choosing must not receive the form we sent to the first one.
                current_body = None
                current_method = "GET"
            current_url = next_url

    def _validate(
        self,
        url: str,
        *,
        host_policy: SourceHostPolicy,
        chain: tuple[RedirectHop, ...],
    ) -> ValidatedTarget:
        """Validate one URL, converting a rejection into a chain-carrying failure."""
        try:
            return validate_url(url, policy=host_policy, resolver=self._resolver)
        except SsrfRejectionError as error:
            raise RedirectRejectedError(
                f"redirect target {url} failed validation: {error}",
                final_outcome=AttemptOutcome.SSRF_REJECTED,
                chain=chain,
            ) from error


def _crosses_host(current_hostname: str, next_url: str) -> bool:
    """Whether ``next_url`` names a different host than the one just contacted.

    Parsed with :func:`urlsplit` rather than by hand, so this agrees with the parser the guard
    itself uses about where the host ends — the userinfo in ``https://cpwd.test@evil.test/`` names
    ``evil.test``, and a decoy in that position must not decide who receives a header.

    Anything inconclusive counts as a crossing: an unparseable authority, or none at all. The cost
    of dropping a header we could have kept is a header; the cost of the opposite mistake is
    handing one to whichever host a remote server named. The comparison is on the host alone, so a
    port or case difference is not a crossing — a trailing-dot form is, which errs the safe way.
    """
    try:
        host = urlsplit(next_url).hostname
    except ValueError:
        return True
    if not host:
        return True
    return host.lower() != current_hostname.lower()
