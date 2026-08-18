"""FastAPI application exposing acquisition metadata.

Read-only by design at this phase. Crawling is triggered by workers, not by HTTP requests:
a long-running crawl behind a request handler would tie up an API worker and make timeouts
meaningless. The write endpoints in the API design (``POST /sources/{id}/crawl``) arrive in
Phase 1 together with the job queue that makes them return immediately.

Every response carries an ``X-Request-ID``, and that same id is bound into the logging
context for the duration of the request, so a log query on one identifier returns the whole
story of a request.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Final

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

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
from aedifex.config import Settings, get_settings
from aedifex.errors import SourceRegistryError
from aedifex.infrastructure.database.session import session_scope
from aedifex.infrastructure.observability.logging import (
    bind_job_context,
    configure_logging,
    get_logger,
    new_request_id,
)

API_PREFIX: Final[str] = "/v1"
REQUEST_ID_HEADER: Final[str] = "X-Request-ID"

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


def database_probe_dependency() -> Callable[[], None]:
    """Provide the database liveness probe.

    Injected rather than called directly so readiness can be tested deterministically. The
    first version of this endpoint reached for the process-wide session, which made its
    unit test depend on whether a database happened to be running locally — it passed only
    because no database was installed, and started failing the moment one was.
    """
    return probe_database


DatabaseProbeDep = Annotated[Callable[[], None], Depends(database_probe_dependency)]


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


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
