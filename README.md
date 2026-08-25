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

Architecture is **frozen**, and as of 2026-08-24 so is engineering: new work needs an evidence ID —
a real document or an observed reviewer workflow that forced it — and speculative tickets are not
created. The gating need is real post-award project data: a Measurement Book, an RA bill, a variation
order, none of which any public procurement portal publishes. See
[docs/plans/2026-08-24-reality-sprint.md](docs/plans/2026-08-24-reality-sprint.md), and
[docs/plans/2026-08-20-development-priorities.md](docs/plans/2026-08-20-development-priorities.md)
for the priority order it inherits.

**Measured, as of 2026-08-24.** Every registered rule was run against a real ₹85 crore building
tender and the numbers are not flattering, which is the point of recording them:

| | |
| --- | --- |
| Findings across the whole corpus | 254 `INCONCLUSIVE`, 51 `PASS`, 5 `REVIEW`, **0 `FAIL`** |
| Rules validated on real *building* evidence | **4 of 10** |
| Findings awaiting review on the one real project | **1** |
| Why | no measurement sheet, RA bill, variation, material or quality document exists in any corpus tier |

Four of the ten rules verify the payment chain — claim against measurement, rate against contract —
and **none of them has ever run against a real measurement sheet**, because none exists to run
against. That is a missing-document problem, not an engineering one, and no amount of code changes
it. The full per-rule record, including which `INCONCLUSIVE` results are honest and which turned out
to be defects, is in
[docs/research/REAL_CORPUS_RULE_VALIDATION.md](docs/research/REAL_CORPUS_RULE_VALIDATION.md).

**If you can help with that**, the ask is one page:
[docs/DATA_REQUEST.md](docs/DATA_REQUEST.md).

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
and so is the vertical slice: real documents reach evidence-backed findings that a person can review.
No agent framework, graph database, rules DSL or risk score exists, and nothing here fabricates one.
The one recogniser in the codebase — OCR — is deliberately a gateway around an external engine rather
than an engine of our own.

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
| Integration tests (98) | ✅ Executed and passing against real PostgreSQL |
| Reproducible dependency lock (`uv.lock`) | ✅ 102 packages; `--locked` installs everywhere |
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
| Crawler: discovery, frontier, resumable acquisition | ✅ Implemented — a real NHAI crawl put the first documents in the corpus |
| Classification, PDF and XLSX extraction | ✅ Implemented — 674 priced rows read from a real ₹85 crore building bill, each citing its page |
| OCR, for scans with no text layer only | ✅ Implemented — RapidOCR behind a gateway; never run on a PDF that already has text |
| Derived facts, deterministic rules, findings | ✅ Implemented — 10 rules, of which **4 have been validated against real building evidence and 6 are starved of it** |
| Review workspace: API, frontend, recorded decisions | ✅ Implemented — click a citation, land on the page that states it |
| Synthetic project with deliberately injected anomalies | ✅ Implemented — `scripts/generate_synthetic_project.py`, byte-reproducible, with a ground-truth file |
| Evidence graph database, rules DSL, risk scoring | ❌ **Not built, and not scheduled.** No graph database, no DSL, no risk score. See [ARCHITECTURE.md](ARCHITECTURE.md) |
| Authentication, authorization, tenancy | ❌ **Not built.** The write API refuses writes and artifact content when the environment is `production` |

**8 of 14 registered sources are approved and collectable**; the other 6 ship
`verification_status: unverified` and `enabled: false`, because nobody has yet reviewed those
portals' terms of use, and the registry schema makes it impossible to enable one until somebody
does. Run `.venv/bin/python -m scripts.validate_registry` to see the current split. See
[DATA_SOURCES.md](DATA_SOURCES.md).

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

### The review workspace

```bash
make run-api                           # first, in one shell
make viewer                            # http://127.0.0.1:5173
```

The first user interface: create a project, give it documents, process them, read the findings, click
an item of evidence and land on the page of the original PDF that states it, then record a review.
See [frontend/README.md](frontend/README.md).

**It is not deployable outside a development machine.** The write API has no authentication, no
authorization and no tenancy, and refuses to serve writes or artifact content when the environment is
`production`. That guard makes the gap loud; it does not close it.

The full suite passes identically against native PostgreSQL and against the Compose stack
(**2,130 unit and 98 integration tests** on both). The container image was built, started, and
verified to reach Compose PostgreSQL via `/health/ready`.

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

## How the code flows

Read this section to follow one real document from arrival to a reviewed finding. Every name below
is a real function or module, in the order it actually runs, so you can open them side by side.

**Two ways in, one pipeline.** A document either arrives by upload or is fetched by the crawler.
After the first step they are indistinguishable to everything downstream — origin changes provenance
and nothing else.

```
        upload  (a customer, an operator)          crawl  (a public portal)
                       │                                    │
        workspace.attach_upload                acquisition.crawl.runner
                       │                                    │
                       └──────────► extraction.ingest ◄─────┘
                                    ingest_file()
                                          │
                            content-addressed, immutable
```

### 1 — Arrival, and why nothing can be overwritten

