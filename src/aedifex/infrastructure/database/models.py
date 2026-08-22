"""ORM models for the acquisition metadata store.

Four tables, and the split between them is the important design decision:

``crawl_jobs``
    One row per crawl run of one source. Holds the checkpoint that makes a run resumable, and the
    counters that describe what the run did.

``discovered_urls``
    The frontier, and also the durable work queue (ADR 0012): one row per (source, canonical URL)
    ever seen. This is where pipeline *state*, lease bookkeeping, and retry bookkeeping live. Unique
    on the URL digest per source, so re-running a crawler re-finds the same rows instead of
    inserting duplicates.

``documents``
    One row per unique *content*, keyed by a deterministic id derived from the SHA-256.

``document_retrievals``
    Append-only: one row per successful retrieval, holding both URLs, the HTTP metadata, the
    attempt history, and where the bytes were stored.

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
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as text_clause
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from aedifex.domain.documents import (
    ClassificationAuthority,
    DocumentCategory,
    DocumentState,
    DocumentType,
)
from aedifex.domain.evidence import (
    DocumentRole,
    DocumentVersionState,
    FactKind,
    RelationshipType,
)
from aedifex.domain.files import FileFormat
from aedifex.domain.review import conclusion_fingerprint

__all__ = [
    "Base",
    "CrawlJob",
    "CrawlJobStatus",
    "DiscoveredUrl",
    "Document",
    "DocumentRetrieval",
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
_CLASSIFICATION_AUTHORITY = _enum_column(ClassificationAuthority, length=32)
_FILE_FORMAT = _enum_column(FileFormat, length=16)
_CRAWL_JOB_STATUS = _enum_column(CrawlJobStatus, length=16)
_FACT_KIND = _enum_column(FactKind, length=24)
_DOCUMENT_ROLE = _enum_column(DocumentRole, length=32)
_RELATIONSHIP_TYPE = _enum_column(RelationshipType, length=24)
_VERSION_STATE = _enum_column(DocumentVersionState, length=16)

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

    # The counters carry a server default as well as a Python one, so a hand-written INSERT during
    # an incident cannot leave a null where a number belongs, and so the migration that added them
    # could run against a populated table.
    urls_discovered: Mapped[int] = mapped_column(Integer, default=0)
    urls_skipped: Mapped[int] = mapped_column(Integer, default=0, server_default=text_clause("0"))
    """Seen and deliberately not fetched: refused by robots.txt, or filtered out by the source."""
    documents_stored: Mapped[int] = mapped_column(Integer, default=0)
    documents_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    documents_failed: Mapped[int] = mapped_column(Integer, default=0)
    documents_quarantined: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text_clause("0")
    )
    bytes_downloaded: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text_clause("0")
    )

    stop_reason: Mapped[str | None] = mapped_column(String(64), default=None)
    """Why the run ended: the frontier drained, a limit was reached, or shutdown was signalled.

    Distinct from ``error_type``: a run that stops because it hit its document cap succeeded, and a
    run that stopped for that reason is not the same as one that finished the frontier. Without this
    a resumed crawl cannot tell "there is nothing left" from "we were told to stop".
    """

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
            "urls_discovered >= 0 AND urls_skipped >= 0 AND documents_stored >= 0 "
            "AND documents_duplicate >= 0 AND documents_failed >= 0 "
            "AND documents_quarantined >= 0 AND bytes_downloaded >= 0",
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
    """What this document is, authoritatively. Read by the extractor to decide what to suppress."""

    type_authority: Mapped[ClassificationAuthority] = mapped_column(
        _CLASSIFICATION_AUTHORITY,
        default=ClassificationAuthority.DECLARED,
        server_default=text_clause("'declared'"),
    )
    """Who decided :attr:`document_type`, and therefore how much weight it carries.

    Every row that existed before this column did was typed by an operator at ingest, which is
    exactly ``declared`` — so the server default backfills the truth rather than a guess.
    """

    document_category: Mapped[DocumentCategory] = mapped_column(
        _DOCUMENT_CATEGORY, default=DocumentCategory.UNKNOWN
    )

    suggested_document_type: Mapped[DocumentType | None] = mapped_column(
        _DOCUMENT_TYPE, default=None
    )
    """What a classifier thinks this is — in its own column, which is the entire point.

    A suggestion cannot be stored in :attr:`document_type` without becoming a decision, and
    ``document_type`` decides whether a quoted amount is treated as a fact about this document.
    Keeping the proposal beside the decision lets a workspace show "you filed this as UNKNOWN; it
    looks like a bill of quantities" without anything downstream acting on the guess.
    """

    classification_confidence: Mapped[float | None] = mapped_column(default=None)
    """How sure the classifier was about :attr:`suggested_document_type`, never the decision."""

    classifier_version: Mapped[str | None] = mapped_column(String(64), default=None)
    """Which classifier proposed it, e.g. ``filename_keywords:1``.

    Names the classifier as well as its version, so a deterministic proposal and a model's proposal
    are distinguishable in the row itself rather than by knowing which one was deployed that week.
    """

    state: Mapped[DocumentState] = mapped_column(
        _DOCUMENT_STATE, default=DocumentState.DOWNLOADED, index=True
    )

    version_state: Mapped[DocumentVersionState] = mapped_column(
        _VERSION_STATE,
        default=DocumentVersionState.ACTIVE,
        server_default=text_clause("'active'"),
        index=True,
    )
    """Whether this is the current version of what it describes.

    Distinct from :attr:`state`, which tracks *processing* — a document can be fully processed and
    superseded at the same time. Defaults to active because absent evidence of supersession a
    document is current; it is only ever changed by an explicit supersession or operator decision.
    """

    version_state_reason: Mapped[str | None] = mapped_column(Text, default=None)
    """Why the state is what it is, e.g. ``superseded by <document id> (operator)``.

    Stored because "why is this excluded from reconciliation?" is a question an auditor will ask,
    and a state with no recorded reason is indistinguishable from a bug.
    """

    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    sightings: Mapped[list[DiscoveredUrl]] = relationship(back_populates="document")
    retrievals: Mapped[list[DocumentRetrieval]] = relationship(back_populates="document")
    facts: Mapped[list[ExtractedFact]] = relationship(back_populates="document")
    findings: Mapped[list[Finding]] = relationship(back_populates="document")
    memberships: Mapped[list[ProjectDocument]] = relationship(back_populates="document")
    uploads: Mapped[list[DocumentUpload]] = relationship(back_populates="document")

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


class DocumentRetrieval(Base):
    """One successful retrieval of one document, and everything it took to get it.

    Append-only, and a separate table from both of its neighbours for reasons that are easy to get
    wrong:

    * Not on ``documents``, because a document is content and content has no single retrieval. The
      same PDF fetched from two portals is one row there and two here.
    * Not on ``discovered_urls``, because that is the frontier — mutable state, one row per URL,
      overwritten as a crawl progresses. A retrieval is an event that happened at a moment, and
      overwriting the record of the last one to describe this one would destroy the provenance this
      table exists to keep.

    So a re-download appends. That is deliberate: "we fetched this again in March and got the same
    bytes" is a fact worth having, and it is the frontier's job to avoid pointless re-downloads, not
    this table's job to hide them.

    ``storage_key`` is recorded here as well as on ``documents``, and the duplication is
    load-bearing. The raw key includes the source, so the same bytes from two portals have two keys
    while sharing one ``documents`` row — which can hold only one of them. The key that *this*
    retrieval wrote is only recoverable here.
    """

    __tablename__ = "document_retrievals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    source_id: Mapped[str] = mapped_column(String(64), index=True)

    # Both URLs, because a document retrieved after three redirects has a different provenance story
    # from one retrieved directly, and only one of the two appears in either version.
    requested_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text)

    retrieved_at: Mapped[datetime] = mapped_column(index=True)

    http_status: Mapped[int] = mapped_column(Integer)
    http_version: Mapped[str] = mapped_column(String(16))
    # Order- and duplicate-preserving, as a list of [name, value] pairs rather than an object:
    # Set-Cookie and Via may legitimately repeat, and a mapping would silently collapse them.
    response_headers: Mapped[list[list[str]]] = mapped_column(JSONB)
    declared_media_type: Mapped[str | None] = mapped_column(String(128), default=None)
    declared_content_length: Mapped[int | None] = mapped_column(BigInteger, default=None)

    # The attempt history, one entry per request made. JSONB rather than a child table: it is
    # written once, read as a whole, and never queried across rows — a table would add a join and a
    # migration for every field the retry layer learns to record.
    attempts: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)

    storage_bucket: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(512))
    storage_version_id: Mapped[str | None] = mapped_column(String(128), default=None)
    # How the upload was confirmed. A plain string with a check constraint rather than an enum
    # column, because the vocabulary lives in the storage layer and importing that here would pull
    # boto3 into the database models.
    storage_verification: Mapped[str] = mapped_column(String(32))

    # Reproducibility: which build produced this record.
    software_version: Mapped[str] = mapped_column(String(32))

    document: Mapped[Document] = relationship(back_populates="retrievals")

    __table_args__ = (
        CheckConstraint("http_status BETWEEN 100 AND 599", name="http_status_in_range"),
        CheckConstraint("attempt_count >= 1", name="at_least_one_attempt"),
        CheckConstraint(
            "storage_verification IN ('server_checksum', 'size_and_metadata')",
            name="verification_is_known",
        ),
        Index("ix_document_retrievals_source_retrieved", "source_id", "retrieved_at"),
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

    # --- Queue bookkeeping ---------------------------------------------------
    # This table is the durable queue as well as the frontier (ADR 0012). A lease rather than a
    # state change, so the acquirer keeps sole ownership of the document state machine: a claim
    # says "a worker is looking at this until then", and the state still moves DISCOVERED ->
    # DOWNLOADING inside the acquisition itself.
    lease_owner: Mapped[str | None] = mapped_column(String(64), default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(default=None)
    next_attempt_after: Mapped[datetime | None] = mapped_column(default=None)
    """Earliest a retry may be claimed. Backoff that survives a restart, unlike a sleep."""
    dead_lettered_at: Mapped[datetime | None] = mapped_column(default=None)
    """Set when a URL has exhausted its attempts. Terminal for the queue, not for the document.

    Deliberately a timestamp column rather than a new ``DocumentState``: that enum describes where a
    *document* is in its lifecycle, and queue exhaustion is a property of delivery. Adding it there
    would spread queue vocabulary through the document state machine and every exhaustive test over
    it, for a fact that only the claim query reads.
    """

    depth: Mapped[int] = mapped_column(Integer, default=0, server_default=text_clause("0"))
    """Links from the seed. Bounds a crawl and makes traversal order deterministic."""
    discovered_via: Mapped[str | None] = mapped_column(Text, default=None)
    """The page or API response this URL was found in. Discovery's own provenance."""

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
        CheckConstraint("depth >= 0", name="depth_non_negative"),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="lease_is_whole",
        ),
        # A URL that reached a content-bearing state must name the content it produced.
        CheckConstraint(
            "document_id IS NOT NULL OR state IN "
            "('discovered', 'downloading', 'failed', 'quarantined')",
            name="document_required_after_download",
        ),
        Index("ix_discovered_urls_state_source", "state", "source_id"),
        # The claim query's index. Ordered as the claim orders, so PostgreSQL can walk it rather
        # than sort a frontier that is expected to reach millions of rows.
        Index(
            "ix_discovered_urls_claimable",
            "source_id",
            "depth",
            "discovered_at",
            postgresql_where=text_clause("dead_lettered_at IS NULL"),
        ),
    )


