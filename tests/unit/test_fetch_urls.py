"""Tests for URL parsing and normalisation.

The property under test throughout: **the authority that gets validated is exactly the authority
that will be contacted.** The adversarial URLs below are not interesting because they are
unusual; they are interesting because a parser disagreement about which host they name is a
complete SSRF bypass.
"""

from __future__ import annotations

import pytest

from aedifex.acquisition.fetch.urls import (
    ALLOWED_PORTS,
    ALLOWED_SCHEMES,
    RejectionReason,
    SsrfRejectionError,
    normalize_url,
)


def reason_for(url: str) -> RejectionReason:
    with pytest.raises(SsrfRejectionError) as error:
        normalize_url(url)
    return error.value.reason


class TestSchemes:
    @pytest.mark.parametrize("url", ["https://example.com/", "http://example.com/"])
    def test_allowed_schemes(self, url: str) -> None:
        assert normalize_url(url).scheme in ALLOWED_SCHEMES

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.com/",
            "gopher://example.com/",
            "data:text/plain;base64,aGk=",
            "javascript:alert(1)",
            "//example.com/",
            "example.com/path",
            "ldap://example.com/",
            "dict://example.com/",
        ],
    )
    def test_other_schemes_rejected(self, url: str) -> None:
        """gopher and dict are classic SSRF gadgets for speaking to non-HTTP services."""
        assert reason_for(url) in {
            RejectionReason.DISALLOWED_SCHEME,
            RejectionReason.MALFORMED_URL,
        }

    def test_scheme_case_is_normalized(self) -> None:
        assert normalize_url("HTTPS://example.com/").scheme == "https"


class TestEmbeddedCredentials:
    @pytest.mark.parametrize(
        "url",
        [
            "https://user:password@example.com/",
            "https://user@example.com/",
            "https://example.com@127.0.0.1/",
            "https://127.0.0.1@example.com/",
            "https://:password@example.com/",
        ],
    )
    def test_rejected(self, url: str) -> None:
        """Rejected, never stripped.

        `https://example.com@127.0.0.1/` is the case that matters: a human reading it sees
        example.com, but the host is 127.0.0.1. Anything that silently strips the userinfo has
        already accepted a URL designed to mislead.
        """
        assert reason_for(url) is RejectionReason.EMBEDDED_CREDENTIALS


class TestHostNormalization:
    def test_case_is_normalized(self) -> None:
        assert normalize_url("https://EXAMPLE.COM/").host == "example.com"

    def test_trailing_root_dot_is_removed(self) -> None:
        """`example.com.` and `example.com` are the same host and must match one policy entry."""
        assert normalize_url("https://example.com./").host == "example.com"
        assert normalize_url("https://example.com../").host == "example.com"

    def test_unicode_host_becomes_punycode(self) -> None:
        """Policy comparison must happen in one encoding, or an IDN escapes the allowlist."""
        assert normalize_url("https://bücher.example/").host.startswith("xn--")

    def test_punycode_host_is_preserved(self) -> None:
        assert normalize_url("https://xn--bcher-kva.example/").host == "xn--bcher-kva.example"

    @pytest.mark.parametrize(
        "host",
        ["xn--.example", "xn--a.example", "xn--0.example", "xn--pokxncvbx.example"],
    )
    def test_undecodable_punycode_rejected(self, host: str) -> None:
        """A label claiming to be punycode must actually decode.

        Otherwise a malformed name is dressed up as a valid one, and two parsers may disagree
        about what host it names — which is the bypass this whole module guards against.
        """
        assert reason_for(f"https://{host}/") is RejectionReason.MALFORMED_HOST

    def test_a_single_label_punycode_host_is_still_rejected(self) -> None:
        """`xn--` alone fails the fully-qualified rule first; either rejection is acceptable."""
        assert reason_for("https://xn--/") is RejectionReason.SINGLE_LABEL_HOST

    @pytest.mark.parametrize("host", ["localhost", "server", "intranet"])
    def test_single_label_hosts_rejected(self, host: str) -> None:
        """A name with no dot resolves only via local search domains."""
        assert reason_for(f"https://{host}/") is RejectionReason.SINGLE_LABEL_HOST

    @pytest.mark.parametrize(
        "host",
        ["printer.local", "db.internal", "host.localdomain", "api.corp", "wiki.intranet"],
    )
    def test_private_network_suffixes_rejected(self, host: str) -> None:
        assert reason_for(f"https://{host}/") is RejectionReason.FORBIDDEN_HOST_SUFFIX

    @pytest.mark.parametrize(
        "url",
        [
            "https://exa mple.com/",
            "https://example..com/",
            "https://-example.com/",
            "https://example-.com/",
            "https://ex_ample.com/",
            "https://.example.com/",
        ],
    )
    def test_malformed_hosts_rejected(self, url: str) -> None:
        """Underscores are invalid in hostnames and a known parser-disagreement vector."""
        assert reason_for(url) in {
            RejectionReason.MALFORMED_HOST,
            RejectionReason.MALFORMED_URL,
            RejectionReason.MISSING_HOST,
        }

    def test_overlong_hostname_rejected(self) -> None:
        host = ".".join(["a" * 60] * 5)
        assert reason_for(f"https://{host}/") is RejectionReason.MALFORMED_HOST


