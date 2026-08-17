# Architecture

## The problem this shape serves

The value of the system is not extracting fields from one document. It is deciding whether
evidence spread across many documents is consistent, complete, and contractually supported.
That single fact drives every structural decision below:

- Documents cannot stay isolated files, so there is an evidence graph.
- A finding must be defensible, so every extracted fact keeps its provenance.
- A finding must be reproducible, so software version, prompt version, and rule version are
  recorded alongside results.
- Arithmetic must never be probabilistic, so verification is deterministic code and language
  models are confined to interpretation.

> **LLMs interpret evidence. Deterministic code verifies evidence.**

## Layers

```
Project data room  (contracts, BOQs, POs, invoices, challans, GRNs, MTCs, IRs, COs)
        │
        ▼
Acquisition            crawl → download → validate → hash → deduplicate → store
        │
        ▼
Document intelligence  parse → OCR → classify → extract (typed, with provenance)
        │
        ▼
Structured evidence    canonical entities: Vendor, PO, POLine, Invoice, GRN, Certificate…
        │
        ▼
Evidence graph         invoice →references→ PO, GRN →confirms→ challan, …
        │
        ▼
Deterministic rules    versioned, testable, explainable comparisons
        │
        ▼
Risk engine            findings → weighted, explainable score
        │
        ▼
Human auditor          PASS / REVIEW / FAIL, with clickable evidence
```

Data flows one way. A lower layer never imports from a higher one.

## Module boundaries

```
src/aedifex/
  config.py          typed settings; the only reader of the environment
  errors.py          exception hierarchy
  domain/            shared vocabulary. Imports nothing but errors.
  acquisition/       registry, content validation; later crawlers and downloaders
  infrastructure/    database, storage, observability adapters
```

Rules, enforced in review:

1. **`domain/` depends on nothing.** It is the vocabulary every other layer speaks.
2. **Only `config.py` reads the environment.** Nothing else touches `os.environ`.
3. **`infrastructure/` is adapters, not decisions.** No business rule lives there.
4. **Higher layers depend on lower layers, never the reverse.**
5. **`apps/` is entry points only.** Wiring and transport; no logic.

## What exists today

Phase 0 is complete. Implemented and tested:

| Component | Where |
| --- | --- |
| Typed configuration, production hardening | [config.py](src/aedifex/config.py) |
| Document taxonomy, lifecycle state machine | [domain/documents.py](src/aedifex/domain/documents.py) |
| Format mapping, magic-byte sniffing | [domain/files.py](src/aedifex/domain/files.py) |
| Content identity, safety validation | [acquisition/content.py](src/aedifex/acquisition/content.py) |
| Source registry schema and loader | [acquisition/registry/](src/aedifex/acquisition/registry/) |
| ORM models, session management | [infrastructure/database/](src/aedifex/infrastructure/database/) |
| Immutable storage key layout | [infrastructure/storage/keys.py](src/aedifex/infrastructure/storage/keys.py) |
| Structured logging | [infrastructure/observability/logging.py](src/aedifex/infrastructure/observability/logging.py) |
| Read-only metadata API | [apps/api/main.py](apps/api/main.py) |

Not yet built: crawlers, downloaders, parsing, OCR, classification, synthetic generation,
the evidence graph, the rules engine, and the risk engine. Directories for those are created
when their first real code lands, rather than kept as empty scaffolding.

## Key decisions and their reasons

Recorded as ADRs in [docs/adr/](docs/adr/). The load-bearing ones:

**Modular monolith, not microservices** ([0002](docs/adr/0002-modular-monolith.md)).
One deployable, strict internal boundaries. Boundaries that survive contact with reality can
be extracted later; boundaries drawn up front are usually wrong.

**Content addressing** ([0004](docs/adr/0004-content-addressed-identity.md)).
A document's identity is the SHA-256 of its bytes, and its primary key is a UUIDv5 derived
from that digest. Re-running any crawler is therefore idempotent by construction rather than
by careful coding.

**The frontier is separate from content** ([DATA_MODEL.md](DATA_MODEL.md)).
`discovered_urls` holds per-URL state; `documents` holds one row per unique payload. Many
URLs may point at one document. This is what lets deduplication coexist with provenance:
the same PDF published at five URLs is stored once and attributed five times.

**Raw storage is immutable** ([0003](docs/adr/0003-object-storage-layout.md)).
`raw/` is write-once. Every derived artifact is keyed by the digest of the raw document it
came from, so a finding can always be traced back to unmodified bytes.

**The source registry is data with a review gate**
([0006](docs/adr/0006-source-registry-as-data.md)).
Sources are declared in YAML, and the schema refuses to enable one until a human has
recorded its terms of use. Collection ethics are a validation rule, not a convention.

## Deliberate omissions

Things a reader might expect that are absent on purpose:

- **No Redis or Celery.** There are no asynchronous tasks yet. They arrive in Phase 1 with
  the download queue that needs them.
- **No Neo4j.** The evidence graph is shallow and relational; PostgreSQL is sufficient until
  traversal depth actually demands otherwise.
- **No async SQLAlchemy.** The API does thin metadata queries; heavy work belongs in
  workers ([0005](docs/adr/0005-synchronous-sqlalchemy.md)).
- **No LLM integration.** Nothing yet needs interpretation. When it does, it goes behind a
  provider protocol with versioned prompts, never inline calls.
- **No agent framework.** Deterministic workflows are sufficient for the payment auditor,
  and are easier to trust for financially consequential decisions.

## Testing shape

```
tests/unit/          no database, no network. Runs in under a second.
tests/integration/   real PostgreSQL. Skipped automatically when unavailable.
```

Migrations are checked twice: an offline DDL comparison in
[test_migration_matches_models.py](tests/unit/test_migration_matches_models.py) that needs no
database, and `alembic check` against real PostgreSQL in CI, which is authoritative.