class ExtractedFact(Base):
    """One value read out of one document, with the evidence for it.

    The unit of the intelligence layer, and deliberately narrow: a fact is a *single* value, its
    normalised form, and where in the document it was found. Facts are not interpreted here and
    carry no judgement -- that is what findings are for.

    Append-only within an extractor version. Re-running the same extractor over the same document
    is idempotent because of the unique constraint; changing the extractor produces a new row rather
    than overwriting the old one, so a finding made last month can still be read against the facts
    that actually produced it. Evidence that can be silently rewritten is not evidence.

    ``numeric_value`` is NUMERIC, not double precision. These values reach a division and a
    percentage comparison, and binary floating point is not a thing to do arithmetic on money with.
    """

    __tablename__ = "extracted_facts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )

    fact_type: Mapped[str] = mapped_column(String(64))
    """What the value is: ``estimated_cost``, ``bid_security``, ``nit_number``."""

    kind: Mapped[FactKind] = mapped_column(
        _FACT_KIND, default=FactKind.TEXT, server_default=text_clause("'text'"), index=True
    )
    """What kind of value it holds, independent of which field produced it (the shared fact model).

    This is what lets one comparison serve every money fact rather than being rewritten per document
    type: a cross-document rule selects on ``kind``, not on ``fact_type``.
    """

    literal: Mapped[str] = mapped_column(String(512))
    """The text exactly as the document rendered it, so a parse can be argued with."""

    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=None)
    currency: Mapped[str | None] = mapped_column(String(3), default=None)

    sheet_name: Mapped[str | None] = mapped_column(String(128), default=None)
    """Which sheet the cell is on, when this came from a spreadsheet.

    Added on 2026-08-22, and the omission was a real gap rather than an oversight in labelling: the
    row and column were stored while the sheet name existed only inside ``snippet`` (``BOQ!D7``) and
    ``method``. So the format the extractor-precedence rules call the *strongest* evidence available
    — a spreadsheet, which already carries rows, columns and cell positions — was the one a reviewer
    could not navigate to, while a PDF could be opened at a page. Existing rows were backfilled from
    the snippet, which is where the value had been all along.
    """

    sheet_row: Mapped[int | None] = mapped_column(Integer, default=None)
    """Row of the spreadsheet cell this came from, when it came from a spreadsheet.

    Separate columns rather than reusing ``span_start``/``span_end``, which are documented as
    character offsets into a page's text. Putting a row and a column in them was tried and rejected:
    it violated ``span_end >= span_start`` for any cell in column A, and — worse — it would have
    meant two different meanings for one pair of columns, so a reader could not tell what a number
    in ``span_start`` referred to without first knowing the document's format.
    """

    sheet_column: Mapped[int | None] = mapped_column(Integer, default=None)

    unit: Mapped[str | None] = mapped_column(String(16), default=None)
    """Unit of measure for a quantity, e.g. ``m3``, ``MT``. Explicit, never inferred.

    A quantity without its unit is not a number anyone should compute with: 470 of one thing and 470
    of another are only comparable if both say what they are counting.
    """

    work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), index=True, default=None
    )
    """The construction item this fact is about, when it is about one.

    ``SET NULL`` rather than cascade: if a work item is removed the fact is still a true statement
    about its document, and deleting evidence because a grouping changed would be the wrong way
    round.
    """

    date_value: Mapped[date | None] = mapped_column(Date, default=None)
    """Parsed calendar value for :attr:`FactKind.DATE` facts, so chronology is a query.

    A separate column rather than a string in ``literal`` because ordering documents by publication
    is the point of extracting a date at all, and ordering by text sorts 07.09.2026 before
    07.08.2026 whenever the format changes.
    """

    # Where it came from. A fact without these is an assertion.
    page: Mapped[int] = mapped_column(Integer)
    span_start: Mapped[int] = mapped_column(Integer)
    span_end: Mapped[int] = mapped_column(Integer)
    snippet: Mapped[str] = mapped_column(Text)
    """Verbatim surrounding text, so a reviewer can judge the value without opening the PDF."""

    method: Mapped[str] = mapped_column(String(128))
    """Which extraction rule produced it, e.g. ``table:header-block``."""

    extractor: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(32))
    extracted_at: Mapped[datetime] = mapped_column(server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="facts")

    retraction: Mapped[FactRetraction | None] = relationship(
        back_populates="fact", uselist=False, cascade="all, delete-orphan"
    )
    """The withdrawal of this fact, if a later extractor version said it should not exist.

    ``None`` for every fact that still stands, which is almost all of them. Present means this row
    is history: readable, citable by the findings that were computed from it, and never selected as
    a current fact again.
    """

    @property
    def is_retracted(self) -> bool:
        """Whether a later extractor version withdrew this fact.

        The one question every consumer of a fact has to ask, given a name so nobody has to remember
        that ``retraction is not None`` is what it means.
        """
        return self.retraction is not None

    __table_args__ = (
        # A prose document states each kind of fact once; a table states it once per row. The
        # original single constraint assumed the former, and a spreadsheet silently kept only its
        # last row -- the extraction was correct and the persistence discarded it.
        #
        # Two partial indexes rather than one over four columns, because NULL never equals NULL in
        # PostgreSQL: a single index including sheet_row would stop deduplicating page facts
        # entirely, which is the failure this constraint exists to prevent.
        Index(
            "uq_extracted_facts_document_type",
            "document_id",
            "fact_type",
            "extractor_version",
            unique=True,
            postgresql_where=text_clause("sheet_row IS NULL"),
        ),
        Index(
            "uq_extracted_facts_document_type_row",
            "document_id",
            "fact_type",
            "extractor_version",
            "sheet_row",
            unique=True,
            postgresql_where=text_clause("sheet_row IS NOT NULL"),
        ),
        CheckConstraint("page >= 1", name="page_is_one_based"),
        CheckConstraint("span_end >= span_start", name="span_is_whole"),
        CheckConstraint("currency IS NULL OR currency = upper(currency)", name="currency_is_upper"),
    )


