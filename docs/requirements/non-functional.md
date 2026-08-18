# Non-functional requirements

Status values: **Implemented** · **Partial** · **Planned**.

Targets are stated as numbers wherever a number is meaningful. An unmeasurable requirement is
not a requirement.

## Reliability

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| NFR-001 | Re-running any pipeline stage must not duplicate documents or corrupt state. | Idempotent by construction, via content-derived IDs and keys | Implemented |
| NFR-002 | An interrupted crawl must resume without re-downloading completed work. | Checkpoint per run; per-URL state | Partial (schema done) |
| NFR-003 | No error may be silently swallowed. | Every failure logged with type and message, or raised | Implemented |
| NFR-004 | Transient failures must be retried with exponential backoff. | Max 5 attempts, then dead-letter | Planned |
| NFR-005 | A stage failure must not corrupt already-stored evidence. | Raw tier is write-once | Implemented |

## Auditability

The system audits others, so it must itself be auditable.

| ID | Requirement | Status |
| --- | --- | --- |
| NFR-010 | Every processing operation records input, output, software version, timestamp, and status. | Partial — `software_version` on crawl jobs; log lines carry `version` |
| NFR-011 | No finding may be produced without a traceable explanation. | Planned |
| NFR-012 | Every finding must be reproducible from stored evidence given the same versions. | Planned |
| NFR-013 | Model version, prompt version, and rule version must be recorded with any result they influenced. | Planned |
| NFR-014 | Every extracted fact retains document, page, location, method, and confidence. | Planned |

## Security

| ID | Requirement | Status |
| --- | --- | --- |
| NFR-020 | All downloaded content is treated as untrusted input. | Implemented |
| NFR-021 | No credential may be hardcoded or committed. | Implemented — `SecretStr`, gitignored `.env`, gitleaks in CI |
| NFR-022 | Production must fail to start with development credentials. | Implemented |
| NFR-023 | Containers run as a non-root user. | Implemented — asserted in CI |
| NFR-024 | Dependencies are scanned for known vulnerabilities on every change. | Implemented — `pip-audit --strict` in CI |
| NFR-025 | Untrusted filenames must never influence filesystem or object paths. | Implemented |
| NFR-026 | Authentication, authorisation, and RBAC required before any non-private deployment. | Planned |
| NFR-027 | Outbound requests must be restricted to a per-source allowlist, with redirects re-validated. | Planned |

## Privacy

| ID | Requirement | Status |
| --- | --- | --- |
| NFR-030 | Sources known to publish personal data must be flagged in the registry. | Implemented |
| NFR-031 | Licence, permitted use, and collection date recorded per source and carried with the corpus. | Implemented |
| NFR-032 | PII detection and redaction before any use of the corpus for training. | Planned |

## Observability

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| NFR-040 | All logs are structured and machine-parseable in deployed environments. | JSON, one object per line | Implemented |
| NFR-041 | Logs carry the canonical correlation keys. | `request_id`, `job_id`, `source_id`, `document_id`, `stage`, `status`, `duration_ms`, `error_type`, `error` | Implemented |
| NFR-042 | Third-party library logs use the same format. | stdlib routed through the same formatter | Implemented |
| NFR-043 | Stage duration and outcome are recorded for every pipeline stage. | `log_stage` | Implemented |
| NFR-044 | Metrics for crawler success rate, download failures, parse and OCR latency, classification confidence, queue depth, duplicate rate, throughput. | Prometheus/OpenTelemetry | Planned |
| NFR-045 | Distributed tracing across stages. | OpenTelemetry | Planned |

## Performance

Benchmarks must exist before optimisation. No target below is measured yet.

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| NFR-050 | Unit test suite stays fast enough to run on every save. | < 5 s (currently ~0.6 s) | Implemented |
| NFR-051 | API metadata reads stay responsive under normal load. | p95 < 200 ms | Planned |
| NFR-052 | Long-running work must never block an API worker. | All processing in workers | Planned |
| NFR-053 | Database queries must be bounded. | Statement timeout, default 30 s | Implemented |
| NFR-054 | Document throughput. | ≥ 500 documents/hour/worker | Planned |
| NFR-055 | OCR latency. | < 5 s/page | Planned |

## Cost

