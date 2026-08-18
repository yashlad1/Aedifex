"""One spelling of a URL, so the frontier can tell two URLs apart.

Shared by the frontier and the acquirer on purpose. They must agree on what makes two URLs the same
URL, and the way that agreement breaks is not a crash: it is a crawl that fetches the same document
twice, or one that skips a URL it has never actually seen. Neither shows up as an error.

The canonical form is the one the SSRF guard already produces — lowercase host, punycode, explicit
scheme, default port omitted, **fragment dropped** — because a second normaliser would be a second
opinion, and the one that decides what we fetch should be the one that decided it was safe to fetch.

What is deliberately *not* normalised: query parameter order, trailing slashes, and case in the
path. All three can change which document a portal serves, and a crawler that assumes otherwise
silently collects the wrong file.
"""

from __future__ import annotations

import hashlib

from aedifex.acquisition.fetch.urls import normalize_url

__all__ = ["canonical_url", "url_digest"]


def canonical_url(raw: str) -> str:
    """Return ``raw`` in canonical form.

    Raises:
        SsrfRejectionError: if the URL cannot be parsed, uses a scheme or port we never speak to, or
            carries credentials. Refused here rather than stored and refused later: a frontier row
            for a URL that can never be fetched is a row that is claimed, attempted, and failed on
            every pass of every run.
    """
    return normalize_url(raw).to_url()


def url_digest(canonical: str) -> str:
    """The frontier's key for a canonical URL.

    Digested rather than indexed directly because procurement portals emit URLs long enough to
    exceed a btree index limit, and a unique constraint that fails on a long URL would fail exactly
    on the portals this project exists to crawl.
    """
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
