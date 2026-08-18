"""Discovery: the classification rule, which is the whole of it.

Small on purpose. A strategy is a pure function from a page to links, so the only behaviour worth
pinning is which links become documents, which become pages, and which are ignored — and *why*. An
ignored link carrying no reason would make a crawl that found nothing look the same as a portal
that offered nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aedifex.acquisition.crawl.discovery import (
    FetchedPage,
    HtmlLinkDiscovery,
    LinkKind,
    known_strategies,
    strategy_for,
)
from aedifex.acquisition.registry.models import (
    DataUsePolicy,
    DiscoveryPolicy,
    RetrievalMethod,
    SourceCategory,
    SourceDefinition,
    VerificationStatus,
)
from aedifex.domain.documents import DocumentType
from aedifex.domain.files import FileFormat
from aedifex.errors import SourceRegistryError

PAGE = """
<html><body>
  <a href="/documents/notice.pdf">Tender notice</a>
  <a href="/documents/boq.xlsx">Bill of quantities</a>
  <a href="/documents/bundle.zip">All documents (ZIP)</a>
  <a href="tenders/archive">Older tenders</a>
  <a href="/search?q=cement">Search</a>
  <a href="https://evilcpwd.test/documents/notice.pdf">Lookalike</a>
  <a href="mailto:tenders@cpwd.test">Email us</a>
  <a href="/documents/notice.pdf#page=2">The same notice again</a>
