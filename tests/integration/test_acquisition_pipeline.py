"""The whole acquisition pipeline, end to end, against real infrastructure.

.. code-block:: text

    a URL on a local server
        ↓  validate_url          SSRF guard, per hop
        ↓  RedirectController    a redirect followed, re-validated
        ↓  RetryController       a 503 retried, one budget
        ↓  HttpxTransport        a real socket
        ↓  download              streamed to disk, hashed on the way past
        ↓  RawObjectStore        MinIO, checksum verified by the server
        ↓  record_retrieval      PostgreSQL: document row and retrieval row
    read the object back out and hash it again

This is the milestone the acquisition slice exists to reach, so the final assertion is deliberately
crude: the digest of the bytes read back out of object storage equals the digest of the bytes the
server was given to send. Everything in between is real — no fake transport, no fake store, no
in-memory database.

Requires PostgreSQL and MinIO, and skips otherwise so ``make test`` stays runnable with nothing
installed. ``REQUIRE_INTEGRATION_TESTS=1`` turns a skip into a failure, which CI sets.
"""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import boto3
import pytest
from alembic import command
from alembic.config import Config
from botocore.config import Config as BotoConfig
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from aedifex.acquisition.download import DownloadPolicy, download
from aedifex.acquisition.fetch import guard as guard_module
from aedifex.acquisition.fetch import urls as urls_module
from aedifex.acquisition.fetch.addresses import IpAddress, classify_address
from aedifex.acquisition.fetch.controller import RetryController
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.httpx_transport import HttpxTransport
from aedifex.acquisition.fetch.ratelimit import RateLimiter, RateLimits
from aedifex.acquisition.fetch.redirect_controller import RedirectController
from aedifex.acquisition.fetch.resolver import ResolvedAddress
from aedifex.acquisition.fetch.retry import AttemptOutcome, BackoffPolicy, RetryPolicy
from aedifex.acquisition.fetch.timing import MonotonicClock, TimeoutBudget, TimeoutPolicy
from aedifex.acquisition.provenance import ProvenanceConflictError, record_retrieval
from aedifex.config import Environment, Settings
from aedifex.domain.documents import DocumentState
from aedifex.domain.files import FileFormat
from aedifex.infrastructure.database.models import Document, DocumentRetrieval
from aedifex.infrastructure.database.session import build_engine
from aedifex.infrastructure.storage.objects import RawObjectStore, Verification

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOSTNAME = "cpwd.test"
SOURCE = "cpwd"
USER_AGENT = "AedifexBot/0.1 (+mailto:ops@example.org)"
PDF = b"%PDF-1.7\n" + b"schedule of rates 2026 " * 400 + b"\n%%EOF\n"

HOST_POLICY = SourceHostPolicy(
    source_id=SOURCE, base_hosts=frozenset({HOSTNAME}), exact_hosts=frozenset()
)
LIMITS = RateLimits(requests_per_minute=600, max_concurrency=4, min_delay_seconds=0.0)


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# A small local portal
# ---------------------------------------------------------------------------


class _Portal(ThreadingHTTPServer):
    """Answers a redirect, then a 503, then the document — a plausible bad afternoon."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.paths: list[str] = []
        self.served_document = 0


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        portal: _Portal = self.server  # type: ignore[assignment]
        portal.paths.append(self.path)
        if self.path == "/tenders/notice":
            self.send_response(302)
            self.send_header("Location", "/documents/notice.pdf")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path != "/documents/notice.pdf":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        portal.served_document += 1
        if portal.served_document == 1:
            # One transient failure, so the retry path is part of the end-to-end claim.
            self.send_response(503)
            self.send_header("Retry-After", "0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(PDF)))
        self.send_header("Content-Disposition", 'attachment; filename="Tender Notice 2026.pdf"')
        self.end_headers()
        self.wfile.write(PDF)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence the default stderr logging."""


class _LoopbackResolver:
    """Points the test hostname at the local portal, recording lookups."""

    def __init__(self) -> None:
        self.lookups: list[str] = []

    def resolve(self, hostname: str, port: int) -> tuple[ResolvedAddress, ...]:
        self.lookups.append(hostname)
        if hostname != HOSTNAME:
            raise OSError(f"no scripted DNS entry for {hostname!r}")
        return (ResolvedAddress(ip=ip_address("127.0.0.1"), port=port),)


