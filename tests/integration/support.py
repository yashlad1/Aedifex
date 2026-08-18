"""Shared pieces for the integration suite: a local portal, and the guard exemption it needs.

Not a conftest, because these are values and classes rather than fixtures — the fixtures that wrap
them live next door. Keeping them apart means a test can build its own portal without inheriting a
fixture's lifetime.
"""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from aedifex.acquisition.fetch import guard as guard_module
from aedifex.acquisition.fetch import urls as urls_module
from aedifex.acquisition.fetch.addresses import IpAddress, classify_address
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.ratelimit import RateLimits

HOSTNAME = "cpwd.test"
SOURCE = "cpwd"
USER_AGENT = "AedifexBot/0.1 (+mailto:ops@example.org)"
LOOPBACK = "127.0.0.1"

PDF = b"%PDF-1.7\n" + b"schedule of rates 2026 " * 400 + b"\n%%EOF\n"
LOGIN_PAGE = b"<!DOCTYPE html><html><body>Session expired. Please log in.</body></html>"

HOST_POLICY = SourceHostPolicy(
    source_id=SOURCE, base_hosts=frozenset({HOSTNAME}), exact_hosts=frozenset()
)
LIMITS = RateLimits(requests_per_minute=600, max_concurrency=4, min_delay_seconds=0.0)


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class Portal(ThreadingHTTPServer):
    """A small procurement portal that behaves like a real one on a bad afternoon.

    ==========================  =================================================================
    ``/tenders/notice``         302 to the document, which then 503s once before serving it
    ``/documents/notice.pdf``   the document itself
    ``/tenders/login-page``     HTTP 200, ``Content-Type: application/pdf``, an HTML login page
    ``/tenders/gone``           404
    ``/tenders/flaky``          503 every time, and with no ``Retry-After``
    ==========================  =================================================================

    The login page is the case worth having on hand: every declared signal says PDF and only the
    bytes disagree, which is what portals actually do when a session expires.

    ``/tenders/flaky`` omits ``Retry-After`` deliberately, so the retry uses a *computed* backoff.
    A zero-length wait is not a wait, so it is never interrupted by a cancellation token — which
    means a test about shutdown has to be given something to interrupt.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__((LOOPBACK, 0), _Handler)
        self.paths: list[str] = []
        self.served_document = 0

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def url(self, path: str) -> str:
        """A URL naming the test hostname, which the scripted resolver points at loopback."""
        return f"http://{HOSTNAME}:{self.port}{path}"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        portal: Portal = self.server  # type: ignore[assignment]
        portal.paths.append(self.path)

        if self.path == "/tenders/notice":
            self._respond(302, headers=(("Location", "/documents/notice.pdf"),))
            return
        if self.path == "/tenders/login-page":
            self._respond(200, body=LOGIN_PAGE, content_type="application/pdf")
            return
        if self.path == "/tenders/flaky":
            self._respond(503)
            return
        if self.path != "/documents/notice.pdf":
            self._respond(404)
            return

        portal.served_document += 1
        if portal.served_document == 1:
            # One transient failure, so the retry path is part of every end-to-end claim here.
            self._respond(503, headers=(("Retry-After", "0"),))
            return
        self._respond(
            200,
            body=PDF,
            content_type="application/pdf",
            headers=(("Content-Disposition", 'attachment; filename="Tender Notice 2026.pdf"'),),
        )

    def _respond(
        self,
        status: int,
        *,
        body: bytes = b"",
        content_type: str | None = None,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.send_response(status)
        if content_type is not None:
            self.send_header("Content-Type", content_type)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence the default stderr logging; failures are asserted, not read."""


def permit_the_local_portal(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    """Let the real guard accept our own loopback server, and nothing else.

    Two exemptions, and both of them are the guard working correctly rather than a weakness being
    papered over: an ephemeral port is not in ``ALLOWED_PORTS``, and ``127.0.0.1`` is loopback. The
    redirect controller validates internally — deliberately, since an injectable validator is an
    injectable bypass — so a chain cannot be driven over loopback without this.

    Everything else stays live, which is asserted rather than assumed:
    ``test_fetch_adversarial.py`` applies these same two exemptions and then checks that the
    metadata address, a private address, and an off-allowlist host are all still refused.
    """
    monkeypatch.setattr(urls_module, "ALLOWED_PORTS", urls_module.ALLOWED_PORTS | {port})

    def only_our_loopback(address: IpAddress) -> object:
        return None if str(address) == LOOPBACK else classify_address(address)

    monkeypatch.setattr(guard_module, "classify_address", only_our_loopback)
