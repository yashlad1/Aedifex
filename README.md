# Aedifex

**What exists today: a production-grade acquisition platform for public construction documents.**
It safely collects, verifies, stores, and catalogues real documents — tenders, BOQs, schedules of
rates, specifications, contracts, procurement notices, drawings, technical documents — with complete
provenance for every byte.

## The product hypothesis is UNVALIDATED

The original thesis was cross-document evidence reconciliation for construction payments: an invoice
claiming 125 MT where the GRN confirms 118 MT, against a PO for 120 MT. It is a plausible problem and
it is **not yet a validated one**. Customer discovery is running in parallel
([docs/research/CUSTOMER_DISCOVERY.md](docs/research/CUSTOMER_DISCOVERY.md)), and the direction may
change once 15–30 interviews reveal which document-heavy workflows are actually painful and
commercially valuable.

So the pipeline is deliberately built **not to know** which product will consume the corpus. It
assumes construction documents are worth collecting with verifiable provenance; it assumes nothing
about what will be done with them. Concretely, that means no invoice-shaped schema, no
payment-specific extraction, no document type privileged over another, and no rules engine.

If discovery points somewhere else — contract obligation tracking, tender intelligence, rate
benchmarking, specification compliance — the acquisition layer should need no rewrite. That property
is the reason to build it first.

## Design principle

> **LLMs interpret evidence. Deterministic code verifies evidence.**

Arithmetic, equality, thresholds, quantity reconciliation, and duplicate detection are
deterministic code — always. Language models are used for classification, terminology
mapping, and explanation. A finding is never the unverified output of a model, and every
extracted fact points back to an exact page and location in a source document.

This holds whatever the product turns out to be, which is why it is stated as a principle rather
than as a feature.

## Current status: Phase 0 complete, acquisition pipeline in progress

The engineering foundation, the source registry, and reproducibility/supply-chain controls are
done. The **current product is the data acquisition platform**. No auditor, evidence graph, rules
engine, agent, or synthetic generator exists, and nothing here fabricates one.

| Area | State |
| --- | --- |
| Typed configuration with production hardening | ✅ Implemented, tested |
| Document taxonomy + lifecycle state machine | ✅ Implemented, tested |
| Content identity: SHA-256, deterministic IDs, spoof detection | ✅ Implemented, tested |
| Immutable content-addressed storage layout | ✅ Implemented, tested |
| Source registry (schema, loader, safety invariants) | ✅ Implemented, tested |
| Structured logging | ✅ Implemented, tested |
| Database models + initial migration | ✅ Verified against real PostgreSQL 17.11 (`alembic check` clean, downgrade/upgrade round-trip) |
| Read-only API (`/health`, `/sources`) | ✅ Implemented, tested |
| Integration tests (22) | ✅ Executed and passing against real PostgreSQL |
| Reproducible dependency lock (`uv.lock`) | ✅ 73 packages; `--locked` installs everywhere |
| Docker Compose stack (PostgreSQL + MinIO) | ✅ Executed via Colima; both healthy, bucket created with versioning |
| Container image | ✅ Built and smoke-tested; serves `/health`, reaches Compose PostgreSQL, runs as uid 1001 |
| CI: lint, types, unit tests (3.12 + 3.13) | ✅ Green on GitHub Actions |
| CI: migrations + integration tests vs PostgreSQL service container | ✅ Green on GitHub Actions |
| CI: secret scanning (gitleaks, full history) + dependency audit | ✅ Green on GitHub Actions |
| CI: container build, guards, smoke test, Trivy, SBOM | ✅ Green on GitHub Actions |
| Dependabot | ✅ Running — opened its first PRs immediately |
| CI: static analysis (Semgrep CE, blocking + self-tested) | ✅ Green on GitHub Actions — 255 rules, 90 targets, 0 findings, 100% parsed; self-test verified 119 matches across 18 files, 0 scanner errors |
| **CodeQL taint tracking** | ❌ **Known gap** — needs Advanced Security on a private repo; Semgrep CE covers SAST meanwhile. See [SECURITY.md](SECURITY.md) |
| SSRF guard + fetch policy layer (timeouts, retry, redirects) | ✅ Implemented, tested — pure policy, no network |
| HTTP transport boundary (IP-pinned, hostname TLS identity) | ✅ Implemented — verified over real sockets and a real TLS handshake; 14/14 security mutations caught |
| Crawlers, downloaders | ❌ Phase 1 — the transport exists, but nothing drives it and no source is enabled |
| OCR, parsing, classification | ❌ Phase 4 |
| Synthetic generator, anomaly injection | ❌ Phase 2 |
| Evidence graph, rules, risk engine | ❌ Phases 5–6 |

**No data source is enabled.** Every source in `config/sources/` ships
`verification_status: unverified` and `enabled: false`, because nobody has yet reviewed
those portals' terms of use. The registry schema makes it impossible to enable one until
somebody does. See [DATA_SOURCES.md](DATA_SOURCES.md).

## Quick start

Requires Python **3.12 or 3.13** (see [ADR 0008](docs/adr/0008-python-version-policy.md)).
[uv](https://docs.astral.sh/uv/) is the supported package manager.

```bash
git clone <repo> && cd Aedifex

make install     # creates .venv and installs the exact locked dependency set

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

The full suite passes identically against native PostgreSQL and against the Compose stack
(**365 tests, 0 skipped, on both**). The container image was built, started, and verified to
reach Compose PostgreSQL via `/health/ready`.

If you have no container runtime, PostgreSQL alone is enough for everything except the image:

```bash
brew install postgresql@17 && brew services start postgresql@17
createdb aedifex
export AEDIFEX_ENVIRONMENT=test
export AEDIFEX_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/aedifex
make migrate && make test-integration
```

On macOS without Docker Desktop, Colima provides the runtime:

```bash
brew install colima docker docker-compose docker-buildx
colima start --cpu 2 --memory 4 --disk 20 --vm-type=vz
```

See [RUNBOOK.md](RUNBOOK.md) for the `~/.docker/config.json` requirement.

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
uv.lock                     pinned dependency graph; installs use --locked
data/                       raw / processed / normalized / synthetic / labels
docs/requirements/          numbered functional + non-functional requirements
docs/adr/                   architecture decision records
migrations/                 Alembic
tests/{unit,integration}
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
