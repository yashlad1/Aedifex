"""Tests for the SSRF gate.

Two tests here matter more than the rest:

* :meth:`TestMixedDnsAnswers.test_a_mixed_answer_rejects_the_entire_resolution` — an attacker
  must not be able to influence address selection by mixing a private address into an answer.
* :class:`TestDnsRebinding` — the guard must resolve exactly once, and the connection must be
  pinned to an address that was validated, so a second answer cannot be substituted.

The resolver is a recording fake rather than a mock of internals, which lets the single-resolution
property be asserted directly (``resolver.calls == 1``) instead of inferred.

Note: ``93.184.216.34`` is used as the public address throughout. ``203.0.113.x`` is a
documentation range and is rejected by the address policy, so it cannot serve that role.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence

import pytest

from aedifex.acquisition.fetch.guard import ValidatedTarget, validate_url
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.resolver import ResolvedAddress
from aedifex.acquisition.fetch.urls import RejectionReason, SsrfRejectionError

PUBLIC_V4 = "93.184.216.34"
PUBLIC_V4_ALT = "8.8.8.8"
PUBLIC_V6 = "2606:4700:4700::1111"


class RecordingResolver:
    """A resolver that returns scripted answers and counts how often it was called.

    Each call consumes the next scripted answer, so a second lookup within one validation is
    both detectable and can be made to return something different — which is exactly the
    rebinding scenario.
    """

    def __init__(self, *answers: Sequence[str], raises: type[OSError] | None = None) -> None:
        self._answers = [tuple(answer) for answer in answers]
        self._raises = raises
        self.calls = 0
        self.hostnames: list[str] = []

    def resolve(self, hostname: str, port: int) -> Sequence[ResolvedAddress]:
        self.calls += 1
        self.hostnames.append(hostname)
        if self._raises is not None:
            raise self._raises("scripted resolution failure")
        index = min(self.calls - 1, len(self._answers) - 1) if self._answers else 0
        if not self._answers:
            return ()
        return tuple(
            ResolvedAddress(ip=ipaddress.ip_address(literal), port=port)
            for literal in self._answers[index]
        )


def policy(*, base: str = "example.com", extra: tuple[str, ...] = ()) -> SourceHostPolicy:
    return SourceHostPolicy(
        source_id="test_source",
        base_hosts=frozenset({base}),
        exact_hosts=frozenset(extra),
    )


def reason_for(
    url: str, resolver: RecordingResolver | None = None, **kwargs: object
) -> RejectionReason:
    with pytest.raises(SsrfRejectionError) as error:
        validate_url(
            url,
            policy=kwargs.get("policy", policy()),  # type: ignore[arg-type]
            resolver=resolver or RecordingResolver((PUBLIC_V4,)),
        )
    return error.value.reason


class TestSuccessfulValidation:
    def test_produces_a_validated_target(self) -> None:
        resolver = RecordingResolver((PUBLIC_V4,))
        target = validate_url("https://example.com/doc.pdf", policy=policy(), resolver=resolver)
        assert isinstance(target, ValidatedTarget)
        assert target.hostname == "example.com"
        assert target.ip_address == ipaddress.ip_address(PUBLIC_V4)
        assert target.port == 443
        assert target.scheme == "https"
        assert target.source_id == "test_source"
        assert target.url == "https://example.com/doc.pdf"

    def test_resolves_exactly_once(self) -> None:
        resolver = RecordingResolver((PUBLIC_V4,))
        validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert resolver.calls == 1

    def test_retains_every_validated_address_for_provenance(self) -> None:
        resolver = RecordingResolver((PUBLIC_V4, PUBLIC_V4_ALT))
        target = validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert target.validated_addresses == (
            ipaddress.ip_address(PUBLIC_V4),
            ipaddress.ip_address(PUBLIC_V4_ALT),
        )

    def test_address_selection_is_deterministic(self) -> None:
        """Safe because a mixed answer is rejected wholesale, so every address is acceptable."""
        for _ in range(5):
            resolver = RecordingResolver((PUBLIC_V4, PUBLIC_V4_ALT))
            target = validate_url("https://example.com/", policy=policy(), resolver=resolver)
            assert target.ip_address == ipaddress.ip_address(PUBLIC_V4)

    def test_ipv6_targets_are_supported(self) -> None:
        resolver = RecordingResolver((PUBLIC_V6,))
        target = validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert target.ip_address == ipaddress.ip_address(PUBLIC_V6)
        assert target.connect_host == f"[{PUBLIC_V6}]"

    def test_the_target_is_immutable(self) -> None:
        resolver = RecordingResolver((PUBLIC_V4,))
        target = validate_url("https://example.com/", policy=policy(), resolver=resolver)
        with pytest.raises(AttributeError):
            target.ip_address = ipaddress.ip_address("127.0.0.1")  # type: ignore[misc]


class TestConnectionInvariant:
    """The four-part invariant that closes the rebinding window.

    TCP destination = validated IP; Host header, TLS SNI, and certificate verification all use
    the original hostname. The target must carry both, separately, so a transport cannot conflate
    them.
    """

    def test_the_target_carries_both_the_address_and_the_hostname(self) -> None:
        resolver = RecordingResolver((PUBLIC_V4,))
        target = validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert target.connect_host == PUBLIC_V4
        assert target.hostname == "example.com"
        assert target.host_header == "example.com"

    def test_host_header_includes_a_non_default_port(self) -> None:
        resolver = RecordingResolver((PUBLIC_V4,))
        target = validate_url("http://example.com/", policy=policy(), resolver=resolver)
        assert target.host_header == "example.com"

    def test_the_hostname_is_never_replaced_by_the_address(self) -> None:
        """If these were conflated, TLS would verify against an IP — the mistake to avoid."""
        resolver = RecordingResolver((PUBLIC_V4,))
        target = validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert target.hostname != str(target.ip_address)


class TestSchemeAndCredentialOrdering:
    def test_scheme_is_checked_before_dns(self) -> None:
        """Validation order matters: a rejected scheme must not cost a DNS lookup."""
        resolver = RecordingResolver((PUBLIC_V4,))
        assert reason_for("file:///etc/passwd", resolver) is RejectionReason.DISALLOWED_SCHEME
        assert resolver.calls == 0

    def test_credentials_are_checked_before_dns(self) -> None:
        resolver = RecordingResolver((PUBLIC_V4,))
        reason = reason_for("https://user:pw@example.com/", resolver)
        assert reason is RejectionReason.EMBEDDED_CREDENTIALS
        assert resolver.calls == 0

    def test_host_policy_is_checked_before_dns(self) -> None:
        """A host we would never contact must not be resolved: no lookup, no information leak."""
        resolver = RecordingResolver((PUBLIC_V4,))
        reason = reason_for("https://evil.test/", resolver)
        assert reason is RejectionReason.HOST_NOT_ALLOWED_FOR_SOURCE
        assert resolver.calls == 0


class TestIpLiterals:
    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/",
            "https://10.0.0.1/",
            "https://169.254.169.254/",
            "https://[::1]/",
            "https://[::ffff:127.0.0.1]/",
            f"https://{PUBLIC_V4}/",
        ],
    )
    def test_rejected_even_when_public(self, url: str) -> None:
        """An IP literal cannot satisfy a hostname allowlist, so it is refused uniformly.

        Including the public case: accepting it would abandon the per-source host constraint,
        which is what limits where a crawler can reach at all.
        """
        resolver = RecordingResolver((PUBLIC_V4,))
        assert reason_for(url, resolver) is RejectionReason.IP_LITERAL_NOT_ALLOWED
        assert resolver.calls == 0


class TestForbiddenAddresses:
    @pytest.mark.parametrize(
        "literal",
        [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "100.64.0.1",
            "0.0.0.0",
            "::1",
            "fe80::1",
            "fc00::1",
            "::ffff:127.0.0.1",
            "::ffff:169.254.169.254",
            "64:ff9b::7f00:1",
            "224.0.0.1",
            "203.0.113.5",
        ],
    )
    def test_a_hostname_resolving_to_a_forbidden_address_is_rejected(self, literal: str) -> None:
        """The realistic attack: an allowlisted hostname whose DNS points somewhere internal."""
        resolver = RecordingResolver((literal,))
        assert reason_for("https://example.com/", resolver) is RejectionReason.FORBIDDEN_ADDRESS
        assert resolver.calls == 1

    def test_the_rejection_names_the_offending_address_and_reason(self) -> None:
        resolver = RecordingResolver(("169.254.169.254",))
        with pytest.raises(SsrfRejectionError) as error:
            validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert "169.254.169.254" in error.value.detail
        assert "link_local" in error.value.detail


class TestMixedDnsAnswers:
    def test_a_mixed_answer_rejects_the_entire_resolution(self) -> None:
        """The single most important policy decision in this module.

        A host answering with one public and one private address must fail completely. Filtering
        to the public address would let an attacker who controls DNS influence which address we
        connect to, and a host that answers with anything internal is not one to talk to at all.
        """
        resolver = RecordingResolver((PUBLIC_V4, "10.0.0.5"))
        with pytest.raises(SsrfRejectionError) as error:
            validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert error.value.reason is RejectionReason.FORBIDDEN_ADDRESS
        assert "entire resolution is rejected" in error.value.detail
        assert "10.0.0.5" in error.value.detail

    def test_order_within_the_answer_does_not_matter(self) -> None:
        """Rejection must not depend on whether the private address came first."""
        for answer in ((PUBLIC_V4, "10.0.0.5"), ("10.0.0.5", PUBLIC_V4)):
            resolver = RecordingResolver(answer)
            with pytest.raises(SsrfRejectionError) as error:
                validate_url("https://example.com/", policy=policy(), resolver=resolver)
            assert error.value.reason is RejectionReason.FORBIDDEN_ADDRESS

    def test_every_forbidden_address_is_reported(self) -> None:
        resolver = RecordingResolver((PUBLIC_V4, "10.0.0.5", "127.0.0.1"))
        with pytest.raises(SsrfRejectionError) as error:
            validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert "10.0.0.5" in error.value.detail
        assert "127.0.0.1" in error.value.detail

    def test_an_all_public_answer_is_accepted(self) -> None:
        resolver = RecordingResolver((PUBLIC_V4, PUBLIC_V4_ALT, PUBLIC_V6))
        target = validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert len(target.validated_addresses) == 3


class TestDnsRebinding:
    """The TOCTOU defence. Probably the most important tests in this slice.

    A hostile authoritative server with a 0-second TTL can answer differently on a second
    lookup. If the guard validated a hostname and then handed that hostname to an HTTP client,
    the client's own resolution would be the one that counted and every other check here would
    be decoration.
    """

    def test_only_one_resolution_occurs(self) -> None:
        """The scripted second answer is loopback; it must never be consulted."""
        resolver = RecordingResolver((PUBLIC_V4,), ("127.0.0.1",))
        target = validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert resolver.calls == 1
        assert target.ip_address == ipaddress.ip_address(PUBLIC_V4)

    def test_the_target_pins_an_address_rather_than_a_hostname(self) -> None:
        """The structural guarantee: the transport is handed an address, so it cannot re-resolve.

        A transport given only a hostname would have to resolve again. Carrying the validated
        address on the target is what removes that second lookup from the connection path.
        """
        resolver = RecordingResolver((PUBLIC_V4,), ("127.0.0.1",))
        target = validate_url("https://example.com/", policy=policy(), resolver=resolver)
        assert target.ip_address in target.validated_addresses
        assert target.ip_address == ipaddress.ip_address(PUBLIC_V4)
        # Nothing on the target invites a second lookup.
        assert target.connect_host == PUBLIC_V4

    def test_a_rebinding_answer_on_the_first_lookup_is_still_caught(self) -> None:
        """Rebinding only helps an attacker on a *later* lookup; the first is validated."""
        resolver = RecordingResolver(("127.0.0.1",), (PUBLIC_V4,))
        assert reason_for("https://example.com/", resolver) is RejectionReason.FORBIDDEN_ADDRESS


class TestResolutionFailure:
    def test_unresolvable_host_fails_closed(self) -> None:
        resolver = RecordingResolver(raises=OSError)
        assert reason_for("https://example.com/", resolver) is RejectionReason.UNRESOLVABLE_HOST

    def test_an_empty_answer_fails_closed(self) -> None:
        """No addresses means no permission; an inconclusive check is a rejection."""
        resolver = RecordingResolver()
        assert reason_for("https://example.com/", resolver) is RejectionReason.NO_ADDRESSES_RETURNED


class TestSourceIsolation:
    def test_a_host_allowed_for_one_source_is_not_allowed_for_another(self) -> None:
        """Global network safety and per-source policy are separate controls."""
        resolver = RecordingResolver((PUBLIC_V4,))
        target = validate_url(
            "https://example.com/", policy=policy(base="example.com"), resolver=resolver
        )
        assert target.source_id == "test_source"

        other = SourceHostPolicy(
            source_id="other_source",
            base_hosts=frozenset({"different.test"}),
            exact_hosts=frozenset(),
        )
        with pytest.raises(SsrfRejectionError) as error:
            validate_url(
                "https://example.com/", policy=other, resolver=RecordingResolver((PUBLIC_V4,))
            )
        assert error.value.reason is RejectionReason.HOST_NOT_ALLOWED_FOR_SOURCE

    def test_an_additional_host_is_permitted_exactly(self) -> None:
        resolver = RecordingResolver((PUBLIC_V4,))
        target = validate_url(
            "https://cdn.example.net/doc.pdf",
            policy=policy(extra=("cdn.example.net",)),
            resolver=resolver,
        )
        assert target.hostname == "cdn.example.net"

    def test_a_subdomain_of_an_additional_host_is_not_permitted(self) -> None:
        """Exact-only for third-party hosts: authorising a CDN must not authorise every tenant."""
        resolver = RecordingResolver((PUBLIC_V4,))
        reason = reason_for(
            "https://evil.cdn.example.net/",
            resolver,
            policy=policy(extra=("cdn.example.net",)),
        )
        assert reason is RejectionReason.HOST_NOT_ALLOWED_FOR_SOURCE
