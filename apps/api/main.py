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

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Final

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from aedifex import __version__
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

    return app


app = create_app()
