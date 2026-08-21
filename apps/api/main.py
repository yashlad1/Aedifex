"""FastAPI application: the corpus read model, and the project intake workflow.

Read-only until 2026-08-21, when the first product workflow needed a beginning. It now has three
kinds of endpoint, and the difference between them matters more than any of them individually:

* **the corpus catalog** — what has been acquired, described by its provenance;
* **the project workspace** — declare a project, give it documents, read its state back;
* **the review boundary** — record what a person concluded about a finding.

.. warning::

   **THE WRITE API IS NOT PUBLICLY DEPLOYABLE UNTIL AUTHORIZATION EXISTS.**

   There is no authentication, no authorization and no tenancy. Any caller who can reach this
   service can create a project, upload a document into it, and confirm a document's type — and
   project identifiers are global UUIDs with nothing scoping them to an owner. That is acceptable
   for a single-operator development deployment and for nothing else, so
   :func:`require_write_access` refuses every write when the environment is ``production``. The
   refusal is a stopgap that makes the gap loud rather than a control that closes it: the real fix
   is an authenticated identity and a project that belongs to a tenant.

Crawling is still not triggered by HTTP. A long-running crawl behind a request handler would tie up
a worker and make timeouts meaningless. Project *processing* is a deliberate exception and is
synchronous — see the endpoint's own note.

Every response carries an ``X-Request-ID``, and that same id is bound into the logging
context for the duration of the request, so a log query on one identifier returns the whole
story of a request.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Final

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from aedifex import __version__
from aedifex.acquisition.catalog import (
    CatalogEntry,
    CorpusSummary,
    RunSummary,
    catalog_entries,
    catalog_entry,
    corpus_summary,
    crawl_runs,
    queue_depth_by_source,
)
from aedifex.acquisition.registry import SourceDefinition, SourceRegistry, get_registry
from aedifex.config import Environment, Settings, get_settings
from aedifex.domain.documents import DocumentType
from aedifex.domain.evidence import FactOrigin
from aedifex.domain.review import ReviewDecision
from aedifex.errors import AedifexError, SourceRegistryError
from aedifex.infrastructure.database.models import (
    DerivedFact,
    DocumentRelationship,
    ExtractedFact,
    Finding,
    FindingReview,
    Project,
    ProjectDocument,
    WorkItem,
)
from aedifex.infrastructure.database.session import session_scope
from aedifex.infrastructure.observability.logging import (
    bind_job_context,
    configure_logging,
    get_logger,
    new_request_id,
)
from aedifex.infrastructure.storage.client import build_s3_client
from aedifex.infrastructure.storage.objects import RawObjectStore
from aedifex.knowledge.registry import (
    DOCUMENT_VERSION_STATES,
    FACT_TYPES,
    FINDING_OUTCOMES,
    RELATIONSHIP_TYPES,
    RULE_TYPES,
)
from aedifex.review import ReviewError, record_review
from aedifex.workspace import (
    DocumentEntry,
    IntakeError,
    attach_upload,
    confirm_document_type,
    create_project,
    process_project,
    project_inventory,
    project_summary,
)

API_PREFIX: Final[str] = "/v1"
REQUEST_ID_HEADER: Final[str] = "X-Request-ID"

MAX_UPLOAD_BYTES: Final[int] = 64 * 1024 * 1024
"""Ceiling on one uploaded document, and the reason it is not the 256 MiB download ceiling.

This implementation holds the whole upload in memory to hash and store it, so the bound is a memory
bound as much as a policy one. 64 MiB is more than twelve times the largest document in the corpus
(a 5 MB technical specification) and far below anything that threatens a worker. Streaming to a
temporary file is the fix when a customer brings a drawing set; until one does, a smaller cap
with an honest reason beats a larger one with none.
"""

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Liveness response. Deliberately dependency-free."""

    status: str = "ok"
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    """Readiness response, reporting each dependency separately."""

    status: str
    version: str
    checks: dict[str, str] = Field(
        description="Per-dependency outcome: 'ok' or a short failure reason."
    )


class DataUseResponse(BaseModel):
    """Licence metadata, surfaced so consumers of the corpus can see its constraints."""

    model_config = ConfigDict(frozen=True)

    license: str
    terms_url: str | None
    access: str
    allowed_use: str
    attribution_required: bool
    contains_personal_data: bool


