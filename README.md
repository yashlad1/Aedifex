# Aedifex

**Aedifex is an evidence acquisition platform for construction, not a crawler.** Crawling is one way
a document arrives; a manual upload, a customer export, an email, an ERP system, cloud storage or an
API are others, and **every path converges into the same immutable pipeline.** Origin affects
provenance and nothing after it: a measurement is a measurement whether it was fetched or handed
over.

What exists today runs end to end. A document is acquired with provenance for every byte, stored
content-addressed and immutable, read into facts that each cite a page span or a spreadsheet cell,
turned into derived facts that record their own inputs, judged by deterministic rules, and published
as findings over a CLI and an API — with every finding walkable back to the bytes it came from.

## The product hypothesis is UNVALIDATED

The original thesis was cross-document evidence reconciliation for construction payments: an invoice
claiming 125 MT where the GRN confirms 118 MT, against a PO for 120 MT. It is a plausible problem and
it is **not yet a validated one**. Customer discovery is running in parallel
([docs/research/CUSTOMER_DISCOVERY.md](docs/research/CUSTOMER_DISCOVERY.md)), and the direction may
change once 15–30 interviews reveal which document-heavy workflows are actually painful and
commercially valuable.

The pipeline was deliberately built **not to know** which product would consume the corpus, and that
restraint has since been spent deliberately rather than abandoned: a rule registry, payment
reconciliation over work items, and document-type-aware extraction all now exist, each added because
a real document demanded it. What still does not exist is an invoice-shaped schema, a rules DSL, or
any document type privileged over another.

Architecture is now **frozen pending real-corpus evidence.** The gating need is real post-award
project data — a Measurement Book, an IPC, a variation order — because no public procurement portal
publishes them. See [docs/plans/2026-08-20-development-priorities.md](docs/plans/2026-08-20-development-priorities.md).

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

## Reference data and project data

The useful axis is not public versus private. It is whether a document is **shared across many
projects** or **specific to one**.

**Reference data** — tender notices, BOQs, standard specifications, Schedule of Rates, material
specifications, government circulars, contract clauses, procurement rules — gives context, standards
and baseline expectations. Public portals are good at it, and it is all the corpus currently holds.

**Project data** — contract agreement, Measurement Book, RA Bill / IPC, variation orders, site
instructions, inspection reports, payment certificates, test reports, daily logs — is the record of
one job, and it is what payment verification actually consumes. It comes from customers, not
portals.

Both streams are meant to meet in one evidence graph. Reference data has nowhere to live in the
current model, which scopes every rule to a single project; that is the crux of the business-object
work and is deliberately unresolved until a real Schedule of Rates exists to settle it.

## Current status: the pipeline runs end to end on real data

The engineering foundation, the source registry, and reproducibility/supply-chain controls are done,
and so is the vertical slice: real NHAI documents reach evidence-backed findings. No agent framework,
graph database, OCR engine or rules DSL exists, and nothing here fabricates one.

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
| **[SRS.md](SRS.md)** | **Read first.** Vision, mission, the evidence pipeline, personas, guiding principles |
| [CLAUDE.md](CLAUDE.md) | Orientation for an agent or a new contributor: what to read, and in what order |
| [AEDIFEX-RULES.md](AEDIFEX-RULES.md) | The engineering constitution |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System boundaries, data flow, module rules |
| [DATA_MODEL.md](DATA_MODEL.md) | Tables, keys, and why the frontier is separate from content |
| [DATA_SOURCES.md](DATA_SOURCES.md) | Every source, its legal status, and the review process |
| [DATASET.md](DATASET.md) | Dataset schema, versioning, provenance |
| [SECURITY.md](SECURITY.md) | Threat model for untrusted documents, secrets, PII |
| [RUNBOOK.md](RUNBOOK.md) | Operational failures and recovery |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow, definition of done |
| [docs/requirements/](docs/requirements/) | FR-xxx / NFR-xxx requirements |
| [docs/adr/](docs/adr/) | Decision records |
| [docs/plans/](docs/plans/) | Implementation plans, newest first |

## Licence and ethics

Collection is limited to publicly accessible documents, under per-source rate limits, with
`robots.txt` respected. Access controls, CAPTCHAs, paywalls, and authentication boundaries
are never bypassed — the registry schema enforces this structurally rather than relying on
convention.
