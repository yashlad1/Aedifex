"""Discovery for the National Highways Authority of India.

The first source-specific adapter in the project, and it exists because NHAI leaves no
alternative: ``nhai.gov.in`` is an Angular single-page app over Drupal whose HTML shell contains no
content and no links, and which has neither a ``robots.txt`` nor a ``sitemap.xml``. Everything the
site shows comes from a JSON API, and that API takes a form body.

Two endpoints, both reconstructed from the site's own JavaScript bundle and then confirmed against
the live service:

.. code-block:: text

    POST /nhai/api/tenderlist     language, totalrecord, index
      → {_resultflag, total_count, message, list: [{id, title, tender_no, publish_date, …}]}
      no document links at all — the listing is an index, not a manifest

    POST /nhai/api/tenderdetail   language, nid   (nid is the list's `id`)
      → {detail: {title, documents: [{named slots}], other_documents: [{file, path, …}], …}}
      `other_documents[].file` is where the PDFs are

**The URL is the request.** The frontier stores URLs, so an API call has to be expressible as one or
it cannot survive a restart. A listing page is therefore
``…/nhai/api/tenderlist?language=en&totalrecord=10&index=0``, and this strategy turns that query
string into the form body. The wart is admitted: a URL carrying a query string that is really a POST
body. The alternative was a request-spec column on the frontier, which buys nothing except a
migration — the URL already identifies the request uniquely, which is exactly what deduplication and
resumption need.

**Only paths the registry authorises are POSTed.** The endpoint comes from reviewed configuration,
never from a response. A hostile listing can therefore change which *tender* we ask about — an `id`
is data — and cannot change what we send it to.

Two portal-specific traps, both found by reading the live response rather than by guessing:

* Every document appears twice, as ``file`` (HTTPS) and ``path`` (plain HTTP). The HTTP twin is
  ignored. Taking it would mean fetching evidence over a tamperable channel, and the redirect policy
  would refuse the downgrade anyway — so picking the wrong field makes every document unfetchable.
* ``documents`` and ``other_documents`` are different shapes for the same idea: the first is a
  fixed set of named slots ("Notice Inviting Tender", "Tender Document"), usually empty; the second
  is a list of files. Both are read, because a tender that uses only the named slots would otherwise
  look like a tender with no documents.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from aedifex.acquisition.crawl.links import (
    DiscoveredLink,
    FetchedPage,
    LinkKind,
    PageRequest,
)
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.registry.models import DiscoveryPolicy, SourceDefinition
from aedifex.domain.files import FileFormat, format_for_extension
from aedifex.errors import SourceRegistryError

__all__ = ["NhaiTenderDiscovery"]

_FORM_MEDIA_TYPE: Final[str] = "application/x-www-form-urlencoded"

_LIST_PATH: Final[str] = "/nhai/api/tenderlist"
_DETAIL_PATH: Final[str] = "/nhai/api/tenderdetail"

_MAX_LISTING_PAGES: Final[int] = 200
"""A ceiling on pagination independent of what the server reports.