class SourceResponse(BaseModel):
    """A source registry entry."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str | None
    country: str
    category: str
    retrieval: str
    base_url: str | None
    enabled: bool
    verification_status: str
    is_collectable: bool = Field(
        description="Whether a crawl run may currently fetch from this source."
    )
    crawler: str | None
    document_types: list[str]
    file_formats: list[str]
    data_use: DataUseResponse
    requests_per_minute: int
    last_successful_run: str | None

    @classmethod
    def from_definition(cls, source: SourceDefinition) -> SourceResponse:
        return cls(
            id=source.id,
            name=source.name,
            description=source.description,
            country=source.country,
            category=source.category.value,
            retrieval=source.retrieval.value,
            base_url=str(source.base_url) if source.base_url else None,
            enabled=source.enabled,
            verification_status=source.verification_status.value,
            is_collectable=source.is_collectable,
            crawler=source.crawler,
            document_types=[item.value for item in source.document_types],
            file_formats=[item.value for item in source.file_formats],
            data_use=DataUseResponse(
                license=source.data_use.license,
                terms_url=str(source.data_use.terms_url) if source.data_use.terms_url else None,
                access=source.data_use.access.value,
                allowed_use=source.data_use.allowed_use,
                attribution_required=source.data_use.attribution_required,
                contains_personal_data=source.data_use.contains_personal_data,
            ),
            requests_per_minute=source.rate_limit.requests_per_minute,
            last_successful_run=(
                source.last_successful_run.isoformat() if source.last_successful_run else None
            ),
        )


class SourceListResponse(BaseModel):
    total: int
    collectable: int
    sources: list[SourceResponse]


class DocumentResponse(BaseModel):
    """One document in the corpus, described by its most recent retrieval.

    Read-only, and deliberately not a download endpoint: the bytes live in object storage behind
    credentials, and handing them out over an unauthenticated API would publish a corpus whose
    licence terms differ per source (rule 55 — authentication before public deployment).
    """

    model_config = ConfigDict(frozen=True)

    document_id: str
    sha256: str
    size_bytes: int
    file_format: str
    media_type: str | None
    original_filename: str | None
    state: str
    version_state: str
    version_state_reason: str | None
    source_id: str
    requested_url: str
    final_url: str
    was_redirected: bool
    retrieved_at: str
    http_status: int
    attempt_count: int
    retrieval_count: int
    storage_uri: str
    storage_version_id: str | None
    storage_verification: str
    first_seen_at: str

    @classmethod
    def from_entry(cls, entry: CatalogEntry) -> DocumentResponse:
        return cls(
            document_id=str(entry.document_id),
            sha256=entry.sha256,
            size_bytes=entry.size_bytes,
            file_format=entry.file_format.value,
            media_type=entry.media_type,
            original_filename=entry.original_filename,
            state=entry.state.value,
            version_state=entry.version_state.value,
            version_state_reason=entry.version_state_reason,
            source_id=entry.source_id,
            requested_url=entry.requested_url,
            final_url=entry.final_url,
            was_redirected=entry.was_redirected,
            retrieved_at=entry.retrieved_at.isoformat(),
            http_status=entry.http_status,
            attempt_count=entry.attempt_count,
            retrieval_count=entry.retrieval_count,
            storage_uri=entry.uri,
            storage_version_id=entry.storage_version_id,
            storage_verification=entry.storage_verification,
            first_seen_at=entry.first_seen_at.isoformat(),
        )


class DocumentListResponse(BaseModel):
    total_in_corpus: int
    returned: int
    documents: list[DocumentResponse]


class CorpusSummaryResponse(BaseModel):
    """The corpus in one object: what is held, and what the queue still owes."""

    model_config = ConfigDict(frozen=True)

    documents: int
    retrievals: int
    bytes_stored: int
    sources: int
    by_source: dict[str, int]
    by_format: dict[str, int]
    by_state: dict[str, int]
    urls_seen: int
    urls_downloaded: int
    urls_failed: int
    urls_dead_lettered: int
    duplicate_url_rate: float
    queue_depth: dict[str, int]
    first_seen_at: str | None
    last_retrieved_at: str | None

    @classmethod
    def from_summary(cls, summary: CorpusSummary, depth: dict[str, int]) -> CorpusSummaryResponse:
        return cls(
            documents=summary.documents,
            retrievals=summary.retrievals,
            bytes_stored=summary.bytes_stored,
            sources=summary.sources,
            by_source=dict(summary.by_source),
            by_format=dict(summary.by_format),
            by_state=dict(summary.by_state),
            urls_seen=summary.urls_seen,
            urls_downloaded=summary.urls_downloaded,
            urls_failed=summary.urls_failed,
            urls_dead_lettered=summary.urls_dead_lettered,
            duplicate_url_rate=round(summary.duplicate_url_rate, 4),
            queue_depth=depth,
            first_seen_at=summary.first_seen_at.isoformat() if summary.first_seen_at else None,
            last_retrieved_at=(
                summary.last_retrieved_at.isoformat() if summary.last_retrieved_at else None
            ),
        )


class CrawlRunResponse(BaseModel):
    """One crawl run's operational metrics (FR-078).

    Counts and rates only. No URLs and no document ids, so this stays safe to graph without a
    cardinality explosion (rule 62); the per-URL detail is in the logs and the frontier.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    source_id: str
    status: str
    stop_reason: str | None
    started_at: str
    finished_at: str | None
    duration_seconds: float | None
    urls_discovered: int
    urls_skipped: int
    documents_stored: int
    documents_duplicate: int
    documents_failed: int
    documents_quarantined: int
    bytes_downloaded: int
    success_rate: float
    duplicate_rate: float
    software_version: str
    error_type: str | None

    @classmethod
    def from_run(cls, run: RunSummary) -> CrawlRunResponse:
        return cls(
            job_id=str(run.job_id),
            source_id=run.source_id,
            status=run.status.value,
            stop_reason=run.stop_reason,
            started_at=run.started_at.isoformat(),
            finished_at=run.finished_at.isoformat() if run.finished_at else None,
            duration_seconds=(
                round(run.duration_seconds, 3) if run.duration_seconds is not None else None
            ),
            urls_discovered=run.urls_discovered,
            urls_skipped=run.urls_skipped,
            documents_stored=run.documents_stored,
            documents_duplicate=run.documents_duplicate,
            documents_failed=run.documents_failed,
            documents_quarantined=run.documents_quarantined,
            bytes_downloaded=run.bytes_downloaded,
            success_rate=round(run.success_rate, 4),
            duplicate_rate=round(run.duplicate_rate, 4),
            software_version=run.software_version,
            error_type=run.error_type,
        )


class CrawlRunListResponse(BaseModel):
    returned: int
    runs: list[CrawlRunResponse]


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


class FactResponse(BaseModel):
    """One extracted fact and the span of the document that supports it.

    Carries the literal alongside the normalised value on purpose. A caller who disagrees with our
    parse of "Rs. 16.93 Lacs" can see exactly what the document said and argue with the number
    rather than having to trust it.
    """

    model_config = ConfigDict(frozen=True)

    fact_id: str
    document_id: str
    fact_type: str
    literal: str
    value: str | None
    currency: str | None
    page: int
    span_start: int
    span_end: int
    snippet: str
    method: str
    extractor: str
    extractor_version: str
    extracted_at: str
    retracted: bool
    """Whether a later extractor version said this fact should never have existed.

    Returned rather than filtered out, for the same reason superseded versions are returned: a
    finding computed from this row has to stay explainable. But a client must never present a
    retracted fact as something the document states — that is exactly what this flag is for, and
    before it existed the API served ₹13,262 crore of another project's resettlement colonies as a
    CAG audit report's own estimated cost.
    """

    retracted_reason: str | None = None

    @classmethod
    def from_row(cls, row: ExtractedFact) -> FactResponse:
        return cls(
            fact_id=str(row.id),
            document_id=str(row.document_id),
            fact_type=row.fact_type,
            literal=row.literal,
            # Serialised as a string, not a float: these are exact decimals and JSON numbers are
            # not. A money value that survives extraction only to be rounded by a JSON parser has
            # been corrupted at the last possible moment.
            value=None if row.numeric_value is None else str(row.numeric_value),
            currency=row.currency,
            page=row.page,
            span_start=row.span_start,
            span_end=row.span_end,
            snippet=row.snippet,
            method=row.method,
            extractor=row.extractor,
            extractor_version=row.extractor_version,
            extracted_at=row.extracted_at.isoformat(),
            retracted=row.is_retracted,
            retracted_reason=None if row.retraction is None else row.retraction.reason,
        )


class EvidenceResponse(BaseModel):
    """A finding's citation of one fact: which fact, in what role, and where it came from.

    Covers both kinds. ``origin`` says whether a document stated the value or the calculation layer
    computed it; ``page`` and ``snippet`` are present only for the former, and ``expression`` only
    for the latter. A client must not present a computed value as something a document says.
    """

    model_config = ConfigDict(frozen=True)

    role: str
    origin: str
    fact_id: str
    fact_type: str
    literal: str
    page: int | None = None
    snippet: str | None = None
    value: str | None = None
    expression: str | None = None
    """For a derived fact, the arithmetic performed — so the number can be redone by hand."""


class ReviewResponse(BaseModel):
    """One human decision about a finding.

    ``stale`` is the field that matters. A review decides a *verdict*, so if the rule was revised or
    re-evaluation changed the outcome, an earlier review no longer speaks for this finding and a
    client must not render it as the current state. Kept and shown rather than hidden, because
    "someone accepted the previous conclusion" is worth seeing.
    """

    model_config = ConfigDict(frozen=True)

    review_id: str
    decision: str
    note: str
    reviewer: str
    reviewed_outcome: str
    reviewed_rule_version: str
    reviewed_at: str
    stale: bool

    @classmethod
    def from_row(cls, row: FindingReview, finding: Finding) -> ReviewResponse:
        return cls(
            review_id=str(row.id),
            decision=row.decision,
            note=row.note,
            reviewer=row.reviewer,
            reviewed_outcome=row.reviewed_outcome,
            reviewed_rule_version=row.reviewed_rule_version,
            reviewed_at=row.reviewed_at.isoformat(),
            stale=(
                row.reviewed_outcome != finding.outcome
                or row.reviewed_rule_version != finding.rule_version
            ),
        )


