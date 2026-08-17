"""Database engine and session management.

Synchronous SQLAlchemy is used deliberately. The API is thin metadata reads and writes, and
the heavy work (downloading, OCR) belongs in workers rather than in request handlers, so the
complexity of an async ORM buys nothing yet. FastAPI runs sync dependencies in a threadpool.
See ``docs/adr/0005-synchronous-sqlalchemy.md``.

A statement timeout is set at connection level: an unbounded query against a corpus table is
how a metadata store takes down an API.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from aedifex.config import Settings, get_settings

__all__ = ["build_engine", "get_engine", "get_sessionmaker", "session_scope"]


def build_engine(settings: Settings) -> Engine:
    """Create a new engine for ``settings``. Callers own its lifecycle."""
    return create_engine(
        str(settings.database_url),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_size,
        # Recycle before typical proxy/idle timeouts, and verify liveness on checkout so a
        # connection killed by a failover surfaces as a retryable error, not a hang.
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "options": f"-c statement_timeout={settings.database_statement_timeout_seconds * 1000}"
        },
        echo=settings.debug,
        future=True,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide engine, created once."""
    return build_engine(get_settings())


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    """Return the process-wide session factory."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session, committing on success and rolling back on error.

    The exception is always re-raised; this manages the transaction boundary and never
    converts a failure into a silent success.
    """
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