class FactRetraction(Base):
    """A later extractor version asserting that an earlier fact should never have existed.

    Extractor versioning already handles a *correction*: version 2 writes a better value, selection
    takes the newest version, and the older row stays readable so a finding made against it is still
    explainable. It cannot handle a *retraction*, because a retraction writes nothing — and a fact
    that is silently not re-emitted remains the newest row for its document and fact type, so it
    stays selected.

    That is not hypothetical. On 2026-08-21 five real documents produced six facts the documents
    never stated — ₹13,262 crore of Polavaram resettlement colonies recorded as a CAG report's own
    estimated cost, dates lifted from specimen forms inside model agreements. The extractor was
    corrected, version 3 declined to emit them, and all six rows remained selectable and were still
    being served by the facts API.

    So a retraction is recorded as its own row, and the shape follows from what it actually is: **a
    new assertion by an extractor version about an existing fact**, not a property of that fact. The
    fact row is never touched, never deleted, and stays exactly as reproducible as before; what
    changes is that something now says it is wrong. Append-only, like everything else here.

    One retraction per fact, enforced by a unique constraint. Retracting twice is not a second
    opinion, it is a repeated run, and it should be idempotent.
    """

    __tablename__ = "fact_retractions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    fact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extracted_facts.id", ondelete="CASCADE"), index=True
    )
    """The fact being withdrawn. ``CASCADE`` because a retraction of a deleted fact says nothing."""

    retracted_by_extractor: Mapped[str] = mapped_column(String(64))
    retracted_by_version: Mapped[str] = mapped_column(String(32))
    """Which extractor and version made the assertion, so it is attributable like any other.

    Necessarily a *later* version than the fact's own, and the check constraint enforces nothing
    about that because string versions do not order reliably. The reason field carries the argument.
    """

    reason: Mapped[str] = mapped_column(Text)
    """Why, in prose, in the operator's words or the extractor's.

    Mandatory and not nullable. A withdrawal of evidence with no stated reason is indistinguishable
    from a bug, and the whole point of keeping the row is that someone can later disagree with it.
    """

    retracted_at: Mapped[datetime] = mapped_column(server_default=func.now())
    software_version: Mapped[str] = mapped_column(String(32))

    fact: Mapped[ExtractedFact] = relationship(back_populates="retraction")

    __table_args__ = (
        UniqueConstraint("fact_id", name="one_retraction_per_fact"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_is_not_blank"),
    )


class Finding(Base):
    """The result of evaluating one deterministic rule against one document's facts.

    A finding says what was checked, what was expected, what was observed, and which facts it read.
    It stores the observed value rather than only the verdict, because "FAIL" without the number is
    not a result anybody can act on -- and because a threshold that later turns out to be wrong
    should be re-judgeable without re-running anything.

    Rules are versioned. A verdict is only reproducible if you know which version of which rule
    produced it, and rule thresholds are exactly the kind of thing that gets revised once real
    documents disagree with them.
    """

    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Exactly one of these is set. A single-document rule scopes its finding to that document; a
    # cross-document rule scopes it to the project, because the conclusion belongs to neither
    # document alone — "these two documents disagree" is not a fact about one of them.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, default=None
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True, default=None
    )
    """The item of work this finding is about, when it is about one.

    Set alongside ``project_id``, never instead of it: a work item exists only within a project, and
    a reviewer filtering by project must see item findings too.
    """

    rule_id: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(16), index=True)
    """``pass``, ``fail``, or ``inconclusive``. Inconclusive is not a failure of the document."""

    summary: Mapped[str] = mapped_column(Text)
    expected: Mapped[str] = mapped_column(String(256))
    observed: Mapped[str] = mapped_column(String(256))

    detail: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    """The numbers the rule used, as strings, so the arithmetic can be re-checked by hand."""

    conclusion_fingerprint: Mapped[str] = mapped_column(
        String(64), default="", server_default=text_clause("''")
    )
    """A digest of this conclusion: the rule, the verdict, the values compared, and the citations.

    Stored rather than computed on read, and the reason is not only speed. It is written once by
    whichever persister wrote the finding, at the moment the evidence links are in hand — so reading
    it later is a column comparison rather than a walk through ``finding_evidence`` and out into
    three possible evidence tables. That walk would run on every project summary and every document
    inventory, which is how a page becomes hundreds of queries.

    Its purpose is :attr:`current_review`. See
    :func:`aedifex.domain.review.conclusion_fingerprint` for what goes into it and why.
    """

    evaluated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    document: Mapped[Document | None] = relationship(back_populates="findings")
    project: Mapped[Project | None] = relationship(back_populates="findings")
    evidence: Mapped[list[FindingEvidence]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[FindingReview]] = relationship(
        back_populates="finding",
        cascade="all, delete-orphan",
        # Both columns, because a timestamp alone does not order these reliably. Two reviews written
        # in one transaction shared a ``reviewed_at``: ``now()`` is the transaction's start time,
        # not the statement's, so their order — and therefore *which one is current* — was whatever
        # the planner returned. ``reviewed_at`` is now ``clock_timestamp()`` and the id breaks any
        # remaining tie, so the sequence is fixed rather than incidental.
        order_by="FindingReview.reviewed_at, FindingReview.id",
    )
    """Every human decision recorded against this finding, oldest first.

    A list rather than one row, unlike ``ExtractedFact.retraction``: a second review genuinely is a
    second opinion and both belong on the record, whereas retracting a fact twice is just a repeated
    run. Use :attr:`current_review` rather than the last element — the last element may be stale.
    """

    def compute_fingerprint(self) -> str:
        """Derive this finding's conclusion fingerprint from its evidence links.

        Walks ``finding_evidence`` and out into the fact, derived-fact and provision tables, so it
        is only called where those rows are already at hand: immediately after a persister writes
        them. Everything that reads a fingerprint reads the stored column.

        Each citation is described by its **content** — role, kind, value, location — rather than by
        its row id, so a re-extraction that rewrites a row carrying the same value at the same place
        does not invalidate a review of it.
        """
        citations: list[tuple[str | None, ...]] = []
        for link in sorted(self.evidence, key=lambda item: item.role):
            if link.fact is not None:
                citations.append(
                    (
                        link.role,
                        "extracted",
                        link.fact.fact_type,
                        link.fact.literal,
                        None if link.fact.numeric_value is None else str(link.fact.numeric_value),
                        f"page:{link.fact.page}",
                        link.fact.sheet_name,
                        None if link.fact.sheet_row is None else str(link.fact.sheet_row),
                    )
                )
            elif link.derived_fact is not None:
                citations.append(
                    (
                        link.role,
                        "derived",
                        link.derived_fact.fact_type,
                        link.derived_fact.expression,
                        (
                            None
                            if link.derived_fact.numeric_value is None
                            else str(link.derived_fact.numeric_value)
                        ),
                    )
                )
            elif link.provision is not None:
                citations.append(
                    (
                        link.role,
                        "policy",
                        link.provision.provision_type,
                        link.provision.clause,
                        None if link.provision.share is None else str(link.provision.share),
                        f"page:{link.provision.page}",
                    )
                )
        return conclusion_fingerprint(
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            outcome=self.outcome,
            expected=self.expected,
            observed=self.observed,
            detail=self.detail or {},
            evidence=citations,
        )

    @property
    def current_review(self) -> FindingReview | None:
        """The newest review that was made against *this* conclusion, or ``None``.

        A review decides a conclusion, and a conclusion is more than its verdict word. Until
        2026-08-22 this compared only ``outcome`` and ``rule_version``, which meant a re-read that
        changed every number while leaving the outcome alone silently kept the old acceptance:

        .. code-block:: text

            reviewed:  FAIL  claim 520 m3 exceeds the measured 470 m3      accepted
            re-read:   FAIL  claim 900 m3 exceeds the measured 470 m3      still "accepted"

        So the comparison is now the whole conclusion — rule, verdict, both values, the rule's own
        numbers, and the citations — via :attr:`conclusion_fingerprint`. Everything earlier becomes
        **stale** and stops counting as the current state, which is what stops an accepted ``FAIL``
        presenting as an accepted ``PASS`` and, now, an accepted ₹54,518 presenting as an accepted
        ₹62,900.

        All three columns are compared, not just the fingerprint, and the redundancy is deliberate.
        The fingerprint catches what the other two cannot see — a changed value under an unchanged
        verdict. The other two catch what the fingerprint cannot: a finding whose outcome or rule
        version was changed *without* going through a persister, which is what a hand-written UPDATE
        during an incident looks like. A derived column is only as good as the code maintaining it,
        and inheriting an acceptance is the failure that matters here, so the cheaper check stays.

        They also serve a second purpose: they are what a reader is *shown* when a review goes
        stale. The fingerprint can only say that something changed.
        """
        for review in reversed(self.reviews):
            # An empty stored fingerprint means "written before fingerprints existed", and the
            # migration backfilled both sides together, so equality still holds for those rows.
            if (
                review.reviewed_fingerprint == self.conclusion_fingerprint
                and review.reviewed_outcome == self.outcome
                and review.reviewed_rule_version == self.rule_version
            ):
                return review
        return None

    __table_args__ = (
        # Two partial uniques rather than one over both columns: a NULL never equals a NULL in
        # PostgreSQL, so a plain UNIQUE(document_id, rule_id, rule_version) would permit unlimited
        # duplicate project findings.
        Index(
            "uq_findings_document_rule",
            "document_id",
            "rule_id",
            "rule_version",
            unique=True,
            postgresql_where=text_clause("document_id IS NOT NULL"),
        ),
        Index(
            "uq_findings_project_rule",
            "project_id",
            "rule_id",
            "rule_version",
            unique=True,
            # Excludes work-item findings, which carry project_id too and would otherwise collide
            # with each other the moment two items were checked by the same rule.
            postgresql_where=text_clause("project_id IS NOT NULL AND work_item_id IS NULL"),
        ),
        Index(
            "uq_findings_work_item_rule",
            "work_item_id",
            "rule_id",
            "rule_version",
            unique=True,
            postgresql_where=text_clause("work_item_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(document_id IS NULL) <> (project_id IS NULL)",
            name="finding_scoped_to_exactly_one_subject",
        ),
        CheckConstraint(
            "work_item_id IS NULL OR project_id IS NOT NULL",
            name="work_item_finding_belongs_to_a_project",
        ),
        CheckConstraint(
            "outcome IN ('pass', 'fail', 'review', 'inconclusive')", name="outcome_is_known"
        ),
    )


class FindingEvidence(Base):
    """Which fact a finding relied on, and in what capacity.

    A join table rather than a JSON list of ids, so the database itself refuses a finding that
    points at a fact which no longer exists. This is the link that makes a result traceable all the
    way back to a page span of a stored document, which is the property the whole pipeline exists to
    have.
    """

    __tablename__ = "finding_evidence"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(64), primary_key=True)
    """How the rule used it, e.g. ``estimated_cost``. Names the slot, not just the link.

    Part of the primary key because a rule may cite the same fact in two slots, and because a slot
    is what the finding actually refers to — ``estimated_cost#1`` means something to a reader in a
    way that a bare fact id does not.
    """

    # Exactly one of these three. A rule cites what a document states about itself, a value computed
    # from such statements, or a norm a reference document imposes. All three are evidence and all
    # three are traceable to a page; which one it is must never be ambiguous, because they support
    # different claims. A provision is a threshold, not a measurement.
    fact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extracted_facts.id", ondelete="RESTRICT"), default=None
    )
    derived_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("derived_facts.id", ondelete="RESTRICT"), default=None
    )
    provision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy_provisions.id", ondelete="RESTRICT"), default=None
    )

    finding: Mapped[Finding] = relationship(back_populates="evidence")
    fact: Mapped[ExtractedFact | None] = relationship()
    derived_fact: Mapped[DerivedFact | None] = relationship()
    provision: Mapped[PolicyProvision | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "(fact_id IS NOT NULL)::int + (derived_fact_id IS NOT NULL)::int "
            "+ (provision_id IS NOT NULL)::int = 1",
            name="evidence_cites_exactly_one_kind_of_fact",
        ),
    )


