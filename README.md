# Aedifex

An evidence-grounded auditing platform for construction and infrastructure projects.

Aedifex ingests the documents a construction project generates — contracts, BOQs, purchase
orders, invoices, delivery challans, GRNs, material test certificates, inspection reports,
change orders — and answers a question that no single document can answer on its own:

> **Is the evidence sufficient to approve this payment?**

The hard problem is not reading one document. It is **cross-document evidence
reconciliation**: an invoice claiming 125 MT when the GRN confirms 118 MT received, against
a PO for 120 MT, supported by a test certificate for Fe500 when the PO required Fe500D.

## Design principle

> **LLMs interpret evidence. Deterministic code verifies evidence.**

Arithmetic, equality, thresholds, quantity reconciliation, and duplicate detection are
deterministic code — always. Language models are used for classification, terminology
mapping, obligation extraction, and explanation. A finding is never the unverified output of
a model, and every finding points back to an exact page and bounding box in a source
document.

## Current status: Phase 0 complete

This repository is at **Phase 0 of 10** — the engineering foundation and the source
registry. The audit engine described above does not exist yet, and nothing here fabricates
it.

| Area | State |
| --- | --- |
| Typed configuration with production hardening | ✅ Implemented, tested |
| Document taxonomy + lifecycle state machine | ✅ Implemented, tested |
| Content identity: SHA-256, deterministic IDs, spoof detection | ✅ Implemented, tested |
| Immutable content-addressed storage layout | ✅ Implemented, tested |
| Source registry (schema, loader, safety invariants) | ✅ Implemented, tested |
| Structured logging | ✅ Implemented, tested |
| Database models + initial migration | ⚠️ Authored; verified in CI against real PostgreSQL |
| Read-only API (`/health`, `/sources`) | ✅ Implemented, tested |
| Docker Compose stack | ⚠️ Authored; **never executed** (no Docker on the authoring machine) |
| Crawlers, downloaders | ❌ Phase 1 |
| OCR, parsing, classification | ❌ Phase 4 |
| Synthetic generator, anomaly injection | ❌ Phase 2 |
| Evidence graph, rules, risk engine | ❌ Phases 5–6 |

**No data source is enabled.** Every source in `config/sources/` ships
`verification_status: unverified` and `enabled: false`, because nobody has yet reviewed
those portals' terms of use. The registry schema makes it impossible to enable one until
somebody does. See [DATA_SOURCES.md](DATA_SOURCES.md).

## Quick start

Requires Python 3.12+. [uv](https://docs.astral.sh/uv/) is the supported package manager.

```bash
git clone <repo> && cd Aedifex

python3 -m venv .venv && .venv/bin/pip install uv
.venv/bin/uv pip install -e ".[dev]"

# Everything below runs with no database, no network, and no Docker.
make test        # unit tests
make lint        # ruff + black --check
make typecheck   # mypy --strict
make check       # all of the above
```

Inspect the source registry without any infrastructure:

```bash
.venv/bin/python -m scripts.validate_registry
```

### With infrastructure

```bash
cp .env.example .env
docker compose up -d postgres minio    # ⚠️ see caveat below
make migrate
make run-api                           # http://localhost:8000/docs
make test-integration
```

> **Caveat:** the Compose stack and the Alembic migration have not been executed on the
> authoring machine — Docker and PostgreSQL were unavailable. They are exercised by CI
> (`.github/workflows/ci.yml`) against real PostgreSQL, including `alembic check` to prove
> the migration matches the ORM models. Treat the first local `docker compose up` as
> unverified and report anything that breaks.

## Repository layout

```
src/aedifex/
  config.py                 typed settings, production hardening
  errors.py                 exception hierarchy
  domain/                   shared vocabulary (document types, states, file formats)
  acquisition/
    content.py              hashing, deterministic IDs, untrusted-content validation
    registry/               declarative source definitions + strict loader
  infrastructure/
    database/               ORM models, session management
    storage/                immutable content-addressed key layout
    observability/          structured logging
apps/api/                   FastAPI read-only metadata API
config/sources/             the source registry (data, not code)
data/                       raw / processed / normalized / synthetic / labels
docs/requirements/          numbered functional + non-functional requirements
docs/adr/                   architecture decision records
migrations/                 Alembic
tests/{unit,integration,e2e}
```

## Documentation

| Document | Contents |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System boundaries, data flow, module rules |
| [DATA_MODEL.md](DATA_MODEL.md) | Tables, keys, and why the frontier is separate from content |
| [DATA_SOURCES.md](DATA_SOURCES.md) | Every source, its legal status, and the review process |
| [DATASET.md](DATASET.md) | Dataset schema, versioning, provenance |
| [SECURITY.md](SECURITY.md) | Threat model for untrusted documents, secrets, PII |
| [RUNBOOK.md](RUNBOOK.md) | Operational failures and recovery |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow, definition of done |
| [docs/requirements/](docs/requirements/) | FR-xxx / NFR-xxx requirements |
| [docs/adr/](docs/adr/) | Decision records |

## Licence and ethics

Collection is limited to publicly accessible documents, under per-source rate limits, with
`robots.txt` respected. Access controls, CAPTCHAs, paywalls, and authentication boundaries
are never bypassed — the registry schema enforces this structurally rather than relying on
convention.