</body></html>
"""


def a_source(**overrides: object) -> SourceDefinition:
    fields: dict[str, object] = {
        "id": "cpwd",
        "name": "Example",
        "country": "IN",
        "category": SourceCategory.GOVERNMENT_PROCUREMENT,
        "retrieval": RetrievalMethod.HTTP_CRAWL,
        "base_url": "https://cpwd.test/",
        "enabled": True,
        "verification_status": VerificationStatus.APPROVED,
        "crawler": "html_links",
        "discovery": DiscoveryPolicy(seed_paths=("/tenders",), max_depth=2),
        "data_use": DataUsePolicy(
            license="Open",
            allowed_use="Redistribution permitted with attribution.",
            reviewed_by="a human",
            reviewed_on=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        "document_types": (DocumentType.TENDER_NOTICE,),
        # Note what is absent: zip. Rule 52 forbids archive expansion until bounded extraction
        # exists, and the registry is where that is expressed.
        "file_formats": (FileFormat.PDF, FileFormat.XLSX),
    }
    fields.update(overrides)
    return SourceDefinition(**fields)  # type: ignore[arg-type]


def classify(page_url: str = "https://cpwd.test/tenders", **overrides: object) -> dict[str, str]:
    """Return ``{url: kind}`` for the sample page, so one assertion covers the whole rule."""
    strategy = HtmlLinkDiscovery.from_source(a_source(**overrides))
    links = strategy.links(FetchedPage(url=page_url, body=PAGE))
    return {link.url: link.kind.value for link in links}


class TestClassification:
    def test_a_page_is_split_into_documents_pages_and_ignored_links(self) -> None:
        assert classify() == {
            "https://cpwd.test/documents/notice.pdf": "document",
            "https://cpwd.test/documents/boq.xlsx": "document",
            # Seen, named, and not opened: the source's registry entry omits zip.
            "https://cpwd.test/documents/bundle.zip": "ignored",
            "https://cpwd.test/tenders/archive": "page",
            "https://cpwd.test/search?q=cement": "page",
            # A lookalike host: a plain suffix match would have followed it.
            "https://evilcpwd.test/documents/notice.pdf": "ignored",
            "mailto:tenders@cpwd.test": "ignored",
        }

    def test_the_same_document_linked_twice_is_returned_once(self) -> None:
        """A listing page routinely links one document from a title and a thumbnail."""
        found = classify()
        assert "https://cpwd.test/documents/notice.pdf#page=2" not in found

    def test_an_ignored_link_always_says_why(self) -> None:
        strategy = HtmlLinkDiscovery.from_source(a_source())
        ignored = [
            link
            for link in strategy.links(FetchedPage(url="https://cpwd.test/tenders", body=PAGE))
            if link.kind is LinkKind.IGNORED
        ]
        assert len(ignored) == 3
        assert all(link.reason for link in ignored)
        assert any("zip is not a format" in (link.reason or "") for link in ignored)

    def test_an_archive_becomes_a_document_once_the_registry_permits_it(self) -> None:
        """The exclusion is configuration, not a hard-coded rule — so it can be lifted by review."""
        permitted = classify(file_formats=(FileFormat.PDF, FileFormat.XLSX, FileFormat.ZIP))
        assert permitted["https://cpwd.test/documents/bundle.zip"] == "document"

    def test_relative_links_resolve_against_the_url_that_answered(self) -> None:
        """Not the URL requested. After a redirect those differ, and the wrong one invents paths.

        Note ``/tenders/tenders/archive``: a relative link resolves against the *directory* of
        ``index.html``, per RFC 3986. That looks wrong and is right — it is what a browser does with
        the same page, so it is what the portal's authors were writing against.
        """
        found = classify(page_url="https://docs.cpwd.test/tenders/index.html")
        # The subdomain is permitted, so the page's own host carries through.
        assert found["https://docs.cpwd.test/documents/notice.pdf"] == "document"
        assert found["https://docs.cpwd.test/tenders/tenders/archive"] == "page"

    def test_depth_stops_a_crawl_walking_forever(self) -> None:
        strategy = HtmlLinkDiscovery.from_source(a_source(discovery=DiscoveryPolicy(max_depth=1)))
        links = strategy.links(FetchedPage(url="https://cpwd.test/tenders", body=PAGE, depth=1))
        pages = [link for link in links if link.kind is LinkKind.PAGE]
        assert pages == []
        assert any("max_depth" in (link.reason or "") for link in links)
        # Documents are still taken at the boundary: the limit bounds walking, not collecting.
        assert any(link.kind is LinkKind.DOCUMENT for link in links)

    def test_a_denied_path_is_excluded_even_when_it_names_a_document(self) -> None:
        strategy = HtmlLinkDiscovery.from_source(
            a_source(discovery=DiscoveryPolicy(deny_patterns=(r"^/documents/b",)))
        )
        links = {
            link.url: link.kind for link in strategy.links(FetchedPage("https://cpwd.test/t", PAGE))
        }
        assert links["https://cpwd.test/documents/boq.xlsx"] is LinkKind.IGNORED
        assert links["https://cpwd.test/documents/notice.pdf"] is LinkKind.DOCUMENT

    def test_malformed_markup_still_yields_the_links_it_had(self) -> None:
        """Portals serve broken HTML. Half a page's links beat an exception."""
        strategy = HtmlLinkDiscovery.from_source(a_source())
        body = '<html><body><a href="/a.pdf">a</a><a href=/b.pdf ><div><p>unclosed'
        found = {link.url for link in strategy.links(FetchedPage("https://cpwd.test/t", body))}
        assert "https://cpwd.test/a.pdf" in found


class TestSeeds:
    def test_seeds_come_from_the_registry(self) -> None:
        source = a_source(discovery=DiscoveryPolicy(seed_paths=("/tenders", "/circulars")))
        assert HtmlLinkDiscovery.from_source(source).seeds(source) == (
            "https://cpwd.test/tenders",
            "https://cpwd.test/circulars",
        )


class TestTheStrategyRegistry:
    def test_a_source_gets_the_strategy_it_names(self) -> None:
        assert isinstance(strategy_for(a_source()), HtmlLinkDiscovery)

    def test_an_unregistered_strategy_fails_loudly(self) -> None:
        """The alternative is a crawl that starts, finds nothing, and reports success."""
        with pytest.raises(SourceRegistryError, match="not registered"):
            strategy_for(a_source(crawler="portal_of_the_future"))

    def test_the_registry_loader_validates_against_what_exists(self) -> None:
        assert "html_links" in known_strategies()
