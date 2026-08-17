# 7. Defer queue infrastructure until there are tasks

Date: 2026-08-17

## Status

Accepted

## Context

The target architecture is clearly asynchronous: crawl → queue → download workers → processing
queue → OCR workers. The recommended stack names Celery and Redis, and the local development
stack was specified to include Redis and a worker container.

Phase 0 has no asynchronous tasks. Adding Redis and Celery now would mean a broker, a worker
container, task serialisation, result backend configuration, and a second failure mode in local
setup — with zero tasks to run.

## Decision

Redis and Celery are not added in Phase 0. The compose stack contains PostgreSQL, MinIO, and
the API. Queue infrastructure lands in Phase 1, in the same change as the download queue that
uses it.

Nothing in the current design blocks this: the `crawl_jobs` table already holds the resumable
checkpoint, and `discovered_urls` already holds per-URL state and retry bookkeeping, which is
the durable state a queue would need.

## Alternatives considered

**Add Redis and Celery now as scaffolding.** Matches the target architecture sooner, but
unused infrastructure has to be maintained, upgraded, and vulnerability-scanned while providing
nothing. It also tends to get configured wrong precisely because nothing exercises it.

**Commit to a durable workflow engine now** (Temporal, Prefect). A larger commitment than
Celery, justified if workflows become long-lived and stateful — which is plausible for
multi-stage document processing. Deferred until the actual shape of the work is known;
revisiting is an ADR at that point.

**Use PostgreSQL as the queue** (`SELECT … FOR UPDATE SKIP LOCKED`). Genuinely attractive: one
fewer dependency, transactional with the metadata it updates. A real candidate for Phase 1,
which is another reason not to commit to Redis prematurely.

## Consequences

- Local setup stays simple: two infrastructure containers.
- `docker-compose.yml` does not match the eventual architecture. Noted in a comment there.
- The Phase 1 choice between Celery/Redis and a PostgreSQL-backed queue stays open, and will be
  made with knowledge of the workload.
