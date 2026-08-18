"""Reading a listing page into memory, so discovery can look at it.

Separate from :mod:`.discovery` because this is the half that touches the network, and keeping the
strategy pure is what makes a source adapter testable against a saved page.

A listing page is *not* a document. It is not stored, not hashed, and not given a place in the
corpus: it is read, mined for links, and discarded. What survives is ``discovered_via`` on each
frontier row, which records the page a URL was found on — enough to answer "why did we fetch this?"
without keeping a copy of every index page a portal serves.

The read is bounded twice, for two different failures. ``max_bytes`` stops a portal that answers a
listing request with a video. The decode is lossy because a page that declares UTF-8 and is really
Windows-1252 is an ordinary Tuesday on a government portal, and a link list is worth having even if
one heading renders as mojibake.
"""

from __future__ import annotations

from typing import Final

from aedifex.acquisition.crawl.links import FetchedPage, PageRequest
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.ratelimit import RateLimits
from aedifex.acquisition.fetch.redirect_controller import RedirectController
from aedifex.acquisition.fetch.timing import MonotonicClock, TimeoutBudget, TimeoutPolicy
from aedifex.acquisition.fetch.transport import RawResponse

__all__ = ["MAX_PAGE_BYTES", "PageReader"]

MAX_PAGE_BYTES: Final[int] = 8 * 1024 * 1024
"""A listing page that needs more than this is not a listing page (rule 51)."""

_READ_CHUNK: Final[int] = 64 * 1024


class PageReader:
    """Fetches a listing page through the frozen fetch stack and hands back its text."""

    def __init__(
        self,
        *,
        redirects: RedirectController,
        host_policy: SourceHostPolicy,
        limits: RateLimits,
        timeouts: TimeoutPolicy | None = None,
        max_bytes: int = MAX_PAGE_BYTES,
    ) -> None:
        self._redirects = redirects
        self._host_policy = host_policy
        self._limits = limits
        self._timeouts = timeouts if timeouts is not None else TimeoutPolicy()
        self._max_bytes = max_bytes

    def read(self, url: str, *, depth: int = 0, request: PageRequest | None = None) -> FetchedPage:
        """Fetch ``url`` and return it as text.

        ``request`` comes from the source's discovery strategy, which is the only thing that knows
        whether this URL is a page to GET or an API call to POST a form to. Defaulting to a plain
        GET keeps every HTML source unaffected.

        Raises whatever the fetch layer raises — ``FetchFailedError``, ``SsrfRejectionError``,
        ``RedirectRejectedError``, ``TransportError``. Deliberately not swallowed: a seed page that
        cannot be read is a crawl that has not started, and the runner decides what that means.
        """
        spec = request if request is not None else PageRequest()
        budget = TimeoutBudget(policy=self._timeouts, clock=MonotonicClock())
        with self._redirects.fetch(
            url,
            host_policy=self._host_policy,
            limits=self._limits,
            budget=budget,
            method=spec.method,
            headers=spec.headers,
            body=spec.body,
            max_response_bytes=self._max_bytes,
        ) as chain:
            return FetchedPage(
                # The URL that *answered*, so relative links resolve against the right base after a
                # redirect. Using the requested URL here produces links to paths that never existed.
                url=chain.final_url,
                body=_read_text(chain.response, limit=self._max_bytes),
                depth=depth,
                media_type=_media_type(chain.response),
            )


def _read_text(response: RawResponse, *, limit: int) -> str:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes(_READ_CHUNK):
        chunks.append(chunk)
        total += len(chunk)
        if total >= limit:
            break
    return b"".join(chunks)[:limit].decode("utf-8", errors="replace")


def _media_type(response: RawResponse) -> str | None:
    declared = response.headers.get("content-type")
    return declared.split(";", 1)[0].strip().lower() if declared else None