class ReviewRequest(BaseModel):
    """A reviewer's decision, as submitted.

    Note and reviewer are required and non-blank by construction. The outcome and rule version are
    deliberately *not* accepted from the client — the server reads them off the finding, so the
    record says what the reviewer was actually looking at rather than what they claimed.
    """

    model_config = ConfigDict(frozen=True)

    decision: ReviewDecision
    note: str = Field(min_length=1, max_length=4000)
    reviewer: str = Field(min_length=1, max_length=128)


class FindingResponse(BaseModel):
    """One rule's verdict on one document, with the evidence it rested on.

    ``outcome`` may be ``inconclusive``, and that is a first-class answer rather than a failure:
    it means the rule could not source a threshold it was willing to judge against. Clients must
    render it distinctly from ``pass`` — ``expected`` reads ``NOT SOURCED`` in that case.
    """

    model_config = ConfigDict(frozen=True)

    finding_id: str
    document_id: str
    rule_id: str
    rule_version: str
    outcome: str
    summary: str
    expected: str
    observed: str
    detail: dict[str, object]
    evaluated_at: str
    evidence: list[EvidenceResponse]
    reviews: list[ReviewResponse] = Field(default_factory=list)
    review_state: str = "unreviewed"
    """``unreviewed``, or the decision of the newest review made against *this* verdict.

    Never the newest review outright: a stale review does not decide anything. See
    ``Finding.current_review``.
    """

    @classmethod
    def from_row(
        cls,
        row: Finding,
        facts: dict[uuid.UUID, ExtractedFact],
        derived: dict[uuid.UUID, DerivedFact] | None = None,
    ) -> FindingResponse:
        cited: list[EvidenceResponse] = []
        for link in sorted(row.evidence, key=lambda e: e.role):
            if link.fact_id is not None:
                fact = facts.get(link.fact_id)
                if fact is None:
                    continue
                cited.append(
                    EvidenceResponse(
                        role=link.role,
                        origin=FactOrigin.EXTRACTED.value,
                        fact_id=str(fact.id),
                        fact_type=fact.fact_type,
                        literal=fact.literal,
                        page=fact.page,
                        snippet=fact.snippet,
                        value=None if fact.numeric_value is None else str(fact.numeric_value),
                    )
                )
                continue
            computed = (derived or {}).get(link.derived_fact_id) if link.derived_fact_id else None
            if computed is None:
                continue
            cited.append(
                EvidenceResponse(
                    role=link.role,
                    origin=FactOrigin.DERIVED.value,
                    fact_id=str(computed.id),
                    fact_type=computed.fact_type,
                    literal=f"{computed.calculation} v{computed.calculation_version}",
                    value=None if computed.numeric_value is None else str(computed.numeric_value),
                    expression=computed.expression,
                )
            )
        return cls(
            finding_id=str(row.id),
            document_id=str(row.document_id),
            rule_id=row.rule_id,
            rule_version=row.rule_version,
            outcome=row.outcome,
            summary=row.summary,
            expected=row.expected,
            observed=row.observed,
            detail=dict(row.detail),
            evaluated_at=row.evaluated_at.isoformat(),
            evidence=cited,
            reviews=[ReviewResponse.from_row(r, row) for r in row.reviews],
            review_state=(
                current.decision if (current := row.current_review) is not None else "unreviewed"
            ),
        )


class FactListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    returned: int
    facts: list[FactResponse]


class FindingListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    returned: int
    findings: list[FindingResponse]


class ProjectResponse(BaseModel):
    """One project: the boundary within which documents are compared.

    ``external_ref`` is nullable because a project can now be *declared* by the person who owns the
    work before any document has stated an identifier. ``established_by`` says which happened —
    ``declared:alice`` or ``shared_fact:nit_number`` — and a client should show it, because "someone
    said so" and "two documents agree" are different warrants for the same row.
    """

    model_config = ConfigDict(frozen=True)

    project_id: str
    source_id: str
    external_ref: str | None
    name: str | None
    description: str | None
    label: str = Field(
        description="Identifier, else name, else id. What to display without ever rendering null."
    )
    established_by: str
    document_count: int
    first_seen_at: str

    @classmethod
    def from_row(cls, row: Project, document_count: int) -> ProjectResponse:
        return cls(
            project_id=str(row.id),
            source_id=row.source_id,
            external_ref=row.external_ref,
            name=row.name,
            description=row.description,
            label=row.label,
            established_by=row.established_by,
            document_count=document_count,
            first_seen_at=row.first_seen_at.isoformat(),
        )


class ProjectCreateRequest(BaseModel):
    """A project as declared by its owner. Three fields, and two of them are optional.

    Deliberately not a project-management schema. Authority, contractor, location, value, dates and
    milestones are all things a construction project has and none of them is needed to hold its
    documents together — and every one of them would be an unsourced assertion until a document
    states it. When a rule needs one, it will read it from evidence rather than from this form.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=512)
    source_id: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "The registered source these documents belong to. Required because projects never "
            "span sources: two authorities can issue the same reference and they are not one "
            "project. This is the column tenancy will replace."
        ),
    )
    created_by: str = Field(min_length=1, max_length=96)
    external_identifier: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=4000)


class ProjectDocumentResponse(BaseModel):
    """One document as the project workspace shows it: identity, classification, state, workload.

    Everything a document row in the workspace needs, in one object. The alternative — the client
    joining the corpus catalog to the facts endpoint to the findings endpoint to the reviews
    endpoint — is how a UI ends up with four subtly different ideas of what is in a project.
    """

    model_config = ConfigDict(frozen=True)

    document_id: str
    filename: str | None
    file_format: str
    size_bytes: int
    sha256: str
    document_type: str
    type_authority: str = Field(
        description="Who decided the type: 'declared' by the uploader, or 'human_confirmed'."
    )
    workflow_category: str = Field(
        description="Which link of the construction chain this document is evidence for."
    )
    role: str
    suggested_type: str | None = Field(
        default=None,
        description=(
            "What the deterministic classifier proposes. A suggestion, never applied: nothing "
            "downstream reads this field, and only a person may move it into document_type."
        ),
    )
    classification_confidence: float | None = None
    classifier: str | None = None
    classification_disputed: bool = Field(
        description="The classifier proposes something other than what this is filed as."
    )
    status: str = Field(
        description=(
            "uploaded | processing | processed | needs_attention | unsupported | failed. A "
            "product-facing projection, not the internal document state."
        )
    )
    origin: str = Field(description="'upload' or 'crawl'. Provenance, not status.")
    source_id: str | None
    acquired_at: str | None
    attached_at: str
    attached_by: str
    fact_count: int
    finding_count: int
    review_needed: int = Field(
        description="Not a pass, and no review speaking for the verdict as it now stands."
    )

    @classmethod
    def from_entry(cls, entry: DocumentEntry) -> ProjectDocumentResponse:
        return cls(
            document_id=str(entry.document_id),
            filename=entry.filename,
            file_format=entry.file_format.value,
            size_bytes=entry.size_bytes,
            sha256=entry.sha256,
            document_type=entry.document_type.value,
            type_authority=entry.type_authority.value,
            workflow_category=entry.category.value,
            role=entry.role.value,
            suggested_type=(None if entry.suggested_type is None else entry.suggested_type.value),
            classification_confidence=entry.classification_confidence,
            classifier=entry.classifier,
            classification_disputed=entry.classification_disputed,
            status=entry.status.value,
            origin=entry.origin,
            source_id=entry.source_id,
            acquired_at=None if entry.acquired_at is None else entry.acquired_at.isoformat(),
            attached_at=entry.attached_at.isoformat(),
            attached_by=entry.attached_by,
            fact_count=entry.fact_count,
            finding_count=entry.finding_count,
            review_needed=entry.review_needed,
        )


class ProjectDocumentListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: str
    returned: int
    documents: list[ProjectDocumentResponse]


class UploadResponse(BaseModel):
    """What one upload did, with storage and membership reported separately.

    The two booleans are the deduplication contract made visible. ``artifact_was_new`` is about
    content identity; ``membership_was_new`` is about this project. Uploading the same bill twice to
    one project sets neither, and uploading it to a second project sets only the second — which is
    the distinction between an artifact and a business fact about it.
    """

    model_config = ConfigDict(frozen=True)

    project_id: str
    document: ProjectDocumentResponse
    artifact_was_new: bool
    membership_was_new: bool
    suggested_type: str | None
    suggestion_matched: str | None = Field(
        default=None,
        description="The filename phrase the classifier matched, so it is explainable.",
    )


class ClassificationRequest(BaseModel):
    """A person's decision about what a document is."""

    model_config = ConfigDict(frozen=True)

    document_type: DocumentType
    confirmed_by: str = Field(min_length=1, max_length=96)


class ClassificationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    document_type: str
    type_authority: str
    suggested_type: str | None
    classification_confidence: float | None
    classifier: str | None
    note: str = (
        "Facts already extracted under the previous type are unchanged. Re-analysis is a separate, "
        "explicit operation, and it retracts what the old type produced."
    )


class ProcessingResponse(BaseModel):
    """What a processing run did, per document, with nothing swallowed.

    ``unsupported`` and ``failed`` are lists rather than counts because a number tells an operator
    that something went wrong and not which thing, and both are ordinary outcomes rather than
    errors: the documents stay stored, provenanced and visible either way.
    """

    model_config = ConfigDict(frozen=True)

    project_id: str
    processed: list[str]
    already_processed: list[str]
    unsupported: list[dict[str, str]]
    failed: list[dict[str, str]]
    facts: int
    document_findings: int
    project_findings: int
    summary: str


class ProjectSummaryResponse(BaseModel):
    """A project in one object: where the evidence is, and what is waiting for a person.

    Counts, not analytics, and no scores of any kind. What ``documents_by_category`` *omits* is as
    informative as what it contains: a project with a BOQ and an RA bill but nothing under
    ``measurement`` cannot have over-certification checked, and the summary should make that
    visible without anyone having to explain it.
    """

    model_config = ConfigDict(frozen=True)

    project: ProjectResponse
    documents: int
    documents_by_status: dict[str, int]
    documents_by_category: dict[str, int]
    facts: int
    findings_by_outcome: dict[str, int]
    reviews_by_decision: dict[str, int]
    stale_reviews: int = Field(
        description=(
            "Reviews that no longer speak for their finding because the rule was revised or the "
            "outcome changed. Kept and counted, never hidden."
        )
    )
    findings_awaiting_review: int
    documents_unclassified: int
    classifications_disputed: int
    summary: str


class RelationshipResponse(BaseModel):
    """One stored relationship between two documents, and what justified it."""

    model_config = ConfigDict(frozen=True)

    relationship_id: str
    project_id: str
    from_document_id: str
    to_document_id: str
    relationship_type: str
    is_symmetric: bool
    established_by: str
    created_at: str

    @classmethod
    def from_row(cls, row: DocumentRelationship) -> RelationshipResponse:
        return cls(
            relationship_id=str(row.id),
            project_id=str(row.project_id),
            from_document_id=str(row.from_document_id),
            to_document_id=str(row.to_document_id),
            relationship_type=row.relationship_type.value,
            # Exposed so a client knows whether the absence of the reverse row means anything.
            is_symmetric=row.relationship_type.is_symmetric,
            established_by=row.established_by,
            created_at=row.created_at.isoformat(),
        )


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    returned: int
    projects: list[ProjectResponse]


class RelationshipListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    returned: int
    relationships: list[RelationshipResponse]


def settings_dependency() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dependency)]


def registry_dependency(settings: SettingsDep) -> SourceRegistry:
    """Provide the source registry, translating a bad registry into a 503.

    A malformed registry is a deployment fault, not a client error: the request was valid
    and the service is the thing that is broken. The settings are injected rather than read
    from the global so that this translation can be exercised in tests.
    """
    try:
        return get_registry(settings)
    except SourceRegistryError as error:
        logger.exception("registry.unavailable", error_type=type(error).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="source registry is unavailable or invalid",
        ) from error


RegistryDep = Annotated[SourceRegistry, Depends(registry_dependency)]


def probe_database() -> None:
    """Execute a trivial query to prove the database is reachable.

    Raises whatever the driver raises; the caller decides how to report it.
    """
    with session_scope() as session:
        session.execute(text("SELECT 1"))


def require_write_access(settings: SettingsDep) -> None:
    """Refuse every write when the environment is production. A stopgap, and labelled as one.

    This API has no authentication, no authorization and no tenancy, and project identifiers are
    global UUIDs with nothing scoping them to an owner. A production deployment that accepted writes
    would let any caller who can reach the port create projects and upload documents into anyone's.

    The check is on the environment rather than on a feature flag because a flag is something an
    operator can turn on without deciding anything. Turning this off requires deleting the
    dependency, which requires replacing it — which is the point.
    """
    if settings.environment is Environment.PRODUCTION:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "write endpoints are disabled in production: this API has no authentication or "
                "authorization, so it must not accept writes until it does"
            ),
        )


# One store per bucket, kept because building a boto3 client sets up connection pools and doing that
# per request would spend more time on TLS handshakes than on the upload. Keyed by bucket so a
# settings change is picked up rather than silently ignored.
_STORES: Final[dict[str, RawObjectStore]] = {}


def store_dependency(settings: SettingsDep) -> RawObjectStore:
    """The raw object store, which is where uploaded bytes actually go."""
    store = _STORES.get(settings.storage_bucket)
    if store is None:
        store = RawObjectStore(build_s3_client(settings), bucket=settings.storage_bucket)
        _STORES[settings.storage_bucket] = store
    return store


def database_probe_dependency() -> Callable[[], None]:
    """Provide the database liveness probe.

    Injected rather than called directly so readiness can be tested deterministically. The
    first version of this endpoint reached for the process-wide session, which made its
    unit test depend on whether a database happened to be running locally — it passed only
    because no database was installed, and started failing the moment one was.
    """
    return probe_database


DatabaseProbeDep = Annotated[Callable[[], None], Depends(database_probe_dependency)]
StoreDep = Annotated[RawObjectStore, Depends(store_dependency)]
WriteAccess = Depends(require_write_access)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