def permit_the_local_portal(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    """Let the real guard accept our own loopback server, and nothing else.

    Two exemptions, both of them the guard working correctly rather than a weakness being papered
    over: an ephemeral port is not in ``ALLOWED_PORTS``, and ``127.0.0.1`` is loopback. Everything
    else stays live — asserted in ``test_fetch_adversarial.py``, which checks that the metadata
    address, a private address, and an off-allowlist host are all still refused with the same
    exemptions applied.
    """
    monkeypatch.setattr(urls_module, "ALLOWED_PORTS", urls_module.ALLOWED_PORTS | {port})

    def only_our_loopback(address: IpAddress) -> object:
        return None if str(address) == "127.0.0.1" else classify_address(address)

    monkeypatch.setattr(guard_module, "classify_address", only_our_loopback)


# ---------------------------------------------------------------------------
# Infrastructure fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(environment=Environment.TEST)


def _require_or_skip(message: str) -> None:
    """Skip, unless CI has forbidden skipping — a skipped test must not look verified (rule 81e)."""
    if os.environ.get("REQUIRE_INTEGRATION_TESTS") == "1":
        pytest.fail(f"{message}. REQUIRE_INTEGRATION_TESTS=1 forbids skipping.")
    pytest.skip(message)


@pytest.fixture(scope="module")
def engine(settings: Settings) -> Iterator[Engine]:
    """A database at ``head``.

    The fixtures here are deliberately their own rather than shared with ``test_database.py``: that
    module's schema fixture exercises a full downgrade/upgrade cycle, which is its subject and not
    this file's, and coupling the two would make a failure in either read as a failure in both.
    """
    candidate = build_engine(settings)
    try:
        with candidate.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (OperationalError, DBAPIError) as error:
        candidate.dispose()
        _require_or_skip(f"PostgreSQL is not reachable: {type(error).__name__}")
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", str(settings.database_url))
    command.upgrade(config, "head")
    yield candidate
    candidate.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as active:
        yield active
        active.rollback()
        active.execute(
            text("TRUNCATE TABLE document_retrievals, discovered_urls, documents CASCADE")
        )
        active.commit()


@pytest.fixture(scope="module")
def store(settings: Settings) -> Iterator[RawObjectStore]:
    endpoint = settings.storage_endpoint_url or "http://localhost:9000"
    access_key = settings.storage_access_key_id
    secret_key = settings.storage_secret_access_key
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=settings.storage_region,
        aws_access_key_id=access_key.get_secret_value() if access_key else "minioadmin",
        aws_secret_access_key=secret_key.get_secret_value() if secret_key else "minioadmin",
        config=BotoConfig(
            connect_timeout=2,
            read_timeout=10,
            retries={"max_attempts": 1},
            signature_version="s3v4",
        ),
    )
    bucket = f"aedifex-e2e-{uuid.uuid4().hex[:12]}"
    candidate = RawObjectStore(client, bucket=bucket)
    try:
        candidate.ensure_bucket()
    except Exception as error:
        _require_or_skip(f"MinIO is not reachable at {endpoint}: {type(error).__name__}")
    yield candidate
    # Every version has to go before the bucket can, because versioning is on and a plain delete
    # only adds a delete marker. Done here and nowhere else: RawObjectStore deliberately cannot
    # remove raw evidence, and a test's teardown is the only place that ability belongs.
    # The two groups are read separately rather than by iterating over their names: they are
    # distinct keys of a TypedDict, and a loop variable makes both of them `object` to mypy.
    paginator = client.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        targets: list[Any] = [
            {"Key": entry["Key"], "VersionId": entry["VersionId"]}
            for entry in page.get("Versions", [])
        ]
        targets += [
            {"Key": marker["Key"], "VersionId": marker["VersionId"]}
            for marker in page.get("DeleteMarkers", [])
        ]
        if targets:
            client.delete_objects(Bucket=bucket, Delete={"Objects": targets})
    client.delete_bucket(Bucket=bucket)


@pytest.fixture
def portal() -> Iterator[_Portal]:
    server = _Portal()
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.daemon = True
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def redirects() -> Iterator[RedirectController]:
    with HttpxTransport(user_agent=USER_AGENT) as transport:
        yield RedirectController(
            controller=RetryController(
                transport=transport,
                limiter=RateLimiter(global_concurrency=4),
                policy=RetryPolicy(
                    backoff=BackoffPolicy(base_seconds=0.01, max_delay_seconds=0.05, max_attempts=3)
                ),
            ),
            resolver=_LoopbackResolver(),
        )


# ---------------------------------------------------------------------------
# The milestone
# ---------------------------------------------------------------------------