Cost is a first-class engineering metric. A system that costs $3 per document is commercially
useless for many workflows regardless of its accuracy.

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| NFR-060 | Cost per document must be tracked, split by OCR, LLM, storage, and compute. | Measured per stage | Planned |
| NFR-061 | Total processing cost per document. | < $0.10 | Planned |
| NFR-062 | LLM token usage, latency, and cost recorded per call. | Per-call accounting | Planned |

## Scalability

| ID | Requirement | Status |
| --- | --- | --- |
| NFR-070 | Processing scales horizontally by adding workers. | Planned |
| NFR-071 | No pipeline stage requires all documents in memory. | Implemented — streaming hash with size cap |
| NFR-072 | The corpus may grow to millions of objects without degrading key operations. | Implemented — sharded content-addressed keys |

## Maintainability

| ID | Requirement | Status |
| --- | --- | --- |
| NFR-080 | All code passes strict type checking. | Implemented — `mypy --strict`, 40 files, zero errors |
| NFR-081 | All code passes lint and format checks. | Implemented — ruff, black |
| NFR-082 | Module boundaries are explicit and one-directional. | Implemented — documented in ARCHITECTURE.md |
| NFR-083 | Architectural decisions are recorded as ADRs. | Implemented — `docs/adr/` |
| NFR-084 | Schema changes require a reviewed, reversible migration. | Implemented — verified against real PostgreSQL 17.11: `alembic check` clean, downgrade/upgrade round-trip |
| NFR-085 | A developer can run all infrastructure-free checks from a clean checkout with two commands. | Implemented — `make install && make check` |
| NFR-086 | Local infrastructure is reproducible. | Implemented — Compose stack and image built and executed via Colima; suite passes identically on native and containerized PostgreSQL |
| NFR-090a | Application behaviour must not depend on host-specific database configuration. | Implemented — session `timezone=UTC` and statement timeout pinned per connection; regression-tested against a non-UTC server |
| NFR-087 | A commit resolves to exactly one dependency graph. | Implemented — committed `uv.lock`; all installs use `uv sync --locked`, which fails on drift |
| NFR-088 | Supported Python versions are explicit and tested. | Implemented — 3.12 and 3.13, both verified locally; CI matrix ([ADR 0008](../adr/0008-python-version-policy.md)) |
| NFR-089 | An unexpectedly skipped integration test must fail rather than report green. | Implemented — `REQUIRE_INTEGRATION_TESTS=1` in CI and `make test-integration` |

## Supply chain

Reproducibility is a precondition for the product's central promise: a finding that cannot be
reproduced cannot be defended. See [ADR 0009](../adr/0009-supply-chain-integrity.md).

| ID | Requirement | Status |
| --- | --- | --- |
| NFR-100 | Vulnerable or badly licensed dependencies are blocked at introduction, before merge. | **Partially met** — `dependency-review-action` needs Advanced Security on a private repo and is gated off; `pip-audit --strict` still audits the locked set every run, so vulnerable deps are caught, but licence checking and pre-merge blocking are not. See SECURITY.md |
| NFR-101 | Our own code is scanned by a data-flow-aware SAST tool, not only pattern rules. | **Not met** — CodeQL requires Advanced Security on a private repo; workflow retained but manual-only. See SECURITY.md |
| NFR-102 | Container images are scanned for OS and library vulnerabilities. | Implemented and **verified green in CI** — Trivy: reporting on PRs, blocking on the weekly run; SARIF retained as a build artifact |
| NFR-103 | Third-party build inputs are immutable. | Implemented — base images pinned by digest; GitHub Actions pinned to commit SHAs |
| NFR-104 | Vulnerabilities disclosed *after* code merged are detected. | Implemented — scheduled weekly security workflow |
| NFR-105 | An SBOM is produced for every built image. | Implemented — SPDX via `anchore/sbom-action` |
| NFR-106 | Dependency updates are proposed automatically but never applied silently. | Implemented — Dependabot weekly PRs; no auto-merge |
| NFR-107 | Build provenance attests what produced a release artifact. | Planned — SLSA provenance |

## Availability

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| NFR-090 | Liveness must not depend on downstream dependencies. | `/health` checks nothing | Implemented |
| NFR-091 | Readiness must report which dependency is failing. | Per-check detail | Implemented |
| NFR-092 | API availability. | 99.5% | Planned |
| NFR-093 | Backups with point-in-time recovery, plus object versioning. | RPO 24 h, RTO 4 h | Planned |
