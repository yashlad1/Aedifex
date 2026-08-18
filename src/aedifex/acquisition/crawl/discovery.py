"""Discovery: turning a page into the URLs worth queueing.

This is the *only* part of the pipeline a new source is allowed to change. Everything downstream —
frontier, fetch, download, validation, storage, provenance — is source-independent, and stays that
way because a strategy here is a **pure function from a page to links**. No network, no database, no
object store. A source adapter can therefore be exercised against a saved page, and a portal
redesign cannot break anything except its own strategy.

.. code-block:: text

    seeds(source)          absolute URLs, from the registry's seed_paths
        ↓  fetched by the runner, through the frozen fetch stack
    links(page)            pure: text in, classified links out
        ↓  PAGE      → follow, if depth and patterns allow
        ↓  DOCUMENT  → enqueue for acquisition
        ↓  IGNORED   → recorded with a reason, never silently dropped

A link is a DOCUMENT when its extension names a format the source is permitted to yield. That is a
deliberately dull rule: the alternative is guessing from link text, and a crawler that guesses
downloads the wrong things at a portal that is entitled to block it. A ZIP link at a source whose
registry entry omits ``zip`` is therefore *ignored with a reason* rather than fetched — which is how
rule 52 is satisfied without an archive extractor existing yet.

Nothing here trusts a link. Every URL is resolved against the page it came from, then handed to the
frontier, which canonicalises it and refuses anything the guard would refuse. Discovery is a
suggestion; the guard is the decision.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from typing import Final, Protocol
from urllib.parse import urldefrag, urljoin, urlsplit

from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.registry.models import DiscoveryPolicy, SourceDefinition
from aedifex.domain.files import FileFormat, format_for_extension
from aedifex.errors import SourceRegistryError

__all__ = [
    "STRATEGIES",
    "DiscoveredLink",
    "DiscoveryStrategy",
    "FetchedPage",
    "HtmlLinkDiscovery",
    "LinkKind",
    "is_document_url",
    "known_strategies",
    "strategy_for",
]


class LinkKind(StrEnum):
    DOCUMENT = "document"
    """Something to acquire: the extension names a format this source may yield."""
    PAGE = "page"
    """Something to read for more links."""
    IGNORED = "ignored"
    """Seen and deliberately not queued. Carried rather than dropped, so a run can report it."""


@dataclass(frozen=True, slots=True)
class DiscoveredLink:
    """One URL a page offered, classified, with where it came from."""

    url: str
    kind: LinkKind
    depth: int
    found_on: str
    reason: str | None = None
    """Why it was ignored. ``None`` for links that were queued."""

    @property
    def is_queueable(self) -> bool:
        return self.kind in (LinkKind.DOCUMENT, LinkKind.PAGE)


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """A listing page, already read into memory by the runner.

    ``url`` is the URL that *answered*, not the one requested, so relative links resolve against the
    right base after a redirect. Getting that backwards produces links to paths that never existed.
    """

    url: str
    body: str
    depth: int = 0
    media_type: str | None = None


class DiscoveryStrategy(Protocol):
    """What a source must provide, and the only thing it may provide."""

    name: str

    def seeds(self, source: SourceDefinition) -> tuple[str, ...]:
        """Absolute URLs where a crawl of this source begins."""
        ...

    def links(self, page: FetchedPage) -> tuple[DiscoveredLink, ...]:
        """Every URL the page offers, classified. Pure: no I/O."""
        ...


_MAX_LINKS_PER_PAGE: Final[int] = 5_000
"""A bound on one page's contribution, so a generated page cannot flood the frontier in one step.

