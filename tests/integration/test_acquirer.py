"""Acquirer tests: one URL in, a consistent frontier and corpus out.

What is under test is the *composition* — the order of the five steps, which failures return and
which raise, and the state the frontier row is left in on each path. So almost every assertion here
is about a database row after the fact rather than about a return value.

Real infrastructure, because the thing being checked is that the pieces agree with each other. The
one exception is a store that refuses an upload: a real bucket cannot be asked to fail at a chosen
moment, so that case uses a stand-in satisfying :class:`ObjectStore`.

Fixtures live in ``conftest.py`` alongside the pipeline test's, since both need the same PostgreSQL,
MinIO, and local portal.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from aedifex.acquisition.download import DownloadedFile, DownloadPolicy
from aedifex.acquisition.fetch.controller import FetchCancelledError
from aedifex.acquisition.fetch.redirect_controller import RedirectController
from aedifex.acquisition.fetch.timing import TimeoutPolicy
from aedifex.acquisition.pipeline import (
    Acquirer,
    AcquisitionPolicy,
    ObjectStore,
)
from aedifex.domain.documents import DocumentState
from aedifex.domain.files import FileFormat
from aedifex.errors import InvalidStateTransitionError
from aedifex.infrastructure.database.models import DiscoveredUrl, Document, DocumentRetrieval
from aedifex.infrastructure.storage.objects import (
    RawObjectStore,
    StorageError,
    StoredObject,
)
from tests.integration.support import (
    HOST_POLICY,
    LIMITS,
    PDF,
    SOURCE,
    Portal,
    permit_the_local_portal,
)

pytestmark = pytest.mark.integration

POLICY = AcquisitionPolicy(
    host_policy=HOST_POLICY,
    limits=LIMITS,
    download=DownloadPolicy(allowed_formats=frozenset({FileFormat.PDF})),
    timeouts=TimeoutPolicy(connect_seconds=2.0, read_seconds=5.0, total_seconds=30.0),
)


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def acquirer(redirects: RedirectController, store: RawObjectStore, tmp_path: Path) -> Acquirer:
    return Acquirer(redirects=redirects, store=store, staging=tmp_path / "staging")


def frontier_of(session: Session, url: str) -> DiscoveredUrl:
    return (
        session.query(DiscoveredUrl)
        .filter_by(source_id=SOURCE, url_sha256=hashlib.sha256(url.encode()).hexdigest())
        .one()
    )


class TestASuccessfulAcquisition:
    def test_the_url_becomes_a_document_and_the_frontier_says_so(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        acquirer: Acquirer,
        session: Session,
    ) -> None:
        permit_the_local_portal(monkeypatch, portal.port)
        url = portal.url("/tenders/notice")

        result = acquirer.acquire(session, url=url, policy=POLICY)
        session.commit()

        assert result.succeeded is True
        assert result.state is DocumentState.DOWNLOADED
        assert result.stored is not None
        assert result.recorded is not None
        assert result.document_id == result.recorded.document.id

        row = frontier_of(session, url)
        assert row.state is DocumentState.DOWNLOADED
        assert row.document_id == result.document_id
        assert row.downloaded_at is not None
        assert row.last_attempted_at is not None
        assert row.http_status == 200
        assert row.error_type is None
        assert row.error_message is None

        assert session.query(Document).count() == 1
        assert session.query(DocumentRetrieval).count() == 1

    def test_the_staged_file_is_not_left_behind(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        acquirer: Acquirer,
        session: Session,
        tmp_path: Path,
    ) -> None:
        """The bytes are durably in the store, so a local copy is only a disk filling up."""
        permit_the_local_portal(monkeypatch, portal.port)
        result = acquirer.acquire(session, url=portal.url("/tenders/notice"), policy=POLICY)
        session.commit()

        assert result.succeeded
        staging = tmp_path / "staging"
        assert list(staging.iterdir()) == []

    def test_the_description_names_the_object_and_no_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        acquirer: Acquirer,
        session: Session,
    ) -> None:
        permit_the_local_portal(monkeypatch, portal.port)
        result = acquirer.acquire(session, url=portal.url("/tenders/notice"), policy=POLICY)
        session.commit()

        described = result.describe()
        assert described.startswith(portal.url("/tenders/notice"))
        assert "s3://" in described
        assert "schedule of rates" not in described


class TestReacquisition:
    def test_acquiring_the_same_url_twice_reuses_the_row_and_the_object(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        acquirer: Acquirer,
        session: Session,
    ) -> None:
        """A re-crawl skips what it already has, and does not touch the network to find out.

        Not merely an optimisation. The state machine has no DOWNLOADED → DOWNLOADING edge and is
        right not to: a *changed* document has a different digest and is therefore a different
        document rather than a new version of this one, so re-fetching is a different operation from
        acquiring, and needs a design rather than a flag (FR-072).
        """
        permit_the_local_portal(monkeypatch, portal.port)
        url = portal.url("/tenders/notice")

        first = acquirer.acquire(session, url=url, policy=POLICY)
        session.commit()
        requests_after_first = list(portal.paths)
        second = acquirer.acquire(session, url=url, policy=POLICY)
        session.commit()

        assert first.succeeded and second.succeeded
        assert first.already_acquired is False
        assert second.already_acquired is True
        assert first.frontier.id == second.frontier.id
        assert portal.paths == requests_after_first, "the portal was contacted for a known document"

        assert session.query(DiscoveredUrl).count() == 1
        assert session.query(Document).count() == 1
        assert session.query(DocumentRetrieval).count() == 1


class TestOrdinaryFailures:
    def test_a_missing_document_fails_and_is_retryable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        acquirer: Acquirer,
        session: Session,
    ) -> None:
        """404 is a failure of this URL, not of the run, so it is recorded and returned."""
        permit_the_local_portal(monkeypatch, portal.port)
        url = portal.url("/tenders/gone")

        result = acquirer.acquire(session, url=url, policy=POLICY)
        session.commit()

        assert result.succeeded is False
        assert result.state is DocumentState.FAILED
        assert result.error_type == "http_status"
        assert result.recorded is None
        assert result.stored is None

        row = frontier_of(session, url)
        assert row.state is DocumentState.FAILED
        assert row.http_status == 404
        assert row.attempts == 1
        assert row.document_id is None
        assert session.query(Document).count() == 0

    def test_a_failed_url_can_be_attempted_again(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        acquirer: Acquirer,
        session: Session,
    ) -> None:
        """FAILED re-enters the pipeline, which is why it is a legal state to leave a row in."""
        permit_the_local_portal(monkeypatch, portal.port)
        url = portal.url("/tenders/gone")

        acquirer.acquire(session, url=url, policy=POLICY)
        second = acquirer.acquire(session, url=url, policy=POLICY)
        session.commit()

        assert second.state is DocumentState.FAILED
        assert second.frontier.attempts == 2, "the attempt counter did not advance"
        assert session.query(DiscoveredUrl).count() == 1

    def test_an_off_allowlist_url_fails_without_touching_the_network(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        acquirer: Acquirer,
        session: Session,
    ) -> None:
        """The guard refuses it, and the refusal is recorded rather than raised at the caller."""
        permit_the_local_portal(monkeypatch, portal.port)
        url = f"http://elsewhere.test:{portal.port}/tenders/notice"

        result = acquirer.acquire(session, url=url, policy=POLICY)
        session.commit()

        assert result.state is DocumentState.FAILED
        # The classification, not the Python type: RedirectRejectedError covers both an SSRF
        # refusal and a hop-cap breach, and the difference is the part worth querying.
        assert result.error_type == "ssrf_rejected"
        assert "not permitted for source" in (result.error_message or "")
        assert portal.paths == [], "the portal was contacted for an unpermitted host"

    def test_a_store_that_refuses_the_upload_fails_the_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        redirects: RedirectController,
        session: Session,
        tmp_path: Path,
    ) -> None:
        """A storage failure is this URL's problem, not the run's.

        Uses a stand-in store, because a real bucket cannot be asked to reject an upload on cue —
        and the branch being tested is what happens *after* a successful download.
        """

        class RefusingStore:
            def put(self, downloaded: DownloadedFile) -> StoredObject:
                raise StorageError(f"the bucket is on fire ({downloaded.sha256[:8]})")

        assert isinstance(RefusingStore(), ObjectStore)
        acquirer = Acquirer(
            redirects=redirects, store=RefusingStore(), staging=tmp_path / "staging"
        )
        permit_the_local_portal(monkeypatch, portal.port)
        url = portal.url("/tenders/notice")

        result = acquirer.acquire(session, url=url, policy=POLICY)
        session.commit()

        assert result.state is DocumentState.FAILED
        assert result.error_type == "StorageError"
        assert session.query(Document).count() == 0, "a document row was written with no object"
        # And the staged file is gone even though the upload failed: nobody will come back for it.
        assert list((tmp_path / "staging").iterdir()) == []


class TestCancellation:
    def test_a_shutdown_signal_leaves_the_url_untried(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        redirects: RedirectController,
        store: RawObjectStore,
        session: Session,
        tmp_path: Path,
    ) -> None:
        """A worker being asked to stop is not a failure of the URL.

        So the row goes back to DISCOVERED rather than FAILED: recording a clean shutdown as a
        failure would make it look like a portal outage, and would burn a retry the URL never had.

        The URL is the one that 503s with no ``Retry-After``, because cancellation is observed at a
        backoff and a server asking for zero seconds produces no wait to interrupt. Worth knowing
        rather than working around: a shutdown during a zero-delay retry costs one more request.
        """
        stopping = threading.Event()
        stopping.set()
        acquirer = Acquirer(
            redirects=redirects,
            store=store,
            staging=tmp_path / "staging",
            cancellation=stopping,
        )
        permit_the_local_portal(monkeypatch, portal.port)
        url = portal.url("/tenders/flaky")

        with pytest.raises(FetchCancelledError):
            acquirer.acquire(session, url=url, policy=POLICY)
        session.commit()

        row = frontier_of(session, url)
        assert row.state is DocumentState.DISCOVERED
        assert row.attempts == 0, "a cancelled attempt was counted against the URL"
        assert row.error_type is None
        assert session.query(Document).count() == 0


class TestQuarantine:
    def test_a_login_page_served_as_a_document_is_quarantined_not_failed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        acquirer: Acquirer,
        session: Session,
    ) -> None:
        """The distinction the state machine exists to make.

        The portal will serve the same login page next time, so a retry is pointless — and content
        that failed a safety check is what someone should look at rather than have retried into the
        corpus. QUARANTINED is terminal; FAILED would not be.
        """
        permit_the_local_portal(monkeypatch, portal.port)
        url = portal.url("/tenders/login-page")

        result = acquirer.acquire(session, url=url, policy=POLICY)
        session.commit()

        assert result.state is DocumentState.QUARANTINED
        assert result.error_type == "UnsafeContentError"
        assert "carries no pdf signature" in (result.error_message or "")
        assert session.query(Document).count() == 0

        row = frontier_of(session, url)
        assert row.state is DocumentState.QUARANTINED

    def test_a_quarantined_url_is_not_retried(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        acquirer: Acquirer,
        session: Session,
    ) -> None:
        """Terminal means terminal: a second attempt is a bug, and it fails loudly.

        Deliberately not a silent no-op. A caller looping over the frontier should be selecting rows
        that can be worked on, and one that hands a quarantined URL back to the acquirer has lost
        track of what it is doing.
        """
        permit_the_local_portal(monkeypatch, portal.port)
        url = portal.url("/tenders/login-page")

        acquirer.acquire(session, url=url, policy=POLICY)
        session.commit()

        with pytest.raises(InvalidStateTransitionError, match="quarantined"):
            acquirer.acquire(session, url=url, policy=POLICY)


class TestOversizedContent:
    def test_a_document_over_the_ceiling_is_quarantined(
        self,
        monkeypatch: pytest.MonkeyPatch,
        portal: Portal,
        redirects: RedirectController,
        store: RawObjectStore,
        session: Session,
        tmp_path: Path,
    ) -> None:
        """Size is a safety limit, so tripping it lands in the same terminal state as a bad type."""
        acquirer = Acquirer(redirects=redirects, store=store, staging=tmp_path / "staging")
        permit_the_local_portal(monkeypatch, portal.port)
        tiny = AcquisitionPolicy(
            host_policy=HOST_POLICY,
            limits=LIMITS,
            download=DownloadPolicy(
                allowed_formats=frozenset({FileFormat.PDF}), max_bytes=len(PDF) // 2
            ),
            timeouts=TimeoutPolicy(connect_seconds=2.0, read_seconds=5.0, total_seconds=30.0),
        )

        result = acquirer.acquire(session, url=portal.url("/tenders/notice"), policy=tiny)
        session.commit()

        assert result.state is DocumentState.QUARANTINED
        assert "exceeds" in (result.error_message or "")
        assert list((tmp_path / "staging").iterdir()) == [], "a partial download survived"
