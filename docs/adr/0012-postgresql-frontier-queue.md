# 12. The frontier table is the queue

Date: 2026-08-18

## Status

Accepted. Supersedes the deferral in [ADR 0007](0007-defer-queue-infrastructure.md).

## Context

ADR 0007 declined to add Redis and Celery while there were no tasks to run, and left the Phase 1
choice open, noting that `SELECT … FOR UPDATE SKIP LOCKED` was "a real candidate". There are now
tasks: a crawl run discovers URLs and has to work through them, survive interruption, and not
duplicate work.

The durable state a queue needs was already in `discovered_urls` before this decision was taken —
per-URL state, an attempt counter, a job id — because the frontier and the queue are the same list
seen from two angles.

## Decision

`discovered_urls` is the queue. Claims use `FOR UPDATE SKIP LOCKED`; a claim writes a **lease**
(owner plus expiry) rather than changing the document state.

**Delivery is at-least-once, made effectively-once by content addressing.** A worker that dies after
fetching but before committing loses its lease, the URL is claimed again, and the second attempt
re-downloads the same bytes — the digest is identical, so the object store reports the key already
present and the document row is found rather than inserted. A second *retrieval* row is appended,
which is correct: it happened.

| Requirement (rule 46) | How |
| --- | --- |
| Transactional consistency | The claim, the acquisition, and the run's counters are one transaction |
| Visibility timeout | `lease_expires_at`; `reclaim_expired` recovers and charges an attempt |
| Retries | `FAILED` re-enters the pipeline (FR-053); `next_attempt_after` defers |
| Dead-letter | `dead_lettered_at` after `max_attempts` (rule 47) |
| Backpressure | Discovery and acquisition are the same loop, so ingestion cannot outrun it |
| Throughput | Far beyond what politeness permits: 10 requests/minute per source |
| Operational complexity | One dependency we already run, back up, and monitor |

A lease rather than a state change because the acquirer owns the document state machine, and two
things moving a row through it means two places to get it wrong. "A worker is looking at this until
then" is a different fact from "this URL is being downloaded", and the difference is the only thing
that makes a crashed worker detectable.

Dead-lettering is a timestamp column, not a new `DocumentState`. That enum describes where a
*document* is in its lifecycle; queue exhaustion is a property of delivery. Putting it there would
spread queue vocabulary through the state machine and every exhaustive test over it, for a fact only
the claim query reads.

## Alternatives considered

**Redis and Celery.** A broker, a worker container, task serialisation, and a result backend, plus a
second store that can disagree with the database about what has been done. The failure mode is
specific and bad: a task acknowledged in Redis whose transaction rolled back is work that is
recorded as complete and was not.

**A durable workflow engine** (Temporal, Prefect). Justified when workflows are long-lived and
stateful, which multi-stage document processing may become. A crawl of one source is not that yet.
Revisit when OCR and extraction stages exist — this decision does not block it, because the frontier
remains the source of truth either way.

**`SKIP LOCKED` held across the download.** Simpler — no lease column — but the lock lives only as
long as the transaction, so a transaction would have to stay open across a network fetch of an
arbitrarily large file. That holds a connection for minutes and makes a slow portal a database
problem.

## Consequences

- **Operational.** No new infrastructure. Queue depth is a `SELECT`, and the backlog is inspectable
  with SQL during an incident rather than through a broker's CLI.
- **Security.** No new listening service and no new credentials. A malformed URL is refused at
  enqueue rather than stored and retried forever.
- **Migration.** Additive and reversible (`34a42436bb53`). One behavioural change: the frontier is
  now keyed on the *canonical* URL, so a pre-existing row whose URL was not canonical may be
  enqueued once more. Nothing has been crawled, so the affected rows are development-only.
- **Scaling limit, stated.** Claim contention through one table becomes the bottleneck somewhere
  around thousands of claims per second. Per-source politeness caps us at ten requests per *minute*,
  so the limit is roughly five orders of magnitude away.
