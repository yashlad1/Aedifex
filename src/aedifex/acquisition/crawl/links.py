"""The vocabulary discovery speaks: links, pages, requests, and the strategy protocol.

Separate from :mod:`.discovery` because every strategy needs these types and
:mod:`.discovery` is where strategies are *registered* — so a strategy module importing that
registry to get a dataclass is a circular import. Splitting the nouns from the registry costs one
file and removes the cycle entirely.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from aedifex.acquisition.registry.models import SourceDefinition

__all__ = [
    "DiscoveredLink",
    "DiscoveryStrategy",
    "FetchedPage",
    "LinkKind",
    "PageRequest",
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

    ``url`` is the URL that *answered*, not the one requested, so relative links resolve against
    the right base after a redirect. Getting that backwards invents paths that never existed.
    """

    url: str
    body: str
    depth: int = 0
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class PageRequest:
    """How to ask for one page. A GET with no body unless a strategy says otherwise.

    Exists because an API source is still discovery: NHAI publishes its tender listing only through
    a form-body POST, so "what URL" is not enough to describe the request. The method and body come
    from the strategy, which is the only place that knows the source's shape — and the endpoints
    that may receive a POST come from the source's reviewed registry entry, so a URL read out of a
    remote response cannot become one.
    """

    method: str = "GET"
    body: bytes | None = None
    headers: Mapping[str, str] | None = None


class DiscoveryStrategy(Protocol):
    """What a source must provide, and the only thing it may provide."""

    name: str

    def seeds(self, source: SourceDefinition) -> tuple[str, ...]:
        """Absolute URLs where a crawl of this source begins."""
        ...

    def request_for(self, url: str) -> PageRequest:
        """How to ask for ``url``. Pure: no I/O."""
        ...

    def links(self, page: FetchedPage) -> tuple[DiscoveredLink, ...]:
        """Every URL the page offers, classified. Pure: no I/O."""
        ...
