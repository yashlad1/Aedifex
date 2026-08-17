# 5. Synchronous SQLAlchemy

Date: 2026-08-17

## Status

Accepted

## Context

FastAPI supports async, and async SQLAlchemy is available. The instinct is to use both. But the
API's work is thin metadata reads and writes; the expensive work — downloading, OCR, parsing —
belongs in workers, not in request handlers.

## Decision

Synchronous SQLAlchemy 2.0, with typed `Mapped[...]` annotations. FastAPI runs sync
dependencies in a threadpool. A connection-level statement timeout is set so an unbounded query
cannot hang a worker.

## Alternatives considered

**Async SQLAlchemy.** Correct choice when a request makes many concurrent I/O calls. Here it
would add async fixtures throughout tests, a second set of driver semantics, and a real risk of
accidentally blocking the event loop in a library that is not async-aware — for queries that
return in single-digit milliseconds.

**Raw SQL with psycopg.** Maximum control, but hand-written SQL for every query plus no
declarative schema for Alembic to diff against.

## Consequences

- Simpler tests: no async fixtures, no event-loop management.
- Alembic autogenerate works against the same models, which is what makes `alembic check` a
  meaningful CI gate.
- Concurrency is bounded by the threadpool. Acceptable for metadata endpoints; revisit if the
  API ever becomes I/O-fan-out heavy.
- Revisiting means changing the session layer only, since no business logic performs I/O.