class Project(Base):
    """A construction project: the boundary within which documents are compared.

    The aggregation boundary the SRS asks for. A project is identified by an ``external_ref`` taken
    from the documents themselves — for NHAI tenders, the tender number — so membership is
    established by evidence rather than asserted. Two documents belong to one project because both
    state the same identifier, and the fact that says so is stored with a page and a span.

    Scoped deliberately: rules compare facts *within* a project and never across. Two projects that
    happen to quote the same amount have nothing to say about each other, and a comparison that
    crossed the boundary would manufacture findings out of coincidence.
    """

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    source_id: Mapped[str] = mapped_column(String(64), index=True)
    """Which registered source **namespaces this project's identifier**. Acquisition metadata, and
    nothing else.

    Stated precisely, because a loose reading of this column would eventually become a security
    defect. It exists for one reason: ``external_ref`` is only unique within the authority that
    issued it, so two authorities can both publish tender ``PWD/2026/14`` and those are two
    projects. Pairing the reference with a source is what keeps reconciliation from merging them.

    Three things it is **not**:

    * **not ownership, and not a tenant.** Authorization, when it arrives, is a separate model
      (``Organization → Membership → Project``) and a new column. Reinterpreting this one would give
      every future authorization check the appearance of scoping while scoping nothing, which is
      worse than having no check at all.
    * **not the source of the project's documents.** Membership legitimately spans sources: one
      project holds an owner-uploaded bill, a contractor's claim, a PMC's certificate and a
      published rate schedule. Each *document* records its own origin in ``document_uploads`` or
      ``document_retrievals``; this column says nothing about them.
    * **not a constraint on attachment.** Nothing refuses a document from another source, and
      nothing should: origin affects provenance and nothing after it.
    """

    external_ref: Mapped[str | None] = mapped_column(String(256), default=None)
    """The identifier the documents themselves use, e.g. a tender number. Never invented.

    Nullable since 2026-08-21, when projects became declarable by the person who owns the work
    rather than only derivable from shared facts. A developer creating "Hostel 19" before uploading
    anything may have no reference number to give, and the alternative — synthesising one from the
    name — would put an invented identifier in the column whose whole contract is that it is never
    invented. An absent identifier is recorded as absent.

    Two consequences, both intended. Two declared projects with no identifier are two projects, even
    if identically named, because ``NULL`` is distinct under the unique constraint and nothing
    entitles us to merge them. And a declared project whose ``external_ref`` *does* match what the
    documents state is found and reused by reconciliation instead of being duplicated, so a
    declaration and the evidence converge on one row.
    """

    name: Mapped[str | None] = mapped_column(Text, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    """What the project is, in the owner's words. Never parsed, never used by a rule."""

    established_by: Mapped[str] = mapped_column(String(128))
    """How the project came to exist, e.g. ``shared_fact:nit_number`` or ``declared:alice``.

    Reused for declaration rather than given a second column, because the question is the same one:
    what justifies this row? A derived project cites the fact that grouped it; a declared project
    cites the person who said so. Never ``inferred``.
    """

    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    memberships: Mapped[list[ProjectDocument]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    relationships: Mapped[list[DocumentRelationship]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    findings: Mapped[list[Finding]] = relationship(back_populates="project")
    work_items: Mapped[list[WorkItem]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def label(self) -> str:
        """The project as a human refers to it: its identifier, else its name, else its id.

        Exists because ``external_ref`` became nullable and every display path had been printing it
        directly. A workspace listing "None" would be a formatting bug reported as missing data.
        """
        return self.external_ref or self.name or str(self.id)

    __table_args__ = (
        UniqueConstraint("source_id", "external_ref", name="one_project_per_source_reference"),
    )


class ProjectDocument(Base):
    """One document's membership of one project, and the part it plays in it.

    ``role`` defaults to ``unclassified`` and stays there unless something can establish it. A role
    guessed from a filename or a page count would put an unsourced claim underneath every
    relationship built on it.
    """

    __tablename__ = "project_documents"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[DocumentRole] = mapped_column(_DOCUMENT_ROLE, default=DocumentRole.UNCLASSIFIED)
    established_by: Mapped[str] = mapped_column(String(128))

    filename: Mapped[str | None] = mapped_column(String(128), default=None)
    """What *this* project's uploader called the file.

    ``documents.original_filename`` is content-level and records the name the bytes first arrived
    under, which is the right thing for a catalogue and the wrong thing for a workspace: with
    content-addressed identity, a second project uploading identical bytes was shown the *first*
    project's filename. For a shared rate schedule that is merely odd; for a bill a contractor sent
    to two parties it displays one customer's naming inside another customer's project.

    Null for a membership that reconciliation derived rather than an upload creating, where there is
    no per-project name to record.
    """

    linked_at: Mapped[datetime] = mapped_column(server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="memberships")
    document: Mapped[Document] = relationship(back_populates="memberships")


class DocumentRelationship(Base):
    """An explicit, stored relationship between two documents in one project.

    First-class rather than derived on read, because a relationship is a claim about the world and
    a claim needs provenance: ``established_by`` records what justified it. Nothing here is inferred
    by a model — the only relationship currently derivable is ``same_tender``, from two documents
    stating an identical identifier, which is exact string equality.

    Symmetric relationships are stored once, in a canonical direction (lower document id first), so
    that "A relates to B" and "B relates to A" cannot disagree.
    """

    __tablename__ = "document_relationships"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    from_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    to_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    relationship_type: Mapped[RelationshipType] = mapped_column(_RELATIONSHIP_TYPE)
    established_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="relationships")

    __table_args__ = (
        UniqueConstraint(
            "from_document_id",
            "to_document_id",
            "relationship_type",
            name="one_relationship_per_pair_and_type",
        ),
        CheckConstraint(
            "from_document_id <> to_document_id", name="relationship_joins_two_documents"
        ),
    )


class PolicyProvision(Base):
    """A norm a reference document states about *other* projects, not about itself.

    The distinction this table exists for was found by running the NHAI Works Manual through the
    pipeline. It states ``two percent of the estimated cost for works up to Rs. 20 crore``, and the
    tender-tuned extractor recorded ``estimated_cost = Rs 20,00,00,000`` as a fact about a 297-page
    procedure manual. **A quoted amount inside a reference document is not a fact about that
    document.** An :class:`ExtractedFact` answers "what does this document state about itself"; a
    provision answers "what rule does this document impose on others", and conflating them puts a
    threshold into the evidence graph as though it were a measurement.

    So a provision is not a fact with an extra column. It carries the things a fact never does — an
    authority, a jurisdiction, an effective date, and the conditions under which it applies — and it
    lacks the thing a fact always has, which is a subject. Nothing here is a formula language: the
    applicability of the one real provision is a band on a single quantity, and it is stored as a
    band on a single quantity.
    """

    __tablename__ = "policy_provisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    """The reference document that states it. A provision with no source is an assertion."""

    provision_type: Mapped[str] = mapped_column(String(64), index=True)
    """What the norm governs, e.g. ``bid_security_share``."""

    # --- Where it is written. The same locator an extracted fact carries, for the same reason.
    clause: Mapped[str] = mapped_column(String(64))
    """The document's own reference, e.g. ``4.14.1(a)``. Quoted, never invented."""

    page: Mapped[int] = mapped_column()
    span_start: Mapped[int] = mapped_column()
    span_end: Mapped[int] = mapped_column()
    snippet: Mapped[str] = mapped_column(Text)

    # --- Who it binds, and from when.
    authority: Mapped[str] = mapped_column(String(64), index=True)
    """The body whose rule this is, e.g. ``nhai``. Matched against a project's source."""

    jurisdiction: Mapped[str] = mapped_column(String(8))
    """ISO country code. A rule of one state does not govern another."""

    effective_from: Mapped[date | None] = mapped_column(Date, default=None)
    """When it began to apply, when the document says. Null means the document does not say."""

    # --- The applicability condition. One dimension, because one real provision needs one.
    applies_to: Mapped[str] = mapped_column(String(64))
    """The quantity the band is measured on, e.g. ``estimated_cost``."""

    applies_from: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=None)
    """Inclusive lower bound of the band. Null means unbounded below."""

    applies_to_max: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=None)
    """Inclusive upper bound of the band. Null means unbounded above."""

    # --- The value it imposes.
    share: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), default=None)
    """A fraction, e.g. ``0.02`` for two percent. Null if the provision states no share."""

    cap_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), default=None)
    """A ceiling on the resulting amount, e.g. Rs 30 lacs. Null if uncapped."""

    currency: Mapped[str | None] = mapped_column(String(3), default=None)

    extractor: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(32))
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    document: Mapped[Document] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "provision_type",
            "clause",
            "extractor_version",
            name="one_provision_per_clause_per_extractor_version",
        ),
        CheckConstraint("page >= 1", name="page_is_one_based"),
        CheckConstraint("span_end >= span_start", name="span_is_whole"),
        # A band that excludes everything is a parse error, not a policy.
        CheckConstraint(
            "applies_from IS NULL OR applies_to_max IS NULL OR applies_to_max >= applies_from",
            name="band_is_whole",
        ),
        # A provision that imposes nothing cannot be applied to anything.
        CheckConstraint(
            "share IS NOT NULL OR cap_amount IS NOT NULL",
            name="imposes_something",
        ),
        CheckConstraint(
            "currency IS NULL OR currency = upper(currency)",
            name="currency_is_upper",
        ),
    )


