"""Integration tests against a real PostgreSQL instance.

Skipped automatically when no database is reachable, so ``make test`` stays runnable with no
infrastructure. CI provides PostgreSQL as a service container and runs these.

These tests are the authoritative check on things a unit test cannot reach: the migration
actually applies and reverses, the check constraints reject bad rows at the database level,
and the deduplication design behaves as intended when two URLs resolve to one document.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from aedifex import __version__
from aedifex.acquisition.content import document_id_for_digest
from aedifex.config import Environment, Settings
from aedifex.domain.documents import DocumentState, DocumentType
from aedifex.domain.files import FileFormat
from aedifex.infrastructure.database.models import CrawlJob, CrawlJobStatus, DiscoveredUrl, Document
from aedifex.infrastructure.database.session import build_engine
from aedifex.infrastructure.storage.keys import raw_key

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(environment=Environment.TEST)


@pytest.fixture(scope="module")
def engine(settings: Settings) -> Iterator[Engine]:
    """Provide an engine, skipping the module if no database is reachable."""
    candidate = build_engine(settings)
    try:
        with candidate.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (OperationalError, DBAPIError) as error:
        candidate.dispose()
        pytest.skip(f"PostgreSQL is not reachable: {type(error).__name__}")
    yield candidate
    candidate.dispose()


@pytest.fixture(scope="module")
def _schema(engine: Engine, settings: Settings) -> Iterator[None]:
    """Apply migrations, then reverse them, proving both directions work."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", str(settings.database_url))

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield
    # A migration that cannot be reversed cannot be safely deployed.
    command.downgrade(config, "base")


@pytest.fixture
def session(engine: Engine, _schema: None) -> Iterator[Session]:
    """A session whose changes are rolled back, keeping tests independent."""
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as active:
        yield active
        active.rollback()
        for table in ("discovered_urls", "documents", "crawl_jobs"):
            active.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
        active.commit()


def make_document(payload: bytes = b"a pdf", source_id: str = "synthetic_projects") -> Document:
    digest = digest_of(payload)
    return Document(
        id=document_id_for_digest(digest),
        sha256=digest,
        size_bytes=len(payload),
        file_format=FileFormat.PDF,
        media_type="application/pdf",
        original_filename="invoice.pdf",
        storage_key=raw_key(source_id=source_id, sha256=digest, file_format=FileFormat.PDF),
        document_type=DocumentType.INVOICE,
        state=DocumentState.DOWNLOADED,
    )


class TestMigrations:
    def test_tables_exist_after_upgrade(self, session: Session) -> None:
        rows = session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
            )
        ).scalars()
        assert set(rows) == {"crawl_jobs", "documents", "discovered_urls"}

    def test_enum_columns_persist_lowercase_values(self, session: Session) -> None:
        """The database must hold 'invoice', not 'INVOICE'; queries depend on that spelling."""
        session.add(make_document())
        session.commit()
        stored = session.execute(text("SELECT document_type, state FROM documents")).one()
        assert stored.document_type == "invoice"
        assert stored.state == "downloaded"


class TestDocumentIdentity:
    def test_a_document_round_trips(self, session: Session) -> None:
        document = make_document()
        session.add(document)
        session.commit()
        loaded = session.get(Document, document.id)
        assert loaded is not None
        assert loaded.sha256 == document.sha256
        assert loaded.file_format is FileFormat.PDF

    def test_reinserting_the_same_content_conflicts(self, session: Session) -> None:
        """Deterministic ids are what make a re-crawl a no-op rather than a duplicate row."""
        session.add(make_document())
        session.commit()
        session.add(make_document())
        with pytest.raises(IntegrityError):
            session.commit()

    def test_digest_must_be_lowercase_hex(self, session: Session) -> None:
        document = make_document()
        document.sha256 = "X" * 64
        session.add(document)
        with pytest.raises(IntegrityError, match="sha256_is_lower_hex"):
            session.commit()

    def test_empty_documents_are_rejected_by_the_database(self, session: Session) -> None:
        document = make_document()
        document.size_bytes = 0
        session.add(document)
        with pytest.raises(IntegrityError, match="size_positive"):
            session.commit()

    def test_confidence_outside_zero_to_one_is_rejected(self, session: Session) -> None:
        document = make_document()
        document.classification_confidence = 1.5
        session.add(document)
        with pytest.raises(IntegrityError, match="confidence_in_range"):
            session.commit()

    def test_storage_keys_are_unique(self, session: Session) -> None:
        first = make_document(b"one")
        second = make_document(b"two")
        second.storage_key = first.storage_key
        session.add_all([first, second])
        with pytest.raises(IntegrityError, match="storage_key"):
            session.commit()