``total_count`` comes from the portal, and a bound derived only from a remote number is not a bound.
At the observed 182 tenders and ten per page this is an order of magnitude of headroom.
"""


class NhaiTenderDiscovery:
    """Turns NHAI's tender API into frontier URLs."""

    name = "nhai_tenders"

    def __init__(
        self,
        *,
        policy: DiscoveryPolicy,
        host_policy: SourceHostPolicy,
        formats: frozenset[FileFormat],
        base_url: str,
    ) -> None:
        self._policy = policy
        self._hosts = host_policy
        self._formats = formats
        self._base = base_url
        self._post_paths = frozenset(policy.api_post_paths)

    @classmethod
    def from_source(cls, source: SourceDefinition) -> NhaiTenderDiscovery:
        if source.base_url is None:
            raise SourceRegistryError(
                f"source {source.id!r} declares no base_url, so its API has no address"
            )
        return cls(
            policy=source.discovery,
            host_policy=SourceHostPolicy.from_source(source),
            formats=frozenset(source.file_formats),
            base_url=str(source.base_url),
        )

    # -- requests ----------------------------------------------------------

    def seeds(self, source: SourceDefinition) -> tuple[str, ...]:
        return tuple(urljoin(self._base, path) for path in source.discovery.seed_paths)

    def request_for(self, url: str) -> PageRequest:
        """A POST for an authorised API path, a plain GET for anything else.

        The query string becomes the form body verbatim. It was built by this strategy, or copied
        from a URL this strategy built, and the path it is sent to must appear in the registry — so
        neither half of the request is taken on a remote server's word.
        """
        parts = urlsplit(url)
        if parts.path not in self._post_paths:
            return PageRequest()
        return PageRequest(
            method="POST",
            body=parts.query.encode("ascii"),
            headers={"Content-Type": _FORM_MEDIA_TYPE},
        )

    # -- responses ---------------------------------------------------------

    def links(self, page: FetchedPage) -> tuple[DiscoveredLink, ...]:
        path = urlsplit(page.url).path
        payload = _parse(page.body)
        if payload is None:
            # A body that is not JSON is not a failure of the crawl: the portal answered something
            # unexpected, and a strategy that raised here would turn one bad page into a dead run.
            return (
                DiscoveredLink(
                    url=page.url,
                    kind=LinkKind.IGNORED,
                    depth=page.depth,
                    found_on=page.url,
                    reason="response was not JSON",
                ),
            )
        if path == _LIST_PATH:
            return tuple(self._from_listing(page, payload))
        if path == _DETAIL_PATH:
            return tuple(self._from_detail(page, payload))
        return ()

    def _from_listing(
        self, page: FetchedPage, payload: Mapping[str, Any]
    ) -> Iterator[DiscoveredLink]:
        """One detail page per tender, plus the next page of the listing."""
        records = payload.get("list")
        if not isinstance(records, list):
            return

        language = _query_value(page.url, "language", "en")
        for record in records:
            if not isinstance(record, dict):
                continue
            identifier = record.get("id")
            if not isinstance(identifier, str) or not identifier.isdigit():
                # The only value from the response that reaches a request. Constrained to digits
                # because it is interpolated into a form body, and a Drupal node id is a number.
                continue
            yield DiscoveredLink(
                url=self._api_url(_DETAIL_PATH, {"language": language, "nid": identifier}),
                kind=LinkKind.PAGE,
                depth=page.depth + 1,
                found_on=page.url,
            )

        next_page = self._next_listing_url(page, payload)
        if next_page is not None:
            # At the *same* depth, not deeper. Nineteen pages of one listing is not nineteen levels
            # of a site, and treating it as such would exhaust max_depth before the second page.
            yield DiscoveredLink(
                url=next_page, kind=LinkKind.PAGE, depth=page.depth, found_on=page.url
            )

    def _next_listing_url(self, page: FetchedPage, payload: Mapping[str, Any]) -> str | None:
        total = payload.get("total_count")
        if not isinstance(total, int):
            return None
        index = int(_query_value(page.url, "index", "0") or 0)
        per_page = int(_query_value(page.url, "totalrecord", "10") or 10)
        if per_page < 1:
            return None
        following = index + per_page
        if following >= total or following >= per_page * _MAX_LISTING_PAGES:
            return None
        return self._api_url(
            _LIST_PATH,
            {
                "language": _query_value(page.url, "language", "en"),
                "totalrecord": str(per_page),
                "index": str(following),
            },
        )

    def _from_detail(
        self, page: FetchedPage, payload: Mapping[str, Any]
    ) -> Iterator[DiscoveredLink]:
        detail = payload.get("detail")
        if not isinstance(detail, dict):
            return

        for candidate, reason in _document_candidates(detail):
            if reason is not None:
                yield DiscoveredLink(
                    url=candidate,
                    kind=LinkKind.IGNORED,
                    depth=page.depth,
                    found_on=page.url,
                    reason=reason,
                )
                continue
            yield self._classify_document(candidate, page)

    def _classify_document(self, url: str, page: FetchedPage) -> DiscoveredLink:
        def ignored(reason: str) -> DiscoveredLink:
            return DiscoveredLink(
                url=url, kind=LinkKind.IGNORED, depth=page.depth, found_on=page.url, reason=reason
            )

        parts = urlsplit(url)
        if parts.scheme != "https":
            # Every document is published twice, and the HTTP twin is the same bytes over a channel
            # somebody else can alter. Evidence fetched that way is weaker evidence.
            return ignored(
                f"scheme {parts.scheme or '(none)'!r}: the HTTPS spelling of this URL is used"
            )
        if not parts.hostname or not self._hosts.permits(parts.hostname):
            return ignored(f"host {parts.hostname or '(none)'} is not permitted for this source")

        file_format = _format_of(parts.path)
        if file_format is None:
            return ignored("the path names no file format")
        if file_format not in self._formats:
            return ignored(f"{file_format.value} is not a format this source may yield")
        return DiscoveredLink(url=url, kind=LinkKind.DOCUMENT, depth=page.depth, found_on=page.url)

    def _api_url(self, path: str, params: Mapping[str, str]) -> str:
        parts = urlsplit(self._base)
        return urlunsplit((parts.scheme, parts.netloc, path, urlencode(params), ""))


def _document_candidates(detail: Mapping[str, Any]) -> Iterator[tuple[str, str | None]]:
    """Every document URL the detail response offers, with a reason when it is being skipped.

    Yields ``(url, None)`` to keep it and ``(url, reason)`` to record and drop it. The HTTP twin in
    ``path`` is dropped here rather than silently omitted, so a run can report that it saw two
    spellings of one document and chose one.
    """
    for entry in _rows(detail.get("other_documents")):
        secure = entry.get("file")
        insecure = entry.get("path")
        if isinstance(secure, str) and secure.strip():
            yield secure.strip(), None
        if isinstance(insecure, str) and insecure.strip() and insecure.strip() != secure:
            yield insecure.strip(), "duplicate of the HTTPS `file` URL over plain HTTP"

    # The named-slot shape: {"Notice Inviting Tender": "https://…", "Tender Document": "", …}
    for entry in _rows(detail.get("documents")):
        for label, value in entry.items():
            if isinstance(value, str) and value.strip().startswith("http"):
                yield value.strip(), (
                    None
                    if value.strip().startswith("https")
                    else (f"{label} is offered over plain HTTP")
                )


def _rows(value: Any) -> Iterator[Mapping[str, Any]]:
    """NHAI wraps single objects in one-element lists. Tolerate both."""
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                yield entry


def _parse(body: str) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _query_value(url: str, name: str, default: str) -> str:
    for key, value in parse_qsl(urlsplit(url).query):
        if key == name:
            return value
    return default


def _format_of(path: str) -> FileFormat | None:
    tail = path.rsplit("/", 1)[-1]
    if "." not in tail:
        return None
    return format_for_extension(tail.rsplit(".", 1)[-1])
