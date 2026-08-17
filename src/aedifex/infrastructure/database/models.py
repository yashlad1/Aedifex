"""ORM models for the acquisition metadata store.

Three tables, and the split between them is the important design decision:

``crawl_jobs``
    One row per crawl run of one source. Holds the checkpoint that makes a run resumable.

``discovered_urls``
    The frontier: one row per (source, URL) ever seen. This is where pipeline *state* and
    retry bookkeeping live. Unique on the URL digest per source, so re-running a crawler
    re-finds the same rows instead of inserting duplicates.

``documents``
    One row per unique *content*, keyed by a deterministic id derived from the SHA-256.

Separating the last two is what lets deduplication coexist with provenance. The same PDF is
routinely published at several URLs, and sometimes across several portals. Collapsing on
content would lose the URLs; keying on URL would store the bytes repeatedly. Here, many
``discovered_urls`` rows may point at one ``documents`` row, so the corpus holds each
payload once while still being able to answer "everywhere we saw this file".

A URL's ``document_id`` is null until the payload has been fetched and hashed, since content
identity cannot be known before download.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from aedifex.domain.documents import DocumentCategory, DocumentState, DocumentType
from aedifex.domain.files import FileFormat

__all__ = [
    "Base",
    "CrawlJob",
    "CrawlJobStatus",
    "DiscoveredUrl",
    "Document",
]


class CrawlJobStatus(StrEnum):
    """Lifecycle of a crawl run.

    Distinct from :class:`~aedifex.domain.documents.DocumentState`: a job either finishes
    or does not, whereas a document moves through validation and processing.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _enum_column(python_enum: type[StrEnum], *, length: int) -> Enum:
    """Build a VARCHAR-backed enum column that persists the enum's *values*.

    Two choices are encoded here:

    * ``native_enum=False`` — plain ``VARCHAR`` rather than a PostgreSQL enum type. This
      vocabulary is expected to grow as document types are added, and extending a native
      enum requires DDL. Values are validated on write by SQLAlchemy
      (``validate_strings=True``); note that this is application-layer enforcement, so the
      database alone will accept an out-of-vocabulary string written by hand.
    * ``values_callable`` — persist ``"invoice"``, not ``"INVOICE"``. SQLAlchemy defaults to
      storing enum *names*, which would put a second spelling of every term in the database
      and force translation in every hand-written query and API response.
    """
    return Enum(
        python_enum,
        native_enum=False,
        length=length,
        validate_strings=True,
        values_callable=lambda enum_type: [member.value for member in enum_type],
    )


_DOCUMENT_STATE = _enum_column(DocumentState, length=32)
_DOCUMENT_TYPE = _enum_column(DocumentType, length=48)
_DOCUMENT_CATEGORY = _enum_column(DocumentCategory, length=32)
_FILE_FORMAT = _enum_column(FileFormat, length=16)
_CRAWL_JOB_STATUS = _enum_column(CrawlJobStatus, length=16)

_SHA256_HEX = "~ '^[0-9a-f]{64}$'"


# Deterministic constraint names. Without a convention, PostgreSQL invents names for
# unnamed constraints, `alembic check` reports phantom differences, and a downgrade cannot
# reliably drop what an upgrade created.
_NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base. Alembic autogenerate compares against ``Base.metadata``."""

    metadata = MetaData(naming_convention=_NAMING_CONVENTION)

    # SQLAlchemy reads this as a plain mapping, so RUF012 does not apply.
    type_annotation_map = {  # noqa: RUF012
        datetime: DateTime(timezone=True),
    }


class CrawlJob(Base):
    """One execution of one source's crawler."""

    __tablename__ = "crawl_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(64), index=True)

    status: Mapped[CrawlJobStatus] = mapped_column(
        _CRAWL_JOB_STATUS, default=CrawlJobStatus.RUNNING, index=True
    )
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(default=None)

    urls_discovered: Mapped[int] = mapped_column(Integer, default=0)
    documents_stored: Mapped[int] = mapped_column(Integer, default=0)
    documents_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    documents_failed: Mapped[int] = mapped_column(Integer, default=0)

    # Opaque, crawler-defined resume point (page number, cursor, last-seen date). Kept as
    # JSONB so adding a new crawler does not require a schema change.
    checkpoint: Mapped[dict[str, object] | None] = mapped_column(JSONB, default=None)

    error_type: Mapped[str | None] = mapped_column(String(128), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    # Reproducibility: which build of the software produced this run's artifacts.
    software_version: Mapped[str] = mapped_column(String(32))

    urls: Mapped[list[DiscoveredUrl]] = relationship(back_populates="job")

    __table_args__ = (
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name="finished_at_matches_status",
        ),
        CheckConstraint(
            "urls_discovered >= 0 AND documents_stored >= 0 "
            "AND documents_duplicate >= 0 AND documents_failed >= 0",
            name="counters_non_negative",
        ),
        Index("ix_crawl_jobs_source_started", "source_id", "started_at"),
    )