async def read_bounded(upload: UploadFile, *, limit: int) -> bytes:
    """Read an uploaded body, refusing to exceed ``limit``.

    Chunked and counted rather than ``await upload.read()``, because the unbounded form decides how
    much memory to allocate from a header a client controls. Starlette spools a large upload to
    disk, so this bound is about what *we* then hold, and it is enforced as the bytes arrive
    rather than after they have all been accepted.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"upload exceeds {limit} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure logging and report configuration once at startup."""
    settings = get_settings()
    configure_logging(settings)
    logger.info(
        "api.startup",
        version=__version__,
        environment=settings.environment.value,
        # Masked: the DSN contains a password.
        database=settings.safe_database_url(),
        storage_bucket=settings.storage_bucket,
    )
    yield
    logger.info("api.shutdown", version=__version__)


def create_app() -> FastAPI:
    """Build the ASGI application."""
    app = FastAPI(
        title="Aedifex Acquisition API",
        version=__version__,
        summary="Metadata for collected construction-project evidence.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Honour an inbound correlation id so a request can be traced across services,
        # but bound its length: it is attacker-controlled and ends up in every log line.
        inbound = request.headers.get(REQUEST_ID_HEADER)
        request_id = inbound[:64] if inbound else new_request_id()

        with bind_job_context(request_id=request_id):
            response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    def health(settings: SettingsDep) -> HealthResponse:
        """Liveness: the process is up. Checks no dependencies, so it never flaps."""
        return HealthResponse(version=__version__, environment=settings.environment.value)

    @app.get("/health/ready", response_model=ReadinessResponse, tags=["operations"])
    def readiness(
        response: Response, registry: RegistryDep, probe_database: DatabaseProbeDep
    ) -> ReadinessResponse:
        """Readiness: dependencies are reachable, so traffic may be routed here.

        Returns 503 with per-check detail when a dependency is down, rather than raising,
        so an operator can see *which* dependency failed from the response body alone.
        """
        checks: dict[str, str] = {"registry": f"ok ({len(registry)} sources)"}

        try:
            probe_database()
            checks["database"] = "ok"
        except Exception as error:
            # Only the exception type is exposed: a DSN or driver message could disclose
            # internal hostnames or credentials to an unauthenticated caller.
            checks["database"] = f"unavailable ({type(error).__name__})"
            logger.warning(
                "readiness.database_unavailable",
                error=str(error),
                error_type=type(error).__name__,
            )

        ready = all(value.startswith("ok") for value in checks.values())
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="ready" if ready else "not_ready", version=__version__, checks=checks
        )

    @app.get(f"{API_PREFIX}/sources", response_model=SourceListResponse, tags=["sources"])
    def list_sources(
        registry: RegistryDep,
        collectable_only: bool = False,
    ) -> SourceListResponse:
        """List registered sources, including those disabled pending terms review."""
        selected = registry.collectable() if collectable_only else registry.all()
        return SourceListResponse(
            total=len(registry),
            collectable=len(registry.collectable()),
            sources=[SourceResponse.from_definition(source) for source in selected],
        )

    @app.get(
        f"{API_PREFIX}/sources/{{source_id}}",
        response_model=SourceResponse,
        tags=["sources"],
        responses={404: {"description": "No such source"}},
    )
    def get_source(source_id: str, registry: RegistryDep) -> SourceResponse:
        """Fetch one source by id."""
        try:
            source = registry.get(source_id)
        except SourceRegistryError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown source {source_id!r}"
            ) from error
        return SourceResponse.from_definition(source)

    # -- the corpus catalog ------------------------------------------------
    #
    # A read model over documents, document_retrievals, and discovered_urls rather than a table of
    # its own. Every field below is already recorded somewhere; a catalog table would be a fourth
    # copy that can disagree with the other three.

    @app.get(f"{API_PREFIX}/documents", response_model=DocumentListResponse, tags=["corpus"])
    def list_documents(
        source_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DocumentListResponse:
        """The corpus, most recently retrieved first. Bounded: ``limit`` is clamped server-side."""
        with session_scope() as session:
            entries = catalog_entries(session, source_id=source_id, limit=limit, offset=offset)
            total = corpus_summary(session).documents
        return DocumentListResponse(
            total_in_corpus=total,
            returned=len(entries),
            documents=[DocumentResponse.from_entry(entry) for entry in entries],
        )

    @app.get(
        f"{API_PREFIX}/documents/{{document_id}}",
        response_model=DocumentResponse,
        tags=["corpus"],
        responses={404: {"description": "No such document"}},
    )
    def get_document(document_id: uuid.UUID) -> DocumentResponse:
        with session_scope() as session:
            entry = catalog_entry(session, document_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown document {document_id}"
            )
        return DocumentResponse.from_entry(entry)

    @app.get(
        f"{API_PREFIX}/documents/{{document_id}}/facts",
        response_model=FactListResponse,
        tags=["analysis"],
    )
    def get_document_facts(document_id: uuid.UUID) -> FactListResponse:
        """Every fact extracted from one document, newest extractor version included.

        Facts from superseded extractor versions are returned too. They are what older findings
        were computed from, so hiding them would make a stored verdict unexplainable.

        The same reasoning applies to a *retracted* fact — a value a later extractor version says
        the document never stated — but the consequence is different, and getting it wrong once was
        enough. A superseded fact has a successor that contradicts it; a retracted fact has nothing,
        so it reads as current unless something says otherwise. ``retracted`` is that something, and
        a client must not display a fact carrying it as a value the document states.
        """
        with session_scope() as session:
            rows = list(
                session.execute(
                    select(ExtractedFact)
                    # Eagerly, because the response is built after the session closes and a lazy
                    # load there raises DetachedInstanceError. Found by calling the endpoint rather
                    # than by reading it.
                    .options(selectinload(ExtractedFact.retraction))
                    .where(ExtractedFact.document_id == document_id)
                    .order_by(ExtractedFact.extractor_version, ExtractedFact.fact_type)
                ).scalars()
            )
        return FactListResponse(
            returned=len(rows), facts=[FactResponse.from_row(row) for row in rows]
        )

    @app.get(
        f"{API_PREFIX}/documents/{{document_id}}/findings",
        response_model=FindingListResponse,
        tags=["analysis"],
    )
    def get_document_findings(document_id: uuid.UUID) -> FindingListResponse:
        """Every rule verdict for one document, each with the facts it cited."""
        with session_scope() as session:
            rows = list(
                session.execute(
                    select(Finding)
                    .where(Finding.document_id == document_id)
                    .order_by(Finding.rule_id, Finding.rule_version)
                ).scalars()
            )
            facts = {
                row.id: row
                for row in session.execute(
                    select(ExtractedFact).where(ExtractedFact.document_id == document_id)
                ).scalars()
            }
            computed = {
                item.id: item
                for item in session.execute(
                    select(DerivedFact).where(DerivedFact.document_id == document_id)
                ).scalars()
            }
            payload = [FindingResponse.from_row(row, facts, computed) for row in rows]
        return FindingListResponse(returned=len(payload), findings=payload)

    @app.get(f"{API_PREFIX}/projects", response_model=ProjectListResponse, tags=["projects"])
    def list_projects(source_id: str | None = None, limit: int = 50) -> ProjectListResponse:
        """Projects, newest identifier first."""
        with session_scope() as session:
            query = select(Project).order_by(Project.external_ref).limit(limit)
            if source_id is not None:
                query = query.where(Project.source_id == source_id)
            rows = list(session.execute(query).scalars())
            counts: dict[uuid.UUID, int] = {}
            for project_id, count in session.execute(
                select(ProjectDocument.project_id, func.count()).group_by(
                    ProjectDocument.project_id
                )
            ).all():
                counts[project_id] = count
            payload = [ProjectResponse.from_row(row, counts.get(row.id, 0)) for row in rows]
        return ProjectListResponse(returned=len(payload), projects=payload)

    @app.post(
        f"{API_PREFIX}/projects",
        response_model=ProjectResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[WriteAccess],
        tags=["projects"],
        responses={
            404: {"description": "Unknown source"},
            409: {"description": "This source already has a project with that identifier"},
        },
    )
    def create_project_endpoint(
        body: ProjectCreateRequest, registry: RegistryDep
    ) -> ProjectResponse:
        """Declare a project. The first step of the workflow, and previously impossible.

        Until now a project could only come into existence by being *derived*: reconciliation found
        two documents quoting the same identifier and created the row. That works for a crawled
        corpus and not at all for a customer, who has seven documents for one building and no
        guarantee that any two of them repeat a reference number — which is exactly the case for the
        real building project this endpoint was built against.

        A project is useful before it holds anything. That is the point of creating it first: the
        documents are attached to something that already exists rather than being uploaded into a
        void and grouped afterwards.
        """
        try:
            source = registry.get(body.source_id)
        except SourceRegistryError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"unknown source {body.source_id!r}",
            ) from error
        with session_scope() as session:
            try:
                project = create_project(
                    session,
                    source=source,
                    name=body.name,
                    external_ref=body.external_identifier,
                    description=body.description,
                    created_by=body.created_by,
                )
            except IntakeError as error:
                code = (
                    status.HTTP_409_CONFLICT
                    if "already has a project" in str(error)
                    else status.HTTP_422_UNPROCESSABLE_CONTENT
                )
                raise HTTPException(status_code=code, detail=str(error)) from error
            return ProjectResponse.from_row(project, document_count=0)

    @app.get(
        f"{API_PREFIX}/projects/{{project_id}}",
        response_model=ProjectResponse,
        tags=["projects"],
        responses={404: {"description": "No such project"}},
    )
    def get_project(project_id: uuid.UUID) -> ProjectResponse:
        with session_scope() as session:
            row = session.get(Project, project_id)
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown project {project_id}"
                )
            count = session.execute(
                select(func.count())
                .select_from(ProjectDocument)
                .where(ProjectDocument.project_id == project_id)
            ).scalar_one()
            return ProjectResponse.from_row(row, count)

    @app.post(
        f"{API_PREFIX}/projects/{{project_id}}/documents",
        response_model=UploadResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[WriteAccess],
        tags=["projects"],
        responses={
            404: {"description": "No such project, or unknown source"},
            413: {"description": "Upload too large"},
            415: {"description": "No allowed format, or content contradicting its name"},
        },
    )
    async def upload_project_document(
        project_id: uuid.UUID,
        store: StoreDep,
        registry: RegistryDep,
        settings: SettingsDep,
        file: Annotated[UploadFile, File(description="The document itself.")],
        source_id: Annotated[str, Form(description="An approved manual-upload source.")],
        uploaded_by: Annotated[str, Form(description="Who is providing it. Provenance.")],
        document_type: Annotated[
            DocumentType | None,
            Form(description="What the uploader says this is. Omit if they do not know."),
        ] = None,
        note: Annotated[str | None, Form()] = None,
    ) -> UploadResponse:
        """Give a project a document: bytes in, immutable evidence out.

        .. code-block:: text

            bytes -> format check -> immutable artifact -> document -> upload provenance
                  -> project membership -> type suggestion

        Provenance is an *upload*, never a retrieval. There is no HTTP status, no requested URL and
        no response headers for a file someone handed over, and inventing them to reuse the crawl
        path would be fabricating provenance.

        Coherent or nothing: one transaction covers the document, its provenance and its membership,
        so none of the three can exist without the others. The single asymmetry is deliberate — the
        object may reach immutable storage and the transaction then roll back, leaving bytes nobody
        references. Storage is content-addressed, so the next upload of the same bytes finds and
        verifies them; a document row pointing at bytes that were never stored has no such recovery.

        Re-uploading the same document is safe and says so in the response rather than in an error:
        ``artifact_was_new`` and ``membership_was_new`` report exactly what happened.
        """
        try:
            source = registry.get(source_id)
        except SourceRegistryError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown source {source_id!r}"
            ) from error

        content = await read_bounded(file, limit=min(MAX_UPLOAD_BYTES, settings.max_download_bytes))
        with session_scope() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown project {project_id}"
                )
            try:
                outcome = attach_upload(
                    session,
                    store,
                    project=project,
                    source=source,
                    content=content,
                    filename=file.filename or "upload",
                    uploaded_by=uploaded_by,
                    declared_type=document_type,
                    declared_media_type=file.content_type,
                    note=note,
                )
            except IntakeError as error:
                # 415 for "we will not store bytes described like that", 422 for a request that is
                # malformed in some other way. Both are the client's to fix.
                code = (
                    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
                    if "format" in str(error) or "content" in str(error)
                    else status.HTTP_422_UNPROCESSABLE_CONTENT
                )
                raise HTTPException(status_code=code, detail=str(error)) from error
            except AedifexError as error:
                # A source that is enabled for crawling but not for upload lands here, and it is a
                # refusal rather than a fault: the terms reviewed for fetching say nothing about
                # someone handing us a file.
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
                ) from error

            entry = next(
                (
                    candidate
                    for candidate in project_inventory(session, project_id)
                    if candidate.document_id == outcome.document.id
                ),
                None,
            )
            if entry is None:  # pragma: no cover - the row was just written in this transaction
                raise HTTPException(status_code=500, detail="attached document not found")
            return UploadResponse(
                project_id=str(project_id),
                document=ProjectDocumentResponse.from_entry(entry),
                artifact_was_new=outcome.artifact_was_new,
                membership_was_new=outcome.membership_was_new,
                suggested_type=(
                    None if outcome.suggestion is None else outcome.suggestion.document_type.value
                ),
                suggestion_matched=(
                    None if outcome.suggestion is None else outcome.suggestion.matched
                ),
            )

    @app.get(
        f"{API_PREFIX}/projects/{{project_id}}/documents",
        response_model=ProjectDocumentListResponse,
        tags=["projects"],
    )
    def get_project_documents(project_id: uuid.UUID) -> ProjectDocumentListResponse:
        """The project's document inventory: the beginning of the workspace read model.

        Reads memberships, not retrievals. This endpoint used to describe each document through the
        corpus catalog, which inner-joins ``document_retrievals`` — so every *uploaded* document was
        silently dropped from the list. On the corpus this was written against that was 41 of 45
        documents, while ``/v1/corpus`` reported all 45 as held. A product surface cannot be built
        on a query that hides the documents customers give it.
        """
        with session_scope() as session:
            entries = project_inventory(session, project_id)
        return ProjectDocumentListResponse(
            project_id=str(project_id),
            returned=len(entries),
            documents=[ProjectDocumentResponse.from_entry(entry) for entry in entries],
        )

    @app.post(
        f"{API_PREFIX}/projects/{{project_id}}/process",
        response_model=ProcessingResponse,
        dependencies=[WriteAccess],
        tags=["projects"],
        responses={404: {"description": "No such project"}},
    )
    def process_project_endpoint(
        project_id: uuid.UUID, store: StoreDep, reprocess: bool = False
    ) -> ProcessingResponse:
        """Run the existing pipeline over the project's documents, then over the project.

        **Not a second pipeline.** Each document goes through the same ``analyse_document`` or
        ``analyse_spreadsheet`` the CLI calls, and the project through the same ``analyse_project``.
        This endpoint picks the capability each format needs and reports what happened.

        **Synchronous, and the honesty is the feature.** There is no job queue in this deployment,
        and inventing one for a vertical slice would be the wrong order of work. A large project
        takes tens of seconds, so a client should expect to wait — which is preferable to returning
        ``202 Accepted`` and a status field that lies about work no worker is doing. The cost is
        recorded here rather than hidden: this is the endpoint a queue replaces first.

        One document failing costs the others nothing. Failures and unreadable formats come back in
        the response, and both documents stay stored, provenanced and visible.
        """
        with session_scope() as session:
            try:
                report = process_project(session, store, project_id, reprocess=reprocess)
            except IntakeError as error:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
                ) from error
            return ProcessingResponse(
                project_id=str(project_id),
                processed=[str(item) for item in report.processed],
                already_processed=[str(item) for item in report.already_processed],
                unsupported=[
                    {"document_id": str(item), "reason": reason}
                    for item, reason in report.unsupported
                ],
                failed=[
                    {"document_id": str(item), "reason": reason} for item, reason in report.failed
                ],
                facts=report.facts,
                document_findings=report.findings,
                project_findings=report.project_findings,
                summary=report.describe(),
            )

    @app.get(
        f"{API_PREFIX}/projects/{{project_id}}/summary",
        response_model=ProjectSummaryResponse,
        tags=["projects"],
        responses={404: {"description": "No such project"}},
    )
    def get_project_summary(project_id: uuid.UUID) -> ProjectSummaryResponse:
        """Orientation for a reviewer opening a project: what is here, and what needs me.

        One call, because the alternative is four and they can disagree. Built on the same inventory
        the document list serves, so the counts and the rows cannot drift apart.
        """
        with session_scope() as session:
            try:
                summary = project_summary(session, project_id)
            except IntakeError as error:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
                ) from error
            return ProjectSummaryResponse(
                project=ProjectResponse.from_row(summary.project, summary.documents),
                documents=summary.documents,
                documents_by_status={
                    key.value: value for key, value in sorted(summary.by_status.items())
                },
                documents_by_category={
                    key.value: value for key, value in sorted(summary.by_category.items())
                },
                facts=summary.facts,
                findings_by_outcome=dict(sorted(summary.findings_by_outcome.items())),
                reviews_by_decision=dict(sorted(summary.reviews_by_decision.items())),
                stale_reviews=summary.stale_reviews,
                findings_awaiting_review=summary.review_needed,
                documents_unclassified=summary.unclassified,
                classifications_disputed=summary.disputed_classifications,
                summary=summary.describe(),
            )

    @app.get(
        f"{API_PREFIX}/projects/{{project_id}}/facts",
        response_model=FactListResponse,
        tags=["projects"],
    )
    def get_project_facts(project_id: uuid.UUID) -> FactListResponse:
        """Every fact from every document of one project — the input to its cross-document rules."""
        with session_scope() as session:
            member = (
                select(ProjectDocument.document_id)
                .where(ProjectDocument.project_id == project_id)
                .scalar_subquery()
            )
            rows = list(
                session.execute(
                    select(ExtractedFact)
                    .where(ExtractedFact.document_id.in_(member))
                    .order_by(ExtractedFact.fact_type, ExtractedFact.document_id)
                ).scalars()
            )
        return FactListResponse(
            returned=len(rows), facts=[FactResponse.from_row(row) for row in rows]
        )

    @app.get(
        f"{API_PREFIX}/projects/{{project_id}}/findings",
        response_model=FindingListResponse,
        tags=["projects"],
    )
    def get_project_findings(project_id: uuid.UUID) -> FindingListResponse:
        """Cross-document findings for one project, each citing facts from several documents."""
        with session_scope() as session:
            rows = list(
                session.execute(
                    select(Finding)
                    .where(Finding.project_id == project_id)
                    .order_by(Finding.rule_id, Finding.rule_version)
                ).scalars()
            )
            member = (
                select(ProjectDocument.document_id)
                .where(ProjectDocument.project_id == project_id)
                .scalar_subquery()
            )
            facts = {
                row.id: row
                for row in session.execute(
                    select(ExtractedFact).where(ExtractedFact.document_id.in_(member))
                ).scalars()
            }
            computed = {
                item.id: item
                for item in session.execute(
                    select(DerivedFact).where(DerivedFact.document_id.in_(member))
                ).scalars()
            }
            payload = [FindingResponse.from_row(row, facts, computed) for row in rows]
        return FindingListResponse(returned=len(payload), findings=payload)

    @app.post(
        f"{API_PREFIX}/findings/{{finding_id}}/reviews",
        response_model=ReviewResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[WriteAccess],
        tags=["review"],
    )
    def create_finding_review(finding_id: uuid.UUID, body: ReviewRequest) -> ReviewResponse:
        """Record a human decision about a finding. The last stage of the pipeline.

        The first write endpoint in this API, and the only place a person's judgement enters the
        system. Everything upstream is deterministic; this is where that stops, which is why the
        record is attributed, reasoned and append-only.

        Appends rather than replaces: a second reviewer disagreeing with the first is what an audit
        trail is for. ``201`` on every successful call, including a re-review.
        """
        with session_scope() as session:
            try:
                review = record_review(
                    session,
                    finding_id,
                    decision=body.decision,
                    note=body.note,
                    reviewer=body.reviewer,
                )
            except ReviewError as error:
                # 404 for an absent finding, 422 for a bad decision — but the service raises one
                # type, so the message decides. Kept simple deliberately.
                code = (
                    status.HTTP_404_NOT_FOUND
                    if "no finding" in str(error)
                    else status.HTTP_422_UNPROCESSABLE_CONTENT
                )
                raise HTTPException(status_code=code, detail=str(error)) from error
            return ReviewResponse.from_row(review, review.finding)

    @app.get(
        f"{API_PREFIX}/findings/{{finding_id}}/reviews",
        tags=["review"],
    )
    def get_finding_reviews(finding_id: uuid.UUID) -> dict[str, object]:
        """Every decision recorded against one finding, oldest first, with staleness marked."""
        with session_scope() as session:
            finding = session.get(Finding, finding_id)
            if finding is None:
                raise HTTPException(status_code=404, detail=f"no finding {finding_id}")
            payload = [ReviewResponse.from_row(row, finding) for row in finding.reviews]
            current = finding.current_review
            state = "unreviewed" if current is None else current.decision
        return {
            "finding_id": str(finding_id),
            "review_state": state,
            "returned": len(payload),
            "reviews": payload,
        }

    @app.post(
        f"{API_PREFIX}/documents/{{document_id}}/classification",
        response_model=ClassificationResponse,
        dependencies=[WriteAccess],
        tags=["analysis"],
        responses={404: {"description": "No such document"}},
    )
    def confirm_classification(
        document_id: uuid.UUID, body: ClassificationRequest
    ) -> ClassificationResponse:
        """Record that a person decided what a document is.

        The only path by which a proposal becomes a decision, and it requires a name. The classifier
        writes to ``suggested_document_type`` and can never write here, because ``document_type``
        decides whether the extractor treats a quoted amount as a fact about this document — and a
        role that looked inferable has already produced five false facts from real documents.

        The suggestion is left exactly as it was, including when the person disagreed with it. "The
        classifier said corrigendum and a human said specification" is worth more than either
        statement alone, and it is the only feedback this classifier will ever get.
        """
        with session_scope() as session:
            try:
                document = confirm_document_type(
                    session,
                    document_id,
                    document_type=body.document_type,
                    confirmed_by=body.confirmed_by,
                )
            except IntakeError as error:
                code = (
                    status.HTTP_404_NOT_FOUND
                    if "no document" in str(error)
                    else status.HTTP_422_UNPROCESSABLE_CONTENT
                )
                raise HTTPException(status_code=code, detail=str(error)) from error
            return ClassificationResponse(
                document_id=str(document.id),
                document_type=document.document_type.value,
                type_authority=document.type_authority.value,
                suggested_type=(
                    None
                    if document.suggested_document_type is None
                    else document.suggested_document_type.value
                ),
                classification_confidence=document.classification_confidence,
                classifier=document.classifier_version,
            )

    @app.get(
        f"{API_PREFIX}/projects/{{project_id}}/relationships",
        response_model=RelationshipListResponse,
        tags=["projects"],
    )
    def get_project_relationships(project_id: uuid.UUID) -> RelationshipListResponse:
        """How the project's documents relate to one another, and what established each link."""
        with session_scope() as session:
            rows = list(
                session.execute(
                    select(DocumentRelationship)
                    .where(DocumentRelationship.project_id == project_id)
                    .order_by(DocumentRelationship.created_at)
                ).scalars()
            )
            payload = [RelationshipResponse.from_row(row) for row in rows]
        return RelationshipListResponse(returned=len(payload), relationships=payload)

    @app.get(f"{API_PREFIX}/projects/{{project_id}}/work-items", tags=["projects"])
    def get_project_work_items(project_id: uuid.UUID) -> dict[str, object]:
        """Each item of work, the facts about it from every document, and its findings.

        The payment-reconciliation view: one entry per item, carrying what was contracted, what was
        measured, and what is claimed, each with the cell it came from. Derived values are listed
        separately from stated ones so a reader can tell which numbers a document asserts.
        """
        with session_scope() as session:
            items = list(
                session.execute(
                    select(WorkItem)
                    .where(WorkItem.project_id == project_id)
                    .order_by(WorkItem.normalised_identifier)
                ).scalars()
            )
            payload: list[dict[str, object]] = []
            for item in items:
                facts = list(
                    session.execute(
                        select(ExtractedFact).where(ExtractedFact.work_item_id == item.id)
                    ).scalars()
                )
                derived = list(
                    session.execute(
                        select(DerivedFact).where(
                            DerivedFact.project_id == project_id,
                            DerivedFact.fact_type.like(f"{item.normalised_identifier}:%"),
                        )
                    ).scalars()
                )
                findings = list(
                    session.execute(
                        select(Finding)
                        .where(Finding.work_item_id == item.id)
                        .order_by(Finding.rule_id)
                    ).scalars()
                )
                payload.append(
                    {
                        "work_item_id": str(item.id),
                        "item_identifier": item.item_identifier,
                        "description": item.description,
                        "unit": item.unit,
                        "matched_by": item.matched_by,
                        "facts": [FactResponse.from_row(fact) for fact in facts],
                        "derived_facts": [
                            {
                                "fact_type": row.fact_type.split(":", 1)[-1],
                                "value": (
                                    None if row.numeric_value is None else str(row.numeric_value)
                                ),
                                "unit": row.unit,
                                "currency": row.currency,
                                "expression": row.expression,
                                "calculation": f"{row.calculation} v{row.calculation_version}",
                            }
                            for row in sorted(derived, key=lambda r: r.fact_type)
                        ],
                        "findings": [
                            {
                                "rule_id": row.rule_id,
                                "outcome": row.outcome,
                                "expected": row.expected,
                                "observed": row.observed,
                                "summary": row.summary,
                                "detail": dict(row.detail),
                            }
                            for row in findings
                        ],
                    }
                )
        return {"returned": len(payload), "work_items": payload}

    @app.get(f"{API_PREFIX}/knowledge", tags=["knowledge"])
    def get_knowledge() -> dict[str, object]:
        """What Aedifex knows how to talk about: fact, relationship, rule and finding types.

        Metadata, served from the registry rather than the database. It describes the vocabulary
        the code implements, so it reads the same on an empty deployment as on a full one.
        """
        return {
            "fact_types": [
                {
                    "fact_type": info.fact_type,
                    "kind": info.kind.value,
                    "origin": info.origin.value,
                    "description": info.description,
                    "produced_by": info.produced_by,
                    "inputs": list(info.inputs),
                }
                for info in FACT_TYPES
            ],
            "relationship_types": [
                {
                    "relationship_type": info.relationship_type.value,
                    "description": info.description,
                    "derivable": info.derivable,
                    "is_symmetric": info.relationship_type.is_symmetric,
                }
                for info in RELATIONSHIP_TYPES
            ],
            "rule_types": [
                {
                    "rule_id": info.rule_id,
                    "scope": info.scope,
                    "description": info.description,
                    "consumes": list(info.consumes),
                }
                for info in RULE_TYPES
            ],
            "document_version_states": [
                {
                    "state": info.state.value,
                    "description": info.description,
                    "participates_in_reconciliation": info.participates_in_reconciliation,
                }
                for info in DOCUMENT_VERSION_STATES
            ],
            "finding_outcomes": [
                {"outcome": info.outcome.value, "description": info.description}
                for info in FINDING_OUTCOMES
            ],
        }

    @app.get(f"{API_PREFIX}/corpus", response_model=CorpusSummaryResponse, tags=["corpus"])
    def get_corpus_summary() -> CorpusSummaryResponse:
        """What the corpus holds, and how much work the frontier still owes."""
        with session_scope() as session:
            summary = corpus_summary(session)
            depth = dict(queue_depth_by_source(session))
        return CorpusSummaryResponse.from_summary(summary, depth)

    @app.get(f"{API_PREFIX}/crawl-runs", response_model=CrawlRunListResponse, tags=["operations"])
    def list_crawl_runs(source_id: str | None = None, limit: int = 20) -> CrawlRunListResponse:
        """Recent runs, newest first: the operational history of the crawler (FR-078)."""
        with session_scope() as session:
            runs = crawl_runs(session, source_id=source_id, limit=limit)
        return CrawlRunListResponse(
            returned=len(runs), runs=[CrawlRunResponse.from_run(run) for run in runs]
        )

    return app


app = create_app()
