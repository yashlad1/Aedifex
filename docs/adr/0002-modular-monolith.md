# 2. Modular monolith, not microservices

Date: 2026-08-17

## Status

Accepted

## Context

The system has visibly distinct concerns — acquisition, document intelligence, evidence
graph, audit rules, risk scoring — which invites splitting them into services early. The
domain boundaries are not yet understood: nobody has built the evidence graph or the rules
engine yet, so any service boundary drawn now is a guess.

## Decision

One deployable application with strict internal module boundaries, enforced by review and
documented in `ARCHITECTURE.md`:

```
domain/          depends on nothing
acquisition/     depends on domain
infrastructure/  adapters only, no business rules
apps/            entry points only, no logic
```

Extraction into a separate service happens only when a concrete pressure demands it — a
genuinely different scaling profile, an isolation requirement, or independent deploy cadence —
and by then the boundary will be known rather than guessed.

## Alternatives considered

**Microservices now.** Adds network calls, partial failure, distributed tracing,
schema-versioned contracts, and per-service deployment before there is any code to justify it.
Every one of those is a tax paid on every future change.

**Single package, no boundaries.** Fastest initially; produces a layer cake where the rules
engine imports the HTTP client and nothing can be tested in isolation.

**Separate worker service immediately.** Deferred rather than rejected. The worker process
arrives in Phase 1 with the download queue; it shares this codebase and its module boundaries.

## Consequences

- Fast local development: the entire test suite runs in under a second with no infrastructure.
- Boundary violations are possible and must be caught in review, since the language does not
  enforce them.
- Horizontal scaling initially means running more copies of the whole application. Acceptable:
  the workload is document processing, which parallelises by document.
