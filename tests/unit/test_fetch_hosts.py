"""Tests for per-source host policy.

The central case is suffix matching. ``host.endswith("cpwd.gov.in")`` also matches
``evilcpwd.gov.in``, which an attacker can register. Label-aware matching does not, and that
difference is the reason this module exists rather than a one-line check at the call site.
"""

from __future__ import annotations

import pytest

from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.registry.models import (
    DataUsePolicy,
    RetrievalMethod,
    SourceCategory,
    SourceDefinition,
)
from aedifex.domain.documents import DocumentType
from aedifex.domain.files import FileFormat


def make_policy(base: str = "cpwd.gov.in", extra: tuple[str, ...] = ()) -> SourceHostPolicy:
    return SourceHostPolicy(
        source_id="cpwd",
        base_hosts=frozenset({base}),
        exact_hosts=frozenset(extra),
    )


def make_source(**overrides: object) -> SourceDefinition:
    kwargs: dict[str, object] = {
        "id": "cpwd",
        "name": "CPWD",
        "category": SourceCategory.GOVERNMENT_PROCUREMENT,
        "retrieval": RetrievalMethod.HTTP_CRAWL,
        "base_url": "https://cpwd.gov.in/",
        "data_use": DataUsePolicy(
            license="unknown (pending review)",
            allowed_use="Pending review; no collection permitted yet.",
        ),
        "document_types": (DocumentType.TENDER_NOTICE,),
        "file_formats": (FileFormat.PDF,),
    }
    kwargs.update(overrides)
    return SourceDefinition(**kwargs)  # type: ignore[arg-type]


class TestExactAndSubdomainMatching:
    def test_the_base_host_is_permitted(self) -> None:
        assert make_policy().permits("cpwd.gov.in")

    @pytest.mark.parametrize(
        "host",
        ["www.cpwd.gov.in", "documents.cpwd.gov.in", "static.assets.cpwd.gov.in"],
    )
    def test_subdomains_of_the_base_host_are_permitted(self, host: str) -> None:
        """Portals routinely serve documents from a `documents.` or `static.` host."""
        assert make_policy().permits(host)


class TestSuffixConfusion:
    @pytest.mark.parametrize(
        "host",
        [
            "evilcpwd.gov.in",
            "notcpwd.gov.in",
            "xcpwd.gov.in",
            "my-cpwd.gov.in",
        ],
    )
    def test_a_host_merely_ending_in_the_base_is_rejected(self, host: str) -> None:
        """The bug this module exists to prevent.

        `endswith("cpwd.gov.in")` matches all of these; label-aware matching does not. Each is
        registrable by someone other than the operator of cpwd.gov.in.
        """
        assert not make_policy().permits(host)
        # Demonstrates that the naive check really would have accepted them.
        assert host.endswith("cpwd.gov.in")

    @pytest.mark.parametrize(
        "host",
        ["cpwd.gov.in.evil.test", "cpwd.gov.in.attacker.example", "www.cpwd.gov.in.evil.test"],
    )
    def test_a_host_merely_starting_with_the_base_is_rejected(self, host: str) -> None:
        """The mirror-image mistake: a prefix match, or forgetting to anchor the end."""
        assert not make_policy().permits(host)

    @pytest.mark.parametrize("host", ["gov.in", "in", "gov", ""])
    def test_parent_domains_are_rejected(self, host: str) -> None:
        assert not make_policy().permits(host)

    def test_an_unrelated_host_is_rejected(self) -> None:
        assert not make_policy().permits("nhai.gov.in")


class TestNormalizationBeforeMatching:
    @pytest.mark.parametrize(
        "host",
        ["CPWD.GOV.IN", "Cpwd.Gov.In", "cpwd.gov.in.", "  cpwd.gov.in  ", "[cpwd.gov.in]"],
    )
    def test_casing_padding_and_trailing_dot_do_not_defeat_policy(self, host: str) -> None:
        """Policy must not be bypassable by rewriting the same host a different way."""
        assert make_policy().permits(host)

    def test_trailing_dot_on_a_subdomain_is_handled(self) -> None:
        assert make_policy().permits("www.cpwd.gov.in.")