| Step | Where | What happens |
| --- | --- | --- |
| Bytes in | [`workspace/__init__.py`](src/aedifex/workspace/__init__.py) `attach_upload` | A file becomes a temp file, nothing is trusted yet |
| Identity | [`acquisition/content.py`](src/aedifex/acquisition/content.py) | SHA-256 of the bytes → a UUIDv5. **The digest is the identity**, so the same bytes twice are one artifact |
| Storage | [`infrastructure/storage/objects.py`](src/aedifex/infrastructure/storage/objects.py) `RawObjectStore.put` | Written to `raw/<source>/<aa>/<bb>/<digest>.pdf`. This class has **no delete and no overwrite**, deliberately |
| Provenance | [`extraction/ingest.py`](src/aedifex/extraction/ingest.py) `ingest_file` | A `document_uploads` row: who supplied it, under what name, when. A crawl writes `document_retrievals` instead, with the HTTP facts. **An upload never fabricates an HTTP status** |
| Membership | `workspace.attach_upload` | A `project_documents` row. Artifact identity and project membership are separate: two customers can upload identical bytes and each sees their own filename |

### 2 — Reading: bytes become facts that cite their source

`POST /v1/projects/{id}/process` → `workspace.process_project` → per document, by format:

- **PDF** → [`extraction/runner.py`](src/aedifex/extraction/runner.py) `analyse_document`
  - [`extraction/pdftext.py`](src/aedifex/extraction/pdftext.py) `extract_text` — bounded text layer, page by page
  - [`extraction/tender_notice.py`](src/aedifex/extraction/tender_notice.py) `extract_tender_notice` — document-scoped values: estimated cost, bid security, dates
  - [`extraction/pdf_boq.py`](src/aedifex/extraction/pdf_boq.py) `read_pdf_boq` — priced bill rows: item, unit, quantity, rate, amount
  - [`extraction/ocr.py`](src/aedifex/extraction/ocr.py) — only for a scan with no text layer
- **XLSX** → `analyse_spreadsheet` → [`extraction/spreadsheet.py`](src/aedifex/extraction/spreadsheet.py), which keeps the **cell reference**

Then [`extraction/store.py`](src/aedifex/extraction/store.py) `persist_facts`. Every row in
`extracted_facts` carries the page and character span, or the sheet, row and column, that it came
from. **A value with no citation is not stored.**

### 3 — Calculating, without judging

[`calculation/engine.py`](src/aedifex/calculation/engine.py) — `compute_bill_items_total`,
`compute_bid_security_share`, `compute_quantity_variance`. A derived fact records **its own inputs**,
so a total that looks wrong unfolds into the rows it was summed from. Nothing here decides whether a
number is acceptable.

### 4 — Judging, deterministically

[`verification/`](src/aedifex/verification/) — `evaluate_all` for one document, `evaluate_project`
across documents, `evaluate_work_item` for the payment chain. Ten rules, each ordinary Python
arithmetic: no model, same answer every time, auditable line by line.

Two supporting pieces matter more than they look:

- [`extraction/selection.py`](src/aedifex/extraction/selection.py) — when two documents state
  different quantities for one item, this **refuses to choose** and records why. Picking one would be
  a guess wearing the clothes of a finding.
- Outcomes are `PASS`, `FAIL`, `REVIEW`, `INCONCLUSIVE`. `INCONCLUSIVE` means *the evidence was
  absent* and must never be displayed as a failure.

### 5 — Findings, and a person deciding

`persist_finding` writes the conclusion plus a `finding_evidence` row per citation.
[`review/__init__.py`](src/aedifex/review/__init__.py) `record_review` appends what a person
concluded — append-only, so a second reviewer disagreeing with the first is preserved. Each review
stores a fingerprint of the conclusion it saw, so if the numbers change underneath it the review is
shown as **stale** rather than silently inherited.

### 6 — Out

- [`apps/api/main.py`](apps/api/main.py) — the project workspace, findings, evidence, and the
  artifact itself at the cited page
- [`frontend/`](frontend/) — the reviewer's screen: original document on the left, extracted evidence
  on the right, click a citation to jump to the page or cell
- [`apps/crawler/main.py`](apps/crawler/main.py) — the operator CLI: `crawl`, `ingest`, `analyse`,
  `review`

### The one invariant worth remembering

```
Finding → Evidence → Derived Fact → Fact → Document → Page/Cell → Immutable Raw Artifact
```

Every finding walks back to bytes nobody can edit.
[`scripts/audit_traceability.py`](scripts/audit_traceability.py) walks that chain over every stored
finding and **fails the build** if a `PASS`, `FAIL` or `REVIEW` cannot be traced. That script is the
shortest honest answer to "does this actually work".

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
  extraction/               classify, extract, persist facts; the analysis pipeline
  calculation/              derived facts, precision-aware row arithmetic
  verification/             deterministic rules, single- and cross-document
  review/                   what a person concluded about a finding
  workspace/                declare a project, attach documents, read its state back
  classification/           proposes a document type; never decides one
apps/api/                   FastAPI: the corpus catalogue, the project workspace, review
apps/crawler/               operator CLI: crawl, ingest, analyse, review
frontend/                   the review workspace (React, TypeScript, Vite)
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
| **[docs/DATA_REQUEST.md](docs/DATA_REQUEST.md)** | **What the project needs from the outside world**, and what it gives back. Forwardable as-is |
| [docs/INDIA_RUNNER.md](docs/INDIA_RUNNER.md) | Running the existing acquisition pipeline on a Mac in India, operated by somebody who cannot use Terminal. Orchestration only — no new capability, and it can refuse a source but never permit one |
| [docs/SPRINT_1_REPORT.md](docs/SPRINT_1_REPORT.md) | Sprint 1 status: what was done, what was not, and what was learned. Separates engineering completed from hypothesis validated |
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