Rule 51: every resource needs a limit. A portal with a runaway template can emit a hundred thousand
links, and the cost of that is paid at enqueue time by the database, not by the page.
"""


class HtmlLinkDiscovery:
    """Generic discovery for a server-rendered portal: follow the links, take the documents.

    Configured entirely from the registry, so a well-behaved HTML portal needs **no adapter code** —
    only a reviewed YAML entry. A named strategy is for portals whose structure genuinely demands
    one, not for every new source.

    Links are extracted with the standard library's ``HTMLParser``. Deliberately not lxml or
    BeautifulSoup: this reads untrusted markup from a remote host, and a pure-Python tolerant parser
    has a smaller and duller attack surface than a C extension. It is also enough — ``href`` and
    ``src`` attributes do not need a DOM.
    """

    name = "html_links"

    def __init__(
        self,
        *,
        policy: DiscoveryPolicy,
        host_policy: SourceHostPolicy,
        formats: frozenset[FileFormat],
    ) -> None:
        self._policy = policy
        self._hosts = host_policy
        self._formats = formats
        self._follow = tuple(re.compile(pattern) for pattern in policy.follow_patterns)
        self._deny = tuple(re.compile(pattern) for pattern in policy.deny_patterns)

    @classmethod
    def from_source(cls, source: SourceDefinition) -> HtmlLinkDiscovery:
        return cls(
            policy=source.discovery,
            host_policy=SourceHostPolicy.from_source(source),
            formats=frozenset(source.file_formats),
        )

    def seeds(self, source: SourceDefinition) -> tuple[str, ...]:
        if source.base_url is None:
            raise SourceRegistryError(
                f"source {source.id!r} declares no base_url, so a crawl has nowhere to start"
            )
        base = str(source.base_url)
        return tuple(urljoin(base, path) for path in source.discovery.seed_paths)

    def links(self, page: FetchedPage) -> tuple[DiscoveredLink, ...]:
        found: list[DiscoveredLink] = []
        seen: set[str] = set()

        for raw in _extract_hrefs(page.body)[:_MAX_LINKS_PER_PAGE]:
            resolved, _ = urldefrag(urljoin(page.url, raw))
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(self._classify(resolved, page=page))
        return tuple(found)

    def _classify(self, url: str, *, page: FetchedPage) -> DiscoveredLink:
        def ignored(reason: str) -> DiscoveredLink:
            return DiscoveredLink(
                url=url, kind=LinkKind.IGNORED, depth=page.depth, found_on=page.url, reason=reason
            )

        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return ignored(f"scheme {parts.scheme or '(none)'!r} is not fetched")
        if not parts.hostname or not self._hosts.permits(parts.hostname):
            # Not a security decision — the guard makes that — but a crawl decision: a link off
            # the source's own hosts would collect documents attributed to the wrong portal.
            return ignored(f"host {parts.hostname or '(none)'} is not permitted here")

        path = parts.path or "/"
        if any(pattern.search(path) for pattern in self._deny):
            return ignored("path matches a deny pattern")

        file_format = _format_of(path)
        if file_format is not None:
            if file_format in self._formats:
                return DiscoveredLink(
                    url=url, kind=LinkKind.DOCUMENT, depth=page.depth, found_on=page.url
                )
            # The archive case, among others: seen, named, and not opened.
            return ignored(f"{file_format.value} is not a format this source may yield")

        if page.depth >= self._policy.max_depth:
            return ignored(f"max_depth {self._policy.max_depth} reached")
        if self._follow and not any(pattern.search(path) for pattern in self._follow):
            return ignored("path matches no follow pattern")
        return DiscoveredLink(url=url, kind=LinkKind.PAGE, depth=page.depth + 1, found_on=page.url)


def is_document_url(url: str, formats: frozenset[FileFormat]) -> bool:
    """Whether a queued URL is a document to acquire rather than a page to read for links.

    The frontier stores no kind column, and deliberately: the answer is derivable from the URL and
    the source's permitted formats, so it stays correct across a restart without a migration and
    without a run holding page URLs in memory where an interruption would lose them.
    """
    file_format = _format_of(urlsplit(url).path or "/")
    return file_format is not None and file_format in formats


def _format_of(path: str) -> FileFormat | None:
    """The format a URL path names by its extension, or ``None`` if it names none.

    ``None`` means "probably a page", not "unknown binary". A path with no extension, or one ending
    in ``.aspx`` or ``.php``, is a page as far as a crawler is concerned — whether the *response* is
    really a document is the downloader's question, and it answers it from the bytes.
    """
    tail = path.rsplit("/", 1)[-1]
    if "." not in tail:
        return None
    return format_for_extension(tail.rsplit(".", 1)[-1])


class _LinkCollector(HTMLParser):
    """Collects link-bearing attributes, tolerating whatever markup a portal serves.

    ``convert_charrefs`` is on, so ``&amp;`` in a query string arrives as ``&`` — a link written
    correctly in HTML would otherwise be fetched with a literal ``&amp;`` in it and 404.
    """

    _ATTRIBUTES: Final[Mapping[str, str]] = {"a": "href", "area": "href", "iframe": "src"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        wanted = self._ATTRIBUTES.get(tag.lower())
        if wanted is None:
            return
        for name, value in attrs:
            if name.lower() == wanted and value and value.strip():
                self.hrefs.append(value.strip())

    def error(self, message: str) -> None:  # pragma: no cover - removed in 3.10+, kept for safety
        """Never raise on malformed markup: half a page's links are better than none."""


def _extract_hrefs(body: str) -> list[str]:
    parser = _LinkCollector()
    try:
        parser.feed(body)
        parser.close()
    except (AssertionError, ValueError):
        # HTMLParser is tolerant but not total. Whatever was collected before the failure stands:
        # a truncated or malformed page is a normal thing for a portal to serve, not a crawl error.
        pass
    return parser.hrefs


STRATEGIES: Final[Mapping[str, type[HtmlLinkDiscovery]]] = {
    HtmlLinkDiscovery.name: HtmlLinkDiscovery,
}
"""Every discovery strategy that exists, by the name a registry entry uses in ``crawler``.

This is what ``load_registry(known_crawlers=...)`` has been validating against since the loader was
written, with nothing to pass it until now: an enabled source naming a strategy that does not exist
is a registry error at load time rather than a crash on the first page.
"""


def known_strategies() -> frozenset[str]:
    return frozenset(STRATEGIES)


def strategy_for(source: SourceDefinition) -> DiscoveryStrategy:
    """Build the discovery strategy a source's registry entry names.

    Raises:
        SourceRegistryError: if the source names no strategy or an unknown one. Loud, because the
            alternative is a crawl that starts, finds nothing, and reports success.
    """
    if source.crawler is None:
        raise SourceRegistryError(
            f"source {source.id!r} names no crawler, so nothing knows how to discover its documents"
        )
    implementation = STRATEGIES.get(source.crawler)
    if implementation is None:
        available = ", ".join(sorted(STRATEGIES)) or "<none registered>"
        raise SourceRegistryError(
            f"source {source.id!r} names crawler {source.crawler!r}, which is not registered "
            f"(available: {available})"
        )
    return implementation.from_source(source)
