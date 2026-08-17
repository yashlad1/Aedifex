"""Tests for the global network safety policy.

The corpus is exhaustive by intent. Every future crawler depends on this function, and a single
missing range is a full SSRF bypass, so each address is asserted individually with the reason it
is rejected for — not merely that it is rejected.

Note on "public" test addresses: ``203.0.113.5`` is **not** usable as one. It is TEST-NET-3,
a documentation range, which ``ipaddress`` reports as private and this policy therefore rejects.
``93.184.216.34`` and ``8.8.8.8`` are genuinely globally routable and are used instead.
"""

from __future__ import annotations

import ipaddress

import pytest

from aedifex.acquisition.fetch.addresses import (
    AddressRejection,
    classify_address,
    is_publicly_routable,
)


def classify(literal: str) -> AddressRejection | None:
    return classify_address(ipaddress.ip_address(literal))


class TestLoopback:
    @pytest.mark.parametrize("literal", ["127.0.0.1", "127.0.0.53", "127.255.255.255", "::1"])
    def test_rejected(self, literal: str) -> None:
        assert classify(literal) is AddressRejection.LOOPBACK


class TestUnspecified:
    @pytest.mark.parametrize("literal", ["0.0.0.0", "::"])
    def test_rejected(self, literal: str) -> None:
        """0.0.0.0 routes to localhost on several stacks, so it is a loopback in disguise."""
        assert classify(literal) is AddressRejection.UNSPECIFIED


class TestPrivateRfc1918:
    @pytest.mark.parametrize(
        "literal",
        [
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.0.1",
            "192.168.1.1",
        ],
    )
    def test_rejected(self, literal: str) -> None:
        assert classify(literal) is AddressRejection.PRIVATE

    @pytest.mark.parametrize("literal", ["172.15.0.1", "172.32.0.1"])
    def test_addresses_just_outside_the_range_are_not_private(self, literal: str) -> None:
        """Guards against an off-by-one in the 172.16/12 boundary."""
        assert classify(literal) is not AddressRejection.PRIVATE


class TestLinkLocalAndMetadata:
    @pytest.mark.parametrize("literal", ["169.254.169.254", "169.254.0.1", "169.254.255.255"])
    def test_ipv4_link_local_rejected(self, literal: str) -> None:
        """169.254.169.254 is the cloud metadata endpoint: the highest-value SSRF target."""
        assert classify(literal) is AddressRejection.LINK_LOCAL

    @pytest.mark.parametrize("literal", ["fe80::1", "fe80::ffff:ffff:ffff:ffff", "febf::1"])
    def test_ipv6_link_local_rejected(self, literal: str) -> None:
        assert classify(literal) is AddressRejection.LINK_LOCAL


class TestCarrierGradeNat:
    @pytest.mark.parametrize("literal", ["100.64.0.1", "100.127.255.254", "100.100.100.100"])
    def test_rejected(self, literal: str) -> None:
        """`is_private` is False for 100.64.0.0/10, so this needs its own check."""
        assert classify(literal) is AddressRejection.CARRIER_GRADE_NAT

    @pytest.mark.parametrize("literal", ["100.63.255.255", "100.128.0.1"])
    def test_addresses_outside_the_shared_range_are_not_cgnat(self, literal: str) -> None:
        assert classify(literal) is not AddressRejection.CARRIER_GRADE_NAT


class TestUniqueLocalIpv6:
    @pytest.mark.parametrize("literal", ["fc00::1", "fd00::1", "fdff::1"])
    def test_rejected(self, literal: str) -> None:
        assert classify(literal) is AddressRejection.PRIVATE


class TestIpv4MappedIpv6:
    @pytest.mark.parametrize(
        "literal",
        [
            "::ffff:127.0.0.1",
            "::ffff:10.0.0.1",
            "::ffff:169.254.169.254",
            "::ffff:192.168.1.1",
        ],
    )
    def test_mapped_private_rejected(self, literal: str) -> None:
        """`::ffff:127.0.0.1` defeats any IPv4-only check, which is why this class exists."""
        assert classify(literal) is AddressRejection.IPV4_MAPPED

    def test_mapped_public_is_also_rejected(self) -> None:
        """Rejected even though the embedded address is routable, and `is_global` is True.

        The form itself is a canonicalisation hazard and no legitimate portal is reachable only
        this way, so it is refused outright rather than unwrapped and re-checked.
        """
        assert classify("::ffff:93.184.216.34") is AddressRejection.IPV4_MAPPED
        assert ipaddress.ip_address("::ffff:93.184.216.34").is_global is True