class Document(Base):
    """A unique document, identified by the SHA-256 of its content.

    The primary key is a UUIDv5 derived from the digest, so ingesting the same bytes twice
    is a no-op rather than a duplicate row.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)

    size_bytes: Mapped[int] = mapped_column(BigInteger)
    file_format: Mapped[FileFormat] = mapped_column(_FILE_FORMAT)
    media_type: Mapped[str | None] = mapped_column(String(128), default=None)

    # Descriptive only. Never used to build storage paths (see storage/keys.py).
    original_filename: Mapped[str | None] = mapped_column(String(128), default=None)

    storage_key: Mapped[str] = mapped_column(String(512), unique=True)

    document_type: Mapped[DocumentType] = mapped_column(
        _DOCUMENT_TYPE, default=DocumentType.UNKNOWN
    )
    document_category: Mapped[DocumentCategory] = mapped_column(
        _DOCUMENT_CATEGORY, default=DocumentCategory.UNKNOWN
    )
    classification_confidence: Mapped[float | None] = mapped_column(default=None)
    classifier_version: Mapped[str | None] = mapped_column(String(64), default=None)

    state: Mapped[DocumentState] = mapped_column(
        _DOCUMENT_STATE, default=DocumentState.DOWNLOADED, index=True
    )

    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    sightings: Mapped[list[DiscoveredUrl]] = relationship(back_populates="document")

    __table_args__ = (
        CheckConstraint(f"sha256 {_SHA256_HEX}", name="sha256_is_lower_hex"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint(
            "classification_confidence IS NULL "
            "OR (classification_confidence >= 0 AND classification_confidence <= 1)",
            name="confidence_in_range",
        ),
        Index("ix_documents_type_state", "document_type", "state"),
    )


class DiscoveredUrl(Base):
    """A URL seen at a source: the crawl frontier and per-URL pipeline state.

    Uniqueness is on ``(source_id, url_sha256)`` rather than on the URL text, because
    procurement portals emit URLs long enough to exceed btree index limits.
    """

    __tablename__ = "discovered_urls"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(Text)
    url_sha256: Mapped[str] = mapped_column(String(64))

    state: Mapped[DocumentState] = mapped_column(
        _DOCUMENT_STATE, default=DocumentState.DISCOVERED, index=True
    )

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), default=None, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("crawl_jobs.id", ondelete="SET NULL"), default=None, index=True
    )

    discovered_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_attempted_at: Mapped[datetime | None] = mapped_column(default=None)
    downloaded_at: Mapped[datetime | None] = mapped_column(default=None)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    http_status: Mapped[int | None] = mapped_column(Integer, default=None)
    error_type: Mapped[str | None] = mapped_column(String(128), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    document: Mapped[Document | None] = relationship(back_populates="sightings")
    job: Mapped[CrawlJob | None] = relationship(back_populates="urls")

    __table_args__ = (
        UniqueConstraint("source_id", "url_sha256"),
        CheckConstraint(f"url_sha256 {_SHA256_HEX}", name="url_sha256_is_lower_hex"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        # A URL that reached a content-bearing state must name the content it produced.
        CheckConstraint(
            "document_id IS NOT NULL OR state IN "
            "('discovered', 'downloading', 'failed', 'quarantined')",
            name="document_required_after_download",
        ),
        Index("ix_discovered_urls_state_source", "state", "source_id"),
    )
