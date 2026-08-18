"""DNS resolution behind a protocol.

Injectable for two reasons, one of which is a security requirement rather than a testing
convenience:

1. **Provability.** The guard must resolve exactly once per validation, because a second lookup
   is the DNS-rebinding attack. A fake resolver lets a test assert ``calls == 1`` directly,
   rather than inferring it.
2. **Determinism.** Rebinding, mixed public/private answers, and resolution failure can be
   exercised without network access or mocking internals.

Synchronous, consistent with ADR 0005 and ADR 0010. The protocol is shaped so an async
implementation can be added later without changing callers' logic.
"""

from __future__ import annotations

import socket
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from aedifex.acquisition.fetch.addresses import IpAddress

__all__ = [
    "ResolvedAddress",
    "Resolver",
    "SystemResolver",
    "UnparseableDnsAnswerError",
]


class UnparseableDnsAnswerError(OSError):
    """The resolver returned an address literal that could not be parsed.

    Raised rather than skipping the offending answer. An earlier version of this module did skip
    it, which was a fail-*open* bug hiding inside a fail-closed-looking function: an IPv6 answer
    carrying a scope identifier (``fe80::1%en0``) failed to parse, was dropped, and a link-local
    address therefore never reached the policy whose only job was to reject it.

    Inside a security boundary, failure to parse means reject, never omit.
    """


@dataclass(frozen=True, slots=True)
class ResolvedAddress:
    """One address a hostname resolved to."""

    ip: IpAddress
    port: int

    @property
    def family(self) -> int:
        """Socket family, for the transport that eventually connects."""
        return socket.AF_INET if self.ip.version == 4 else socket.AF_INET6


@runtime_checkable
class Resolver(Protocol):
    """Resolves a hostname to addresses."""

    def resolve(self, hostname: str, port: int) -> Sequence[ResolvedAddress]:
        """Return every address ``hostname`` resolves to.

        Implementations must return an empty sequence rather than raising when a host simply has
        no records, and may raise :class:`OSError` for resolution failures. The guard treats both
        as a rejection, so failure is always closed.
        """
        ...


class SystemResolver:
    """Resolver backed by the operating system, via :func:`socket.getaddrinfo`."""

    def resolve(self, hostname: str, port: int) -> Sequence[ResolvedAddress]:
        """Resolve ``hostname``, returning both IPv4 and IPv6 answers.

        Both families are requested deliberately. Resolving only one would let a host with a
        safe A record and a hostile AAAA record escape validation of the address actually used,
        depending on connection order.
        """
        try:
            infos = socket.getaddrinfo(
                hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
            )
        except socket.gaierror:
            return ()

        addresses: list[ResolvedAddress] = []
        seen: set[IpAddress] = set()
        for info in infos:
            sockaddr = info[4]
            # getaddrinfo yields (host, port) for IPv4 and (host, port, flowinfo, scope_id) for
            # IPv6; the textual address is always first.
            literal = str(sockaddr[0])
            # A scoped IPv6 address arrives as "fe80::1%en0"; the scope is not part of the
            # address and would fail parsing.
            literal = literal.split("%", 1)[0]
            try:
                address = _parse(literal)
            except ValueError as error:
                # Reject the whole resolution rather than dropping this answer. Skipping would
                # mean an address we could not classify never reaches the policy that would have
                # rejected it, which fails open and leaves no trace.
                raise UnparseableDnsAnswerError(
                    f"resolver returned an unparseable address for {hostname!r}: {literal!r}"
                ) from error
            if address in seen:
                continue
            seen.add(address)
            addresses.append(ResolvedAddress(ip=address, port=port))
        return tuple(addresses)


def _parse(literal: str) -> IpAddress:
    import ipaddress

    return ipaddress.ip_address(literal)
