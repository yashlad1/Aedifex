"""Structured logging.

Every log line is a JSON object in deployed environments and human-readable text locally.
The pipeline is asynchronous and multi-stage, so free-text logs are close to useless: the
only way to answer "what happened to this document?" is to filter on identifiers. This
module therefore standardises the context keys from the observability requirements
(``request_id``, ``document_id``, ``source_id``, ``job_id``, ``stage``, ``duration_ms``,
``status``, ``error``) and provides a context manager that binds them for the duration of a
unit of work.

Secrets are never logged. Because configuration secrets are :class:`~pydantic.SecretStr`,
accidentally interpolating one yields ``**********`` rather than the value.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

import structlog
from structlog.contextvars import bind_contextvars, reset_contextvars
from structlog.typing import EventDict, Processor, WrappedLogger

from aedifex.config import LogFormat, Settings, get_settings

__all__ = [
    "PIPELINE_CONTEXT_KEYS",
    "bind_job_context",
    "configure_logging",
    "get_logger",
    "log_stage",
    "new_request_id",
]

# The canonical context keys. Documented here so dashboards and log queries have a
# contract, and so reviewers notice when a new cross-cutting key is introduced.
PIPELINE_CONTEXT_KEYS: Final[tuple[str, ...]] = (
    "request_id",
    "job_id",
    "source_id",
    "document_id",
    "project_id",
    "stage",
    "status",
    "duration_ms",
    "error_type",
    "error",
)

_configured = False


def new_request_id() -> str:
    """Return a fresh correlation id for an inbound request or job run."""
    return uuid.uuid4().hex


def _add_service_metadata(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Stamp every line with the software version, for reproducibility of findings."""
    from aedifex import __version__

    event_dict.setdefault("service", "aedifex")
    event_dict.setdefault("version", __version__)
    return event_dict


def configure_logging(settings: Settings | None = None, *, force: bool = False) -> None:
    """Configure structlog and the standard library root logger.

    Idempotent: repeated calls are ignored unless ``force`` is set, so importing a module
    that logs cannot silently reconfigure a running process.

    Args:
        settings: Configuration to use; falls back to :func:`get_settings`.
        force: Reconfigure even if logging was already set up. Intended for tests.
    """
    global _configured
    if _configured and not force:
        return

    resolved = settings or get_settings()
    level = logging.getLevelNamesMapping()[resolved.log_level]

    # Processors applied to structlog calls and to foreign stdlib records alike, so a log
    # line from SQLAlchemy or uvicorn carries the same shape as one of ours.
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_service_metadata,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: Processor
    if resolved.log_format is LogFormat.JSON:
        renderer = structlog.processors.JSONRenderer(sort_keys=True)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        # wrap_for_formatter hands the event dict to ProcessorFormatter below, which is what
        # lets one renderer serve both structlog and stdlib records.
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # Must precede the renderer so a traceback becomes a string field rather than an
            # unserialisable object.
            structlog.processors.format_exc_info,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    # Replace existing handlers rather than adding to them: repeated configuration would
    # otherwise duplicate every line.
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Configures logging on first use if needed."""
    if not _configured:
        configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


@contextmanager
def bind_job_context(**context: Any) -> Iterator[None]:
    """Bind context variables for the enclosing block, restoring them on exit.

    Keys outside :data:`PIPELINE_CONTEXT_KEYS` are allowed but should be rare; the shared
    keys are what makes cross-stage tracing possible.
    """
    tokens = bind_contextvars(**context)
    try:
        yield
    finally:
        reset_contextvars(**tokens)


@contextmanager
def log_stage(
    stage: str,
    *,
    logger: structlog.stdlib.BoundLogger | None = None,
    **context: Any,
) -> Iterator[None]:
    """Log the start, duration, and outcome of a pipeline stage.

    Emits ``<stage>.started`` and then either ``<stage>.completed`` with ``duration_ms``
    or ``<stage>.failed`` with the exception type and message. The exception is always
    re-raised: this records failures, it never suppresses them.
    """
    bound = logger or get_logger(__name__)
    started = time.perf_counter()
    bound.info(f"{stage}.started", stage=stage, status="started", **context)
    try:
        yield
    except Exception as error:
        bound.error(
            f"{stage}.failed",
            stage=stage,
            status="failed",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            error_type=type(error).__name__,
            error=str(error),
            exc_info=True,
            **context,
        )
        raise
    else:
        bound.info(
            f"{stage}.completed",
            stage=stage,
            status="completed",
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            **context,
        )