class TestADocumentEndToEnd:
    def test_a_url_becomes_a_stored_document_with_provenance(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: _Portal,
        redirects: RedirectController,
        store: RawObjectStore,
        session: Session,
        tmp_path: Path,
    ) -> None:
        permit_the_local_portal(monkeypatch, portal.server_address[1])
        url = f"http://{HOSTNAME}:{portal.server_address[1]}/tenders/notice"
        budget = TimeoutBudget(
            policy=TimeoutPolicy(connect_seconds=2.0, read_seconds=5.0, total_seconds=30.0),
            clock=MonotonicClock(),
        )

        with redirects.fetch(url, host_policy=HOST_POLICY, limits=LIMITS, budget=budget) as chain:
            downloaded = download(
                chain,
                source_id=SOURCE,
                policy=DownloadPolicy(allowed_formats=frozenset({FileFormat.PDF})),
                directory=tmp_path / "staging",
            )

        stored = store.put(downloaded)
        recorded = record_retrieval(session, downloaded=downloaded, stored=stored)
        session.commit()

        # The portal saw exactly what it should: the redirect, the 503, then the document.
        assert portal.paths == [
            "/tenders/notice",
            "/documents/notice.pdf",
            "/documents/notice.pdf",
        ]

        # The bytes are what was sent, all the way through.
        assert downloaded.sha256 == digest_of(PDF)
        assert downloaded.file_format is FileFormat.PDF
        assert downloaded.filename == "Tender_Notice_2026.pdf"

        # In object storage, verified by the store itself.
        assert stored.already_present is False
        assert stored.verification is Verification.SERVER_CHECKSUM
        assert stored.key == downloaded.storage_key

        # Provenance, complete.
        document = session.get(Document, recorded.document.id)
        assert document is not None
        assert document.sha256 == digest_of(PDF)
        assert document.size_bytes == len(PDF)
        assert document.file_format is FileFormat.PDF
        assert document.media_type == "application/pdf"
        assert document.original_filename == "Tender_Notice_2026.pdf"
        assert document.storage_key == stored.key
        assert document.state is DocumentState.DOWNLOADED

        retrieval = session.query(DocumentRetrieval).one()
        assert retrieval.source_id == SOURCE
        assert retrieval.requested_url == url
        assert retrieval.final_url.endswith("/documents/notice.pdf")
        assert retrieval.final_url != retrieval.requested_url
        assert retrieval.http_status == 200
        assert retrieval.http_version == "HTTP/1.1"
        assert retrieval.storage_bucket == store.bucket
        assert retrieval.storage_verification == Verification.SERVER_CHECKSUM.value
        assert retrieval.declared_content_length == len(PDF)
        assert ["content-type", "application/pdf"] in retrieval.response_headers

        # The attempt history spans hops, not just the last one: the 302 that redirected us, the
        # 503 that failed, and the 200 that answered. Three requests, which is what the portal's own
        # log above records — the two counts are derived independently and agree.
        assert retrieval.attempt_count == 3
        assert [entry["outcome"] for entry in retrieval.attempts] == [
            AttemptOutcome.SUCCESS.value,
            AttemptOutcome.HTTP_STATUS.value,
            AttemptOutcome.SUCCESS.value,
        ]
        assert [entry["status_code"] for entry in retrieval.attempts] == [302, 503, 200]
        assert retrieval.attempt_count == len(portal.paths)

        # And the round trip: read it back out and hash it again.
        retrieved = store.download_to(stored.key, tmp_path / "out" / "notice.pdf")
        assert digest_of(retrieved.read_bytes()) == digest_of(PDF)


# ---------------------------------------------------------------------------
# Provenance rows on their own
# ---------------------------------------------------------------------------


class TestProvenanceRows:
    @staticmethod
    def _fetch_and_store(
        monkeypatch: pytest.MonkeyPatch,
        portal: _Portal,
        redirects: RedirectController,
        store: RawObjectStore,
        tmp_path: Path,
    ) -> tuple[Any, Any]:
        permit_the_local_portal(monkeypatch, portal.server_address[1])
        url = f"http://{HOSTNAME}:{portal.server_address[1]}/documents/notice.pdf"
        budget = TimeoutBudget(
            policy=TimeoutPolicy(connect_seconds=2.0, read_seconds=5.0, total_seconds=30.0),
            clock=MonotonicClock(),
        )
        with redirects.fetch(url, host_policy=HOST_POLICY, limits=LIMITS, budget=budget) as chain:
            downloaded = download(
                chain,
                source_id=SOURCE,
                policy=DownloadPolicy(allowed_formats=frozenset({FileFormat.PDF})),
                directory=tmp_path / "staging",
            )
        return downloaded, store.put(downloaded)

    def test_a_second_retrieval_appends_a_row_and_reuses_the_document(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: _Portal,
        redirects: RedirectController,
        store: RawObjectStore,
        session: Session,
        tmp_path: Path,
    ) -> None:
        """Re-fetching a known document is an event, not a duplicate.

        The document row is found by its content-derived id, so it is reused rather than collided
        with; the retrieval row is appended, because "we fetched this again and got the same bytes"
        is a fact worth keeping.
        """
        downloaded, stored = self._fetch_and_store(monkeypatch, portal, redirects, store, tmp_path)
        first = record_retrieval(session, downloaded=downloaded, stored=stored)
        second = record_retrieval(session, downloaded=downloaded, stored=stored)
        session.commit()

        assert first.document_was_new is True
        assert second.document_was_new is False
        assert first.document.id == second.document.id
        assert session.query(Document).count() == 1
        assert session.query(DocumentRetrieval).count() == 2
        assert "known document" in second.describe()

    def test_mismatched_results_are_refused_rather_than_written(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: _Portal,
        redirects: RedirectController,
        store: RawObjectStore,
        session: Session,
        tmp_path: Path,
    ) -> None:
        """Pairing a download with another document's stored object must not write a row.

        It would point provenance at bytes it does not describe, which is worse than losing the
        record entirely — a wrong citation is harder to detect than a missing one.
        """
        from dataclasses import replace

        downloaded, stored = self._fetch_and_store(monkeypatch, portal, redirects, store, tmp_path)
        wrong = replace(stored, sha256="0" * 64)

        with pytest.raises(ProvenanceConflictError, match="not the same document"):
            record_retrieval(session, downloaded=downloaded, stored=wrong)

        assert session.query(DocumentRetrieval).count() == 0