class TestAdditionalHosts:
    def test_an_additional_host_is_permitted(self) -> None:
        """A legitimate CDN is added by configuration, never by loosening network safety."""
        assert make_policy(extra=("cdn.example.net",)).permits("cdn.example.net")

    def test_subdomains_of_an_additional_host_are_not_permitted(self) -> None:
        """Deliberate asymmetry.

        The source's own domain permits subdomains because the operator controls them. A
        third-party host does not: authorising a shared object-storage domain by suffix would
        authorise every other tenant on it.
        """
        policy = make_policy(extra=("cdn.example.net",))
        assert not policy.permits("evil.cdn.example.net")
        assert not policy.permits("other-tenant.cdn.example.net")

    def test_additional_hosts_do_not_widen_the_base_match(self) -> None:
        policy = make_policy(extra=("cdn.example.net",))
        assert not policy.permits("evilcpwd.gov.in")


class TestDerivationFromRegistry:
    def test_the_base_host_comes_from_the_registry_base_url(self) -> None:
        policy = SourceHostPolicy.from_source(make_source())
        assert policy.base_hosts == frozenset({"cpwd.gov.in"})
        assert policy.source_id == "cpwd"
        assert policy.permits("documents.cpwd.gov.in")

    def test_additional_hosts_are_carried_through_as_exact(self) -> None:
        source = make_source(additional_hosts=("cdn.example.net",))
        policy = SourceHostPolicy.from_source(source)
        assert policy.exact_hosts == frozenset({"cdn.example.net"})
        assert policy.permits("cdn.example.net")
        assert not policy.permits("sub.cdn.example.net")

    def test_a_port_in_the_base_url_does_not_leak_into_the_host(self) -> None:
        policy = SourceHostPolicy.from_source(make_source(base_url="https://cpwd.gov.in:443/x"))
        assert policy.base_hosts == frozenset({"cpwd.gov.in"})

    def test_a_source_without_a_base_url_cannot_produce_a_policy(self) -> None:
        """Failing loudly beats returning a policy that silently rejects everything."""
        source = make_source(
            retrieval=RetrievalMethod.MANUAL_UPLOAD,
            base_url=None,
            robots_policy="not_applicable",
        )
        with pytest.raises(ValueError, match="no base_url host"):
            SourceHostPolicy.from_source(source)


class TestDescription:
    def test_describes_both_allowlists_distinctly(self) -> None:
        """Error messages must make the asymmetry visible, or it looks like a bug."""
        described = make_policy(extra=("cdn.example.net",)).describe()
        assert "cpwd.gov.in (+subdomains)" in described
        assert "cdn.example.net (exact)" in described

    def test_an_empty_policy_describes_itself_clearly(self) -> None:
        policy = SourceHostPolicy(source_id="none", base_hosts=frozenset(), exact_hosts=frozenset())
        assert policy.describe() == "<no hosts permitted>"
        assert not policy.permits("anything.test")


class TestRegistryValidation:
    """`additional_hosts` must not become a way to reintroduce suffix matching."""

    @pytest.mark.parametrize(
        "host",
        [
            "*.example.net",
            "CDN.example.net",
            " cdn.example.net",
            "https://cdn.example.net",
            "cdn.example.net:443",
            "example",
            "10.0.0.1",
        ],
    )
    def test_patterns_urls_and_bare_names_are_rejected(self, host: str) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            make_source(additional_hosts=(host,))

    def test_duplicates_are_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="unique"):
            make_source(additional_hosts=("cdn.example.net", "cdn.example.net"))

    def test_a_valid_host_is_accepted(self) -> None:
        source = make_source(additional_hosts=("cdn.example.net", "files.example.org"))
        assert len(source.additional_hosts) == 2
