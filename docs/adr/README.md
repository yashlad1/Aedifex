# Architecture decision records

One file per significant decision. Immutable once accepted: a reversal is a new ADR that
supersedes the old one, so the reasoning history survives.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-modular-monolith.md) | Modular monolith, not microservices | Accepted |
| [0003](0003-object-storage-layout.md) | Immutable, content-addressed object storage | Accepted |
| [0004](0004-content-addressed-identity.md) | SHA-256 content identity with deterministic UUIDs | Accepted |
| [0005](0005-synchronous-sqlalchemy.md) | Synchronous SQLAlchemy | Accepted |
| [0006](0006-source-registry-as-data.md) | Source registry as data, with a mandatory review gate | Accepted |
| [0007](0007-defer-queue-infrastructure.md) | Defer queue infrastructure until there are tasks | Accepted |
| [0008](0008-python-version-policy.md) | Python version policy: support 3.12 and 3.13 | Accepted |
| [0009](0009-supply-chain-integrity.md) | Supply-chain integrity: lockfile, digest pins, layered scanning | Accepted |
| [0010](0010-fetch-retry-ssrf-policy.md) | HTTP fetch policy: SSRF validation, retries, rate limiting | Accepted (pre-implementation) |
| [0011](0011-transport-boundary.md) | Transport boundary: validated targets only | Accepted |
| [0012](0012-postgresql-frontier-queue.md) | PostgreSQL as the frontier queue | Accepted |
| [0013](0013-reuse-evaluation-kingfisher-scrapy-ocds.md) | Reuse evaluation: Kingfisher, Scrapy, OCDS | Accepted |
| [0014](0014-reference-data-by-explicit-applicability.md) | Reference data by explicit applicability, not global scope | Accepted (pre-implementation) |
| [0015](0015-ocr-execution-shape-on-apple-silicon.md) | OCR on three CPU threads with a bounded ONNX pool; CoreML rejected | Accepted |
| [0016](0016-ocr-gateway-not-an-ocr-engine.md) | Aedifex owns an OCR gateway and a trust boundary, not an OCR engine | Accepted as direction (nothing implemented) |

Write one when a change constrains future work, chooses between viable technologies,
introduces or removes a boundary, or encodes a policy in code. See
[0001](0001-record-architecture-decisions.md).