class TestEmbeddedIpv4Transitions:
    @pytest.mark.parametrize(
        "literal",
        [
            "64:ff9b::7f00:1",  # NAT64 wrapping 127.0.0.1
            "64:ff9b::a00:1",  # NAT64 wrapping 10.0.0.1
            "64:ff9b::5db8:d822",  # NAT64 wrapping a public address
            "64:ff9b:1::1",  # NAT64 local-use prefix
            "2002:7f00:1::1",  # 6to4
            "2001::1",  # Teredo
        ],
    )
    def test_rejected(self, literal: str) -> None:
        """These embed an arbitrary IPv4 address, and `is_global` is True for NAT64."""
        assert classify(literal) is AddressRejection.EMBEDDED_IPV4

    def test_nat64_is_reported_as_global_by_the_stdlib(self) -> None:
        """Documents precisely why an `is_global` check alone would be a bypass."""
        assert ipaddress.ip_address("64:ff9b::7f00:1").is_global is True


class TestMulticast:
    @pytest.mark.parametrize("literal", ["224.0.0.1", "239.255.255.255", "ff02::1", "ff05::1:3"])
    def test_rejected(self, literal: str) -> None:
        assert classify(literal) is AddressRejection.MULTICAST

    def test_multicast_is_reported_as_global_by_the_stdlib(self) -> None:
        """The second reason an `is_global` check alone would be a bypass."""
        assert ipaddress.ip_address("224.0.0.1").is_global is True
        assert ipaddress.ip_address("ff02::1").is_global is True


class TestReservedAndDocumentation:
    @pytest.mark.parametrize(
        "literal",
        [
            "203.0.113.5",  # TEST-NET-3
            "192.0.2.1",  # TEST-NET-1
            "198.51.100.1",  # TEST-NET-2
            "2001:db8::1",  # IPv6 documentation
            "198.18.0.1",  # benchmarking
        ],
    )
    def test_documentation_ranges_rejected(self, literal: str) -> None:
        """Not routable, so not contactable — and a link to one indicates a crawler bug.

        Reported as `documentation` rather than `private` so the diagnosis points at the real
        cause: an example URL that escaped into a real code path.
        """
        assert classify(literal) is AddressRejection.DOCUMENTATION

    def test_203_0_113_x_is_not_a_usable_public_test_address(self) -> None:
        """Recorded because it is a natural mistake when writing SSRF tests.

        TEST-NET-3 looks like a plausible public address and is widely used in examples, but the
        stdlib classifies it as private and this policy rejects it. Genuinely routable addresses
        must be used for the positive cases.
        """
        assert ipaddress.ip_address("203.0.113.5").is_global is False
        assert classify("203.0.113.5") is AddressRejection.DOCUMENTATION

    @pytest.mark.parametrize("literal", ["240.0.0.1", "255.255.255.255", "255.255.255.254"])
    def test_reserved_and_broadcast_rejected(self, literal: str) -> None:
        """`reserved` is checked before `private` since these ranges are both.

        240.0.0.0/4 is reserved for future use rather than documentation, and it contains the
        broadcast address — so it must not be reported as a documentation range.
        """
        assert classify(literal) is AddressRejection.RESERVED


class TestPubliclyRoutable:
    @pytest.mark.parametrize(
        "literal",
        [
            "93.184.216.34",
            "8.8.8.8",
            "1.1.1.1",
            "142.250.185.78",
            "2606:4700:4700::1111",
            "2001:4860:4860::8888",
        ],
    )
    def test_accepted(self, literal: str) -> None:
        assert classify(literal) is None
        assert is_publicly_routable(ipaddress.ip_address(literal)) is True


class TestPolicyCompleteness:
    def test_no_forbidden_address_is_reported_as_routable(self) -> None:
        """The two helpers must never disagree."""
        for literal in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"):
            address = ipaddress.ip_address(literal)
            assert classify_address(address) is not None
            assert is_publicly_routable(address) is False

    def test_every_rejection_reason_is_reachable(self) -> None:
        """A reason no address can produce is dead code that misleads a reader."""
        samples = {
            "::": AddressRejection.UNSPECIFIED,
            "127.0.0.1": AddressRejection.LOOPBACK,
            "10.0.0.1": AddressRejection.PRIVATE,
            "169.254.169.254": AddressRejection.LINK_LOCAL,
            "100.64.0.1": AddressRejection.CARRIER_GRADE_NAT,
            "224.0.0.1": AddressRejection.MULTICAST,
            "255.255.255.255": AddressRejection.RESERVED,
            "203.0.113.5": AddressRejection.DOCUMENTATION,
            "::ffff:127.0.0.1": AddressRejection.IPV4_MAPPED,
            "64:ff9b::7f00:1": AddressRejection.EMBEDDED_IPV4,
        }
        for literal, expected in samples.items():
            assert classify(literal) is expected, literal

        produced = set(samples.values())
        unreachable = set(AddressRejection) - produced
        # NOT_GLOBALLY_ROUTABLE is the deliberate catch-all and may have no example today.
        assert unreachable <= {AddressRejection.NOT_GLOBALLY_ROUTABLE}