class TestIpLiterals:
    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/",
            "https://10.0.0.1/",
            "https://[::1]/",
            "https://[::ffff:127.0.0.1]/",
            "https://93.184.216.34/",
        ],
    )
    def test_recognised_as_literals(self, url: str) -> None:
        """Recognised here so the guard knows no DNS resolution is needed, and can refuse them."""
        normalized = normalize_url(url)
        assert normalized.is_ip_literal
        assert normalized.ip_literal is not None

    def test_ipv6_literal_is_unbracketed_in_the_host_field(self) -> None:
        assert normalize_url("https://[::1]/").host == "::1"

    def test_ipv6_literal_is_rebracketed_in_the_authority(self) -> None:
        assert normalize_url("https://[::1]/").netloc == "::1".join("[]")

    def test_malformed_ipv6_literal_rejected(self) -> None:
        assert reason_for("https://[::1zz]/") in {
            RejectionReason.MALFORMED_HOST,
            RejectionReason.MALFORMED_URL,
        }

    def test_a_hostname_is_not_mistaken_for_a_literal(self) -> None:
        assert normalize_url("https://example.com/").ip_literal is None


class TestPorts:
    def test_default_port_is_applied(self) -> None:
        assert normalize_url("https://example.com/").port == 443
        assert normalize_url("http://example.com/").port == 80

    def test_explicit_default_port_is_normalized_away_from_the_authority(self) -> None:
        """`https://example.com:443/` and `https://example.com/` must be one canonical URL."""
        assert normalize_url("https://example.com:443/").netloc == "example.com"
        assert normalize_url("http://example.com:80/").netloc == "example.com"

    @pytest.mark.parametrize("port", [22, 25, 3306, 5432, 6379, 8080, 9000, 11211])
    def test_other_ports_rejected(self, port: int) -> None:
        """Fail closed: an arbitrary port on an allowlisted host is still an unintended service."""
        assert reason_for(f"https://example.com:{port}/") is RejectionReason.DISALLOWED_PORT
        assert port not in ALLOWED_PORTS

    @pytest.mark.parametrize("url", ["https://example.com:0/", "https://example.com:99999/"])
    def test_out_of_range_ports_rejected(self, url: str) -> None:
        assert reason_for(url) in {
            RejectionReason.DISALLOWED_PORT,
            RejectionReason.MALFORMED_URL,
        }


class TestPathHandling:
    def test_path_is_preserved_verbatim(self) -> None:
        """Rewriting a path could change which document a portal serves, so it is left alone."""
        normalized = normalize_url("https://example.com/a/%2e%2e/b?x=1&y=2")
        assert normalized.path == "/a/%2e%2e/b"
        assert normalized.query == "x=1&y=2"

    def test_empty_path_becomes_root(self) -> None:
        assert normalize_url("https://example.com").to_url() == "https://example.com/"

    def test_fragment_is_dropped(self) -> None:
        """A fragment is never sent to a server, so it is not part of the canonical request."""
        assert "#" not in normalize_url("https://example.com/a#section").to_url()

    def test_unusual_paths_do_not_affect_the_authority(self) -> None:
        """The whole point: a strange path must not change which host is validated."""
        for path in ("/%2e%2e/", "/..;/", "//evil.com/", "/@evil.com/", "/\\evil.com"):
            assert normalize_url(f"https://example.com{path}").host == "example.com"


class TestMalformedInput:
    @pytest.mark.parametrize("url", ["", "   ", "https://", "https:///path", "://example.com"])
    def test_rejected(self, url: str) -> None:
        assert reason_for(url) in {
            RejectionReason.MALFORMED_URL,
            RejectionReason.MISSING_HOST,
            RejectionReason.DISALLOWED_SCHEME,
        }

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/\nHost: evil.com",
            "https://example.com/\r\nX: y",
            "https://example.com/\x00",
            "https://example.com/\ta",
        ],
    )
    def test_control_characters_rejected(self, url: str) -> None:
        """CRLF in a URL can split a request line or forge a log entry."""
        assert reason_for(url) is RejectionReason.MALFORMED_URL

    def test_overlong_url_rejected(self) -> None:
        assert reason_for("https://example.com/" + "a" * 3000) is RejectionReason.URL_TOO_LONG


class TestCanonicalForm:
    def test_round_trip_is_stable(self) -> None:
        """Normalising twice must not change the result, or policy could differ per pass."""
        once = normalize_url("HTTPS://Example.COM.:443/a?b=1").to_url()
        assert once == "https://example.com/a?b=1"
        assert normalize_url(once).to_url() == once

    def test_normalized_url_is_immutable(self) -> None:
        normalized = normalize_url("https://example.com/")
        with pytest.raises(AttributeError):
            normalized.host = "evil.com"  # type: ignore[misc]
