"""The whole acquisition pipeline, end to end, against real infrastructure.

.. code-block:: text

    a URL on a local portal
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
portal was given to send. Everything in between is real — no fake transport, no fake store, no
in-memory database.

The steps are wired up by hand here rather than through ``Acquirer``, and that is the point: this
asserts the pieces *can* be composed and what the composition produces, while ``test_acquirer.py``
asserts that the composition in production code does it the same way. If those two ever disagree,
one of them is wrong, and it shows up here.

Requires PostgreSQL and MinIO; the fixtures skip otherwise, and fail rather than skip under
``REQUIRE_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from aedifex.acquisition.download import DownloadPolicy, download
from aedifex.acquisition.fetch.redirect_controller import RedirectController
from aedifex.acquisition.fetch.retry import AttemptOutcome
from aedifex.acquisition.fetch.timing import MonotonicClock, TimeoutBudget, TimeoutPolicy
from aedifex.acquisition.provenance import ProvenanceConflictError, record_retrieval
from aedifex.domain.documents import DocumentState
from aedifex.domain.files import FileFormat
from aedifex.infrastructure.database.models import Document, DocumentRetrieval
from aedifex.infrastructure.storage.objects import RawObjectStore, Verification
from tests.integration.support import (
    HOST_POLICY,
    LIMITS,
    PDF,
    SOURCE,
    Portal,
    digest_of,
    permit_the_local_portal,
)

pytestmark = pytest.mark.integration


def budget() -> TimeoutBudget:
    return TimeoutBudget(
        policy=TimeoutPolicy(connect_seconds=2.0, read_seconds=5.0, total_seconds=30.0),
        clock=MonotonicClock(),
    )


# ---------------------------------------------------------------------------
# The milestone
# ---------------------------------------------------------------------------


class TestADocumentEndToEnd:
    def test_a_url_becomes_a_stored_document_with_provenance(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        redirects: RedirectController,
        store: RawObjectStore,
        session: Session,
        tmp_path: Path,
    ) -> None:
        permit_the_local_portal(monkeypatch, portal.port)
        url = portal.url("/tenders/notice")

        with redirects.fetch(url, host_policy=HOST_POLICY, limits=LIMITS, budget=budget()) as chain:
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
        portal: Portal,
        redirects: RedirectController,
        store: RawObjectStore,
        tmp_path: Path,
    ) -> tuple[Any, Any]:
        permit_the_local_portal(monkeypatch, portal.port)
        url = portal.url("/documents/notice.pdf")
        with redirects.fetch(url, host_policy=HOST_POLICY, limits=LIMITS, budget=budget()) as chain:
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
        portal: Portal,
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
        portal: Portal,
        redirects: RedirectController,
        store: RawObjectStore,
        session: Session,
        tmp_path: Path,
    ) -> None:
        """Pairing a download with another document's stored object must not write a row.

        It would point provenance at bytes it does not describe, which is worse than losing the
        record entirely — a wrong citation is harder to detect than a missing one.
        """

        downloaded, stored = self._fetch_and_store(monkeypatch, portal, redirects, store, tmp_path)
        wrong = replace(stored, sha256="0" * 64)

        with pytest.raises(ProvenanceConflictError, match="not the same document"):
            record_retrieval(session, downloaded=downloaded, stored=wrong)

        assert session.query(DocumentRetrieval).count() == 0