class DerivedFact(Base):
    """A value computed deterministically from facts, stored so more than one rule can use it.

    The SRS calls for these to be first-class rather than living inside whichever rule needed them.
    The reason is reuse, but the effect is explainability: a derived fact records its inputs, the
    calculation that produced it, and that calculation's version, so a reader can redo the
    arithmetic by hand and get the same number. A value computed inside a rule and thrown away
    leaves a finding asserting a figure nobody can re-derive.

    Scoped like a finding: to one document when every input came from it, to a project when the
    inputs span documents. A share computed from a notice's own two amounts is a fact about that
    notice; a remaining contract value computed from a contract and a bill is a fact about neither.

    Carries no judgement. ``bid_security_share = 0.02`` says nothing about whether 2% is correct —
    that is a rule's business, and keeping the two apart is what lets one calculation serve rules
    that disagree about what it means.
    """

    __tablename__ = "derived_facts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, default=None
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )

    fact_type: Mapped[str] = mapped_column(String(64), index=True)
    """What was computed, e.g. ``bid_security_share``."""

    kind: Mapped[FactKind] = mapped_column(_FACT_KIND)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), default=None)
    """Wider and more precise than an extracted amount: a share is a ratio, not a rupee figure."""

    currency: Mapped[str | None] = mapped_column(String(3), default=None)
    unit: Mapped[str | None] = mapped_column(String(32), default=None)

    calculation: Mapped[str] = mapped_column(String(128))
    """The named calculation that produced it, e.g. ``share_of``."""

    calculation_version: Mapped[str] = mapped_column(String(32))
    produced_by: Mapped[str] = mapped_column(String(128))
    """The module responsible, so a wrong value leads to the code that made it."""

    expression: Mapped[str] = mapped_column(Text)
    """The arithmetic in words, e.g. ``1693000 / 84649969``. What makes it redoable by hand."""

    inputs_fingerprint: Mapped[str] = mapped_column(String(64), server_default=text_clause("''"))
    """Digest of the exact input fact ids this value was computed from.

    Identity by calculation version alone was not enough. A calculation is stale when its *inputs*
    change — a superseded document dropping out of active selection, or a newer fact replacing an
    older one — and the version does not move for either. Comparing fingerprints makes that
    detectable, so a reused value can be distinguished from a recomputed one rather than assumed
    current.
    """

    computed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    inputs: Mapped[list[DerivedFactInput]] = relationship(
        back_populates="derived_fact", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "(document_id IS NULL) <> (project_id IS NULL)",
            name="derived_fact_scoped_to_exactly_one_subject",
        ),
        Index(
            "uq_derived_facts_document",
            "document_id",
            "fact_type",
            "calculation_version",
            unique=True,
            postgresql_where=text_clause("document_id IS NOT NULL"),
        ),
        Index(
            "uq_derived_facts_project",
            "project_id",
            "fact_type",
            "calculation_version",
            unique=True,
            postgresql_where=text_clause("project_id IS NOT NULL"),
        ),
    )


