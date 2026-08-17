"""The SSRF gate: the only way to obtain permission to make an outbound request.

Validation order, rejecting at the first failure (FR-100):

.. code-block:: text

    Untrusted URL
        ↓  parse + normalize                    (urls.normalize_url)
        ↓  allowed scheme?
        ↓  no embedded credentials?
        ↓  hostname permitted by source policy? (hosts.SourceHostPolicy)
        ↓  resolve exactly once                 (resolver.Resolver)
        ↓  normalize IPv4 / IPv6 representation
        ↓  validate EVERY resolved address      (addresses.classify_address)
        ↓  reject any forbidden address         → REJECT THE WHOLE RESOLUTION
        ↓  choose a validated address
        ↓  ValidatedTarget

The type is the control. :class:`ValidatedTarget` can only be produced here, and the transport
layer accepts nothing else — so "developers must remember to validate" becomes "the transport
cannot be called without a value that only validation produces". A plain ``str`` cannot reach a
socket.

**A mixed answer is rejected entirely.** If a hostname resolves to one public and one private
address, the whole resolution fails; the private address is not skipped in favour of the public
one. Otherwise an attacker who controls DNS could influence address selection, and — more
importantly — a host that answers with anything internal is not a host we should be talking to.
This also removes any question of selection bias: because every returned address must be
acceptable, connecting to the first is safe and deterministic.

**Connection invariant, security-critical.** The transport must honour all four of these:

===========================  ==========================================
TCP destination              the validated ``ip_address``
HTTP ``Host`` header         the original ``hostname``
TLS SNI                      the original ``hostname``
TLS certificate verification the original ``hostname``
===========================  ==========================================

Never verify a certificate against the IP address, and never disable verification. If the HTTP
library makes this awkward, write a narrow transport adapter — do not weaken the model. Tying
the connection to an already-validated address is what closes the DNS-rebinding window: no
second resolution happens, so no second answer can be substituted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from aedifex.acquisition.fetch.addresses import IpAddress, classify_address
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.resolver import ResolvedAddress, Resolver
from aedifex.acquisition.fetch.urls import (
    NormalizedUrl,
    RejectionReason,
    SsrfRejectionError,
    normalize_url,
)

__all__ = ["ValidatedTarget", "validate_url"]


@dataclass(frozen=True, slots=True)
class ValidatedTarget:
    """Permission to contact one specific address, on behalf of one specific source.

    Produced only by :func:`validate_url`. Frozen, so a validated destination cannot be edited
    into an unvalidated one after the fact.
    """

    url: str
    """The canonical absolute URL to request."""
    scheme: str
    hostname: str
    """The name to use for the ``Host`` header, TLS SNI, and certificate verification."""
    port: int
    ip_address: IpAddress
    """The only address the transport may connect to."""
    source_id: str
    validated_addresses: tuple[IpAddress, ...]
    """Every address the resolution returned. All were validated; kept for provenance."""
    resolved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    was_ip_literal: bool = False
    """True when the URL named an address directly, so no DNS resolution occurred."""

    @property
    def connect_host(self) -> str:
        """The address in the textual form a socket expects, bracketed for IPv6."""
        return f"[{self.ip_address}]" if self.ip_address.version == 6 else str(self.ip_address)

    @property
    def host_header(self) -> str:
        """The ``Host`` header value: the hostname, with a non-default port when present."""
        default_port = 443 if self.scheme == "https" else 80
        host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        return host if self.port == default_port else f"{host}:{self.port}"

    def describe(self) -> str:
        """One-line summary for logs. Never includes a response body."""
        return (
            f"{self.scheme}://{self.hostname}:{self.port} via {self.ip_address} "
            f"(source={self.source_id})"
        )


def validate_url(
    raw_url: str,
    *,
    policy: SourceHostPolicy,
    resolver: Resolver,
) -> ValidatedTarget:
    """Validate ``raw_url`` for ``policy``'s source and return permission to fetch it.

    Args:
        raw_url: An untrusted URL, from a registry entry, scraped markup, or a redirect header.
        policy: Which hostnames this source may be fetched from.
        resolver: DNS resolution. Called at most once, and not at all for an IP literal.

    Returns:
        A :class:`ValidatedTarget` naming exactly one address to connect to.

    Raises:
        SsrfRejectionError: with a specific :class:`RejectionReason`. Every failure path raises;
            nothing is returned on a partial result, and an inconclusive check is a rejection.
    """
    normalized = normalize_url(raw_url)

    # An IP literal can never satisfy a hostname allowlist, and permitting one would give up the
    # per-source host constraint entirely. Rejected before address classification so the reason
    # names the real problem rather than reporting, say, "loopback" for a URL that was never
    # going to be acceptable in any case.
    if normalized.is_ip_literal:
        raise SsrfRejectionError(
            RejectionReason.IP_LITERAL_NOT_ALLOWED,
            f"{normalized.host} is an IP literal; source {policy.source_id!r} permits hosts: "
            f"{policy.describe()}",
        )

    if not policy.permits(normalized.host):
        raise SsrfRejectionError(
            RejectionReason.HOST_NOT_ALLOWED_FOR_SOURCE,
            f"host {normalized.host!r} is not permitted for source {policy.source_id!r}; "
            f"permitted: {policy.describe()}",
        )

    addresses = _resolve_once(normalized, resolver)
    validated = _validate_every_address(normalized, addresses)

    return ValidatedTarget(
        url=normalized.to_url(),
        scheme=normalized.scheme,
        hostname=normalized.host,
        port=normalized.port,
        # Safe and deterministic: every returned address passed validation, so the first is as
        # good as any other and the choice cannot be influenced.
        ip_address=validated[0],
        source_id=policy.source_id,
        validated_addresses=validated,
        was_ip_literal=False,
    )


def _resolve_once(normalized: NormalizedUrl, resolver: Resolver) -> tuple[ResolvedAddress, ...]:
    """Resolve the host exactly once, treating any failure as a rejection."""
    try:
        answers = tuple(resolver.resolve(normalized.host, normalized.port))
    except OSError as error:
        raise SsrfRejectionError(
            RejectionReason.UNRESOLVABLE_HOST,
            f"host {normalized.host!r} could not be resolved: {type(error).__name__}",
        ) from error

    if not answers:
        raise SsrfRejectionError(
            RejectionReason.NO_ADDRESSES_RETURNED,
            f"host {normalized.host!r} returned no addresses",
        )
    return answers


def _validate_every_address(
    normalized: NormalizedUrl, answers: tuple[ResolvedAddress, ...]
) -> tuple[IpAddress, ...]:
    """Validate all addresses, rejecting the entire resolution if any is forbidden."""
    forbidden: list[str] = []
    for answer in answers:
        rejection = classify_address(answer.ip)
        if rejection is not None:
            forbidden.append(f"{answer.ip} ({rejection.value})")

    if forbidden:
        # The whole answer is refused, not filtered. A host that answers with anything internal
        # is not one to talk to, and filtering would let DNS influence which address we use.
        raise SsrfRejectionError(
            RejectionReason.FORBIDDEN_ADDRESS,
            f"host {normalized.host!r} resolved to {len(answers)} address(es) including "
            f"forbidden: {', '.join(forbidden)}; the entire resolution is rejected",
        )
    return tuple(answer.ip for answer in answers)