class TestDeduplicationWithProvenance:
    def test_two_urls_can_share_one_document(self, session: Session) -> None:
        """The core of the design: one payload stored once, every URL that yielded it retained."""
        document = make_document()
        session.add(document)
        session.flush()

        for url in ("https://a.test/doc.pdf", "https://b.test/mirror.pdf"):
            session.add(
                DiscoveredUrl(
                    source_id="synthetic_projects",
                    url=url,
                    url_sha256=digest_of(url.encode()),
                    state=DocumentState.VALIDATED,
                    document_id=document.id,
                    downloaded_at=datetime.now(UTC),
                )
            )
        session.commit()

        loaded = session.get(Document, document.id)
        assert loaded is not None
        assert len(loaded.sightings) == 2
        assert session.query(Document).count() == 1

    def test_the_same_url_cannot_be_recorded_twice_for_a_source(self, session: Session) -> None:
        """Re-running a crawler must re-find rows, not insert them again."""
        url = "https://a.test/doc.pdf"
        for _ in range(2):
            session.add(
                DiscoveredUrl(source_id="cpwd", url=url, url_sha256=digest_of(url.encode()))
            )
        with pytest.raises(IntegrityError, match="uq_discovered_urls_source_id_url_sha256"):
            session.commit()

    def test_the_same_url_at_two_sources_is_recorded_separately(self, session: Session) -> None:
        """Provenance is per source: the same document found twice is two findings."""
        url = "https://shared.test/doc.pdf"
        session.add_all(
            [
                DiscoveredUrl(source_id="cpwd", url=url, url_sha256=digest_of(url.encode())),
                DiscoveredUrl(source_id="nhai", url=url, url_sha256=digest_of(url.encode())),
            ]
        )
        session.commit()
        assert session.query(DiscoveredUrl).count() == 2

    def test_a_downloaded_url_must_name_its_document(self, session: Session) -> None:
        session.add(
            DiscoveredUrl(
                source_id="cpwd",
                url="https://a.test/x.pdf",
                url_sha256=digest_of(b"x"),
                state=DocumentState.VALIDATED,
                document_id=None,
            )
        )
        with pytest.raises(IntegrityError, match="document_required_after_download"):
            session.commit()

    def test_a_pending_url_needs_no_document(self, session: Session) -> None:
        """Content identity is unknowable before the payload has been fetched."""
        session.add(
            DiscoveredUrl(
                source_id="cpwd",
                url="https://a.test/y.pdf",
                url_sha256=digest_of(b"y"),
                state=DocumentState.DISCOVERED,
            )
        )
        session.commit()
        assert session.query(DiscoveredUrl).count() == 1

    def test_documents_cannot_be_deleted_while_referenced(self, session: Session) -> None:
        """Deleting content out from under its provenance would orphan the audit trail."""
        document = make_document()
        session.add(document)
        session.flush()
        session.add(
            DiscoveredUrl(
                source_id="cpwd",
                url="https://a.test/z.pdf",
                url_sha256=digest_of(b"z"),
                state=DocumentState.VALIDATED,
                document_id=document.id,
            )
        )
        session.commit()

        session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": str(document.id)})
        with pytest.raises(IntegrityError):
            session.commit()


class TestCrawlJobs:
    def test_a_running_job_has_no_finish_time(self, session: Session) -> None:
        job = CrawlJob(source_id="cpwd", software_version=__version__)
        session.add(job)
        session.commit()
        assert job.status is CrawlJobStatus.RUNNING
        assert job.finished_at is None

    def test_a_finished_job_must_record_when(self, session: Session) -> None:
        """Guards against the classic stuck-job bug where status and timestamps disagree."""
        job = CrawlJob(
            source_id="cpwd", software_version=__version__, status=CrawlJobStatus.SUCCEEDED
        )
        session.add(job)
        with pytest.raises(IntegrityError, match="finished_at_matches_status"):
            session.commit()

    def test_a_running_job_must_not_have_a_finish_time(self, session: Session) -> None:
        job = CrawlJob(
            source_id="cpwd",
            software_version=__version__,
            status=CrawlJobStatus.RUNNING,
            finished_at=datetime.now(UTC),
        )
        session.add(job)
        with pytest.raises(IntegrityError, match="finished_at_matches_status"):
            session.commit()

    def test_counters_cannot_go_negative(self, session: Session) -> None:
        job = CrawlJob(source_id="cpwd", software_version=__version__, documents_stored=-1)
        session.add(job)
        with pytest.raises(IntegrityError, match="counters_non_negative"):
            session.commit()

    def test_checkpoint_round_trips_as_json(self, session: Session) -> None:
        """Resumability depends on this surviving a restart intact."""
        job = CrawlJob(
            source_id="cpwd",
            software_version=__version__,
            checkpoint={"page": 12, "last_seen": "2026-08-01", "cursor": None},
        )
        session.add(job)
        session.commit()
        session.expire_all()

        loaded = session.get(CrawlJob, job.id)
        assert loaded is not None
        assert loaded.checkpoint == {"page": 12, "last_seen": "2026-08-01", "cursor": None}

    def test_urls_survive_their_job_being_deleted(self, session: Session) -> None:
        """Job history may be pruned; the frontier must not be destroyed with it."""
        job = CrawlJob(source_id="cpwd", software_version=__version__)
        session.add(job)
        session.flush()

        url = DiscoveredUrl(
            source_id="cpwd",
            url="https://a.test/j.pdf",
            url_sha256=digest_of(b"j"),
            job_id=job.id,
        )
        session.add(url)
        session.commit()

        session.execute(text("DELETE FROM crawl_jobs WHERE id = :id"), {"id": str(job.id)})
        session.commit()
        session.expire_all()

        surviving = session.get(DiscoveredUrl, url.id)
        assert surviving is not None
        assert surviving.job_id is None


class TestStatementTimeout:
    def test_a_statement_timeout_is_configured(self, engine: Engine, _schema: None) -> None:
        """An unbounded query is how a metadata store takes down the API."""
        with engine.connect() as connection:
            timeout = connection.execute(text("SHOW statement_timeout")).scalar_one()
        assert timeout not in ("0", 0)


def test_document_id_is_stable_across_processes(session: Session) -> None:
    """Derived from content alone, so it cannot depend on any local state."""
    payload = b"a stable payload"
    expected = uuid.uuid5(uuid.UUID("852e666c-780a-5903-85c4-d357129f3878"), digest_of(payload))
    document = make_document(payload)
    session.add(document)
    session.commit()
    assert document.id == expected