class DerivedFactInput(Base):
    """One fact that fed one calculation, and the slot it filled.

    Stored rather than implied, because "which numbers produced this" is the whole provenance of a
    computed value. ``ON DELETE RESTRICT`` on the fact: a derived value must not outlive the
    evidence it came from, and silently keeping it would leave a number with no origin.
    """

    __tablename__ = "derived_fact_inputs"

    derived_fact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("derived_facts.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(64), primary_key=True)

    # A calculation reads a fact or applies a provision. "Required bid security" is the share from
    # clause 4.14.1 multiplied by a cost the tender states, so it has one input of each -- and both
    # must be citable or the derived value has a page for half its origin.
    fact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extracted_facts.id", ondelete="RESTRICT"), default=None
    )
    provision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy_provisions.id", ondelete="RESTRICT"), default=None
    )

    derived_fact: Mapped[DerivedFact] = relationship(back_populates="inputs")
    fact: Mapped[ExtractedFact | None] = relationship()
    provision: Mapped[PolicyProvision | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "(fact_id IS NULL) <> (provision_id IS NULL)",
            name="input_is_fact_or_provision",
        ),
    )


class WorkItem(Base):
    """One item of construction work within a project — the thing a payment claim is about.

    The aggregation key that makes payment reconciliation possible. A bill of quantities, a
    measurement book, and a running bill each say something about "item 4.7.2"; until those three
    statements are attached to one object there is nothing to reconcile.

    Matching is deterministic and layered: an exact item identifier first, then a normalised form of
    it. Nothing here uses embeddings or a model. A seam is left for semantic matching by keeping
    ``matched_by`` on every link, so a future fuzzy match would be visibly weaker evidence rather
    than silently equivalent to an exact one.

    Scoped to a project, because item numbering restarts with every contract: "4.7.2" identifies a
    work item only in the presence of the project it belongs to.
    """

    __tablename__ = "work_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )

    item_identifier: Mapped[str] = mapped_column(String(64))
    """The item number as the documents write it, e.g. ``4.7.2``."""

    normalised_identifier: Mapped[str] = mapped_column(String(64))
    """Case- and separator-normalised form, which is what matching actually compares."""

    description: Mapped[str | None] = mapped_column(Text, default=None)
    unit: Mapped[str | None] = mapped_column(String(16), default=None)
    matched_by: Mapped[str] = mapped_column(String(64))
    """How facts were attached: ``exact_identifier`` or ``normalised_identifier``. Never guessed."""

    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="work_items")
    facts: Mapped[list[ExtractedFact]] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "project_id", "normalised_identifier", name="one_work_item_per_project_identifier"
        ),
    )


