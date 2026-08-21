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

from aedifex.domain.documents import DocumentCategory, DocumentState, DocumentType
from aedifex.domain.evidence import (
    DocumentRole,
    DocumentVersionState,
    FactKind,
    RelationshipType,
)
from aedifex.domain.files import FileFormat

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
    document_category: Mapped[DocumentCategory] = mapped_column(
        _DOCUMENT_CATEGORY, default=DocumentCategory.UNKNOWN
    )
    classification_confidence: Mapped[float | None] = mapped_column(default=None)
    classifier_version: Mapped[str | None] = mapped_column(String(64), default=None)

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

    evaluated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    document: Mapped[Document | None] = relationship(back_populates="findings")
    project: Mapped[Project | None] = relationship(back_populates="findings")
    evidence: Mapped[list[FindingEvidence]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )

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
    external_ref: Mapped[str] = mapped_column(String(256))
    """The identifier the documents themselves use, e.g. a tender number. Never invented."""

    name: Mapped[str | None] = mapped_column(Text, default=None)
    established_by: Mapped[str] = mapped_column(String(128))
    """How membership was determined, e.g. ``shared_fact:nit_number``. Never ``inferred``."""

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
        UniqueConstraint("document_id", "source_id", name="one_upload_per_document_and_source"),
    )
