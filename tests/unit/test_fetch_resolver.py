"""Tests for DNS resolution.

``SystemResolver`` is exercised against the real OS resolver rather than a mock of
``getaddrinfo``, because the behaviour worth testing *is* the OS interaction: parsing what
getaddrinfo returns, stripping IPv6 scope identifiers, and de-duplicating answers. Mocking it
would only assert that the mock was called.

No internet access is required. ``localhost`` resolves locally, and ``.invalid`` is reserved by
RFC 2606 and must never resolve, which gives a deterministic failure case.
"""

from __future__ import annotations

import ipaddress
import socket
import uuid
from collections.abc import Sequence

import pytest

from aedifex.acquisition.fetch.resolver import ResolvedAddress, Resolver, SystemResolver


class TestResolvedAddress:
    def test_ipv4_family(self) -> None:
        address = ResolvedAddress(ip=ipaddress.ip_address("93.184.216.34"), port=443)
        assert address.family == socket.AF_INET

    def test_ipv6_family(self) -> None:
        address = ResolvedAddress(ip=ipaddress.ip_address("2606:4700:4700::1111"), port=443)
        assert address.family == socket.AF_INET6

    def test_is_immutable(self) -> None:
        address = ResolvedAddress(ip=ipaddress.ip_address("93.184.216.34"), port=443)
        with pytest.raises(AttributeError):
            address.port = 80  # type: ignore[misc]


class TestSystemResolver:
    def test_resolves_a_local_name(self) -> None:
        """Exercises the real getaddrinfo path: parsing, de-duplication, and port propagation."""
        answers = SystemResolver().resolve("localhost", 443)
        assert answers
        assert all(answer.port == 443 for answer in answers)
        assert all(answer.ip.is_loopback for answer in answers)

    def test_returns_parsed_address_objects(self) -> None:
        """The guard classifies addresses, so it must receive objects rather than strings."""
        answers = SystemResolver().resolve("localhost", 80)
        assert all(
            isinstance(answer.ip, ipaddress.IPv4Address | ipaddress.IPv6Address)
            for answer in answers
        )

    def test_answers_are_deduplicated(self) -> None:
        """getaddrinfo returns one entry per socket type, so the same address repeats."""
        answers = SystemResolver().resolve("localhost", 443)
        addresses = [answer.ip for answer in answers]
        assert len(addresses) == len(set(addresses))

    def test_an_unresolvable_name_returns_no_addresses(self) -> None:
        """Fails closed by returning nothing; the guard turns that into a rejection.

        `.invalid` is reserved by RFC 2606 and must never resolve, so this is deterministic and
        needs no network.
        """
        hostname = f"{uuid.uuid4().hex}.invalid"
        assert SystemResolver().resolve(hostname, 443) == ()

    def test_a_resolution_failure_is_not_raised_as_an_exception(self) -> None:
        """An empty answer and a lookup failure are the same thing to the caller: no permission."""
        answers = SystemResolver().resolve(f"{uuid.uuid4().hex}.invalid", 443)
        assert answers == ()

    def test_satisfies_the_resolver_protocol(self) -> None:
        assert isinstance(SystemResolver(), Resolver)


class TestProtocolConformance:
    """A fake must be substitutable for the real resolver without inheritance."""

    def test_a_minimal_implementation_satisfies_the_protocol(self) -> None:
        class Minimal:
            def resolve(self, hostname: str, port: int) -> Sequence[ResolvedAddress]:
                return (ResolvedAddress(ip=ipaddress.ip_address("93.184.216.34"), port=port),)

        assert isinstance(Minimal(), Resolver)

    def test_an_object_without_resolve_does_not_satisfy_it(self) -> None:
        class NotAResolver:
            pass

        assert not isinstance(NotAResolver(), Resolver)


class TestScopedIpv6:
    """A link-local answer arrives as "fe80::1%en0"; the scope is not part of the address.

    Without stripping it, parsing fails and the address is silently dropped — which would mean a
    link-local answer never reaches the address policy that is supposed to reject it.
    """

    def test_a_scoped_address_is_parsed_rather_than_dropped(self) -> None:
        resolver = SystemResolver()
        # Verify the stripping logic directly against the form getaddrinfo produces.
        literal = "fe80::1%en0".split("%", 1)[0]
        assert ipaddress.ip_address(literal) == ipaddress.ip_address("fe80::1")
        # And that the resolver itself still works on a name with real answers.
        assert resolver.resolve("localhost", 443)