class DocumentUpload(Base):
    """Provenance for a document that was uploaded rather than fetched.

    A separate table from ``document_retrievals`` because the two record genuinely different events.
    A retrieval has a URL, an HTTP status and response headers; an upload has a filesystem path and
    a person or script that put it there. Reusing the retrieval table would have meant inventing an
    HTTP 200 for a request nobody made, which is fabricating provenance — the one thing this project
    will not do, even for its own synthetic data.

    ``is_synthetic`` is stored rather than inferred from the source id, so a query for real evidence
    can exclude generated data without knowing which sources happen to be synthetic today.
    """

    __tablename__ = "document_uploads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(String(64), index=True)

    original_path: Mapped[str] = mapped_column(Text)
    """Where the file came from. Descriptive only, never used to build a storage key."""

    is_synthetic: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())
    uploaded_by: Mapped[str] = mapped_column(String(128))

    storage_bucket: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(512))
    storage_verification: Mapped[str] = mapped_column(String(32))
    software_version: Mapped[str] = mapped_column(String(32))

    document: Mapped[Document] = relationship(back_populates="uploads")

    __table_args__ = (
        # An upload is an *event*, and two people handing us the same bytes are two events. The
        # constraint used to be (document_id, source_id), which was tolerable while every source had
        # one operator and became wrong the moment `customer_provided` existed: two customers
        # uploading identical content — a contractor's bill sent to the owner and the PMC — were
        # collapsed into whichever arrived first, and the second uploader, their filename, their
        # timestamp and their note were simply not recorded.
        #
        # The uploader and the stated path are in the key so a repeated *identical* ingest — the
        # same person re-running the same script — stays idempotent, which is what the original
        # constraint was protecting. What is no longer deduplicated is two different people, or one
        # person filing the same bytes under a different name.
        UniqueConstraint(
            "document_id",
            "source_id",
            "uploaded_by",
            "original_path",
            name="one_upload_per_document_source_and_uploader",
        ),
    )


class FindingReview(Base):
    """A person's decision about one finding: the pipeline's last stage, and its trust boundary.

    Everything upstream of this table is deterministic. This is where judgement is allowed to enter,
    and the design constraint is that it must enter **visibly** — attributed, dated, reasoned, and
    append-only, exactly like every other assertion in the corpus.

    Why it exists, stated as the invariant it implements: an uncertain document reading becomes
    authoritative evidence only when deterministic validation closes **or a human accepts it**.
    Until this table existed the second clause was not expressible, so the trust boundary the
    project is built on had no representation in code.

    **Append-only, and deliberately without a one-review-per-finding constraint.** That is the
    difference from :class:`FactRetraction`, where retracting twice is a repeated run and is made
    idempotent. Here a second review is a *second opinion* — a senior reviewer disagreeing with a
    junior one is precisely the thing an audit trail should preserve — so reviews accumulate and
    :attr:`Finding.current_review` decides which one speaks for the finding now.

    **A review is about a verdict, not about a rule.** ``reviewed_outcome`` and
    ``reviewed_rule_version`` record what the reviewer was actually looking at, so revising a rule
    or re-evaluating a document invalidates prior reviews instead of silently inheriting them.
    Without those two columns an accepted ``FAIL`` would present as an accepted ``PASS`` the moment
    a threshold changed, which loses a finding without deleting anything.
    """

    __tablename__ = "finding_reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )

    decision: Mapped[str] = mapped_column(String(24))
    """One of ``accepted``, ``rejected``, ``needs_evidence``.

    See :class:`aedifex.domain.review.ReviewDecision` for what each one is for.
    """

    note: Mapped[str] = mapped_column(Text)
    """The reviewer's reasoning, mandatory and non-blank.

    A decision with no stated reason is indistinguishable from a mis-click, and the value of keeping
    the row is that someone can later disagree with the argument rather than just the verdict.
    """

    reviewer: Mapped[str] = mapped_column(String(128))
    """Who decided, as recorded by the caller.

    A free string and not a foreign key, because this deployment has no user table and inventing one
    to hold a name would be building authentication under another name. When identity arrives, this
    becomes the migration target rather than a thing to retrofit.
    """

    reviewed_outcome: Mapped[str] = mapped_column(String(16))
    reviewed_rule_version: Mapped[str] = mapped_column(String(32))
    """What the finding said at the moment of review. See the class docstring."""

    reviewed_fingerprint: Mapped[str] = mapped_column(
        String(64), default="", server_default=text_clause("''")
    )
    """The conclusion this review was made against, as a digest.

    What decides whether the review still speaks for the finding. The two columns above are kept
    because they are how a reader is *told* what changed; this is what detects it, including the
    cases they cannot see — a different observed value, a different comparison, a different cited
    cell, under the same outcome and the same rule version.
    """

    reviewed_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())
    """When, by the wall clock at the moment of the insert.

    ``clock_timestamp()`` rather than ``now()``, which returns the *transaction's* start time: two
    reviews recorded in one transaction shared a timestamp, leaving their order — and so which is
    current — up to the query planner.
    """
    software_version: Mapped[str] = mapped_column(String(32))

    finding: Mapped[Finding] = relationship(back_populates="reviews")

    __table_args__ = (
        CheckConstraint("length(btrim(note)) > 0", name="note_is_not_blank"),
        CheckConstraint("length(btrim(reviewer)) > 0", name="reviewer_is_not_blank"),
        CheckConstraint(
            "decision IN ('accepted', 'rejected', 'needs_evidence')",
            name="decision_is_known",
        ),
        Index("ix_finding_reviews_decision", "decision"),
    )
