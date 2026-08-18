# Functional requirements

Status values: **Implemented** (built and tested) · **Partial** · **Planned** (not built).

Each implemented requirement names the test that demonstrates it, so "done" is verifiable
rather than asserted.

## Configuration

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| FR-001 | The system shall read all configuration from the environment through a single typed settings object. | Implemented | `test_config.py::TestDefaults` |
| FR-002 | The system shall reject an unrecognised `AEDIFEX_*` environment variable rather than ignoring it. | Implemented | `test_unknown_setting_is_rejected` |
| FR-003 | The system shall refuse to start in production with development placeholder credentials. | Implemented | `test_config.py::TestProductionHardening` |
| FR-004 | The system shall never expose secrets in logs, `repr`, or tracebacks. | Implemented | `test_config.py::TestSecretHandling` |

## Source registry

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| FR-010 | The system shall declare every data source as data, not code, with target, rate limits, and legal metadata. | Implemented | `test_registry_loader.py` |
| FR-011 | The system shall require recorded licence and permitted-use metadata for every source. | Implemented | `test_registry_models.py::TestDataUsePolicy` |
| FR-012 | The system shall refuse to enable a source whose terms of use have not been reviewed and approved. | Implemented | `TestEnablingRequiresReview` |
| FR-013 | The system shall refuse to enable a source that sits behind an access control. | Implemented | `TestAccessControls` |
| FR-014 | The system shall require `robots.txt` compliance for HTML-crawling sources. | Implemented | `TestRobotsPolicy` |
| FR-015 | The system shall require explicit acknowledgement before using a plain-HTTP source. | Implemented | `TestTransportSecurity` |
| FR-016 | The system shall report every registry problem in one pass, naming the file and source. | Implemented | `TestErrorReporting` |
| FR-017 | The system shall reject an enabled source naming an unregistered crawler. | Implemented | `TestCrawlerRegistration` |
| FR-018 | The system shall bound rate limits and reject self-contradictory limits. | Implemented | `TestRateLimitPolicy` |

## Content identity and deduplication

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| FR-020 | The system shall identify documents by the SHA-256 of their content. | Implemented | `test_content.py::TestHashing` |
| FR-021 | The system shall derive a deterministic document ID from the content digest, so the same bytes always yield the same ID. | Implemented | `TestDocumentIdNamespace` |
| FR-022 | The system shall detect duplicate content and store each unique payload once. | Implemented | `test_database.py::TestDeduplicationWithProvenance` |
| FR-023 | The system shall retain every URL at which a document was found, across sources. | Implemented | `test_two_urls_can_share_one_document` |
| FR-024 | The system shall associate every document with its originating source. | Implemented | `test_storage_keys.py::test_source_is_part_of_the_prefix` |
| FR-025 | The system shall detect near-duplicate documents that differ only slightly. | Planned | — |

## Content validation

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| FR-030 | The system shall enforce a maximum payload size while streaming, before buffering completes. | Implemented | `test_the_cap_is_enforced_while_streaming` |
| FR-031 | The system shall reject empty payloads. | Implemented | `test_empty_payload_is_rejected` |
| FR-032 | The system shall verify declared content type against actual magic bytes and reject mismatches. | Implemented | `TestResolveFormat` |
| FR-033 | The system shall reject content whose media type contradicts its filename (HTML error pages served for document requests). | Implemented | `test_html_error_page_served_for_a_pdf_request_is_rejected` |
| FR-034 | The system shall accept only formats a source is permitted to yield. | Implemented | `test_format_outside_the_source_allowlist_is_rejected`; enforced on every download through `DownloadPolicy.from_source` |
| FR-035 | The system shall neutralise untrusted filenames and never derive storage paths from them. | Implemented | `TestSafeFilename`, plus `TestFilename` on `Content-Disposition` traversal attempts — the stored path comes from the digest either way |
| FR-036 | The system shall expand archives under bounded entry count, size, and nesting limits. | Planned | — |
| FR-037 | The system shall detect and redact personal data in collected documents. | Planned | — |
| FR-038 | The system shall refuse a payload declared as a binary format that carries no signature for it. | Implemented | `FORMATS_WITH_A_SIGNATURE`; an HTML login page answered with HTTP 200 and `Content-Type: application/pdf` used to resolve cleanly as a PDF, because HTML has no magic bytes for the mismatch check to see |
| FR-039 | The system shall refuse a body shorter than its declared `Content-Length`, except when content-encoded. | Implemented | `TestDeclaredLength`; a truncated document with a valid digest is worse than no document |

FR-038 and FR-039 were **added after the code**, which is the exception in this file rather
than the rule. Both came from building the downloader: the first because the mismatch check
provably could not see an HTML page served as a PDF, the second because nothing had said what a
short body meant. Recorded as new requirements rather than folded into FR-030's evidence, so it
stays visible that they were not foreseen.

## Storage

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| FR-040 | The system shall preserve raw documents immutably and never overwrite them with derived output. | Implemented | `test_writing_to_the_raw_tier_is_refused`, and `RawObjectStore` has no delete or overwrite path — asserted structurally, not promised. A key already holding different bytes is a refusal; bucket versioning makes the guarantee recoverable if something else ever writes there |
| FR-041 | The system shall derive storage keys deterministically from content, so re-download is idempotent. | Implemented | `test_storage_keys.py::test_is_deterministic`; end to end, storing the same document twice uploads once and reports `already_present`, verified against MinIO by the version id not advancing |
| FR-042 | The system shall key every derived artifact by the digest of the raw document it came from. | Implemented | `test_is_keyed_by_the_raw_digest` |
| FR-043 | The system shall write documents to S3-compatible object storage. | Implemented | `RawObjectStore`; `test_storage_objects.py` against a fake that reproduces S3's failures, and `tests/integration/test_object_storage.py` against real MinIO. The upload carries a SHA-256 the store validates itself, and a corrupted body is refused with `XAmzContentChecksumMismatch` — measured for a streamed handle, not only for a `bytes` payload |

## Pipeline state

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| FR-050 | The system shall represent document processing state explicitly, as a state machine. | Implemented | `test_domain_documents.py::TestStateMachine` |
| FR-051 | The system shall reject illegal state transitions loudly. | Implemented | `test_skipping_stages_is_rejected` |
| FR-052 | The system shall record `error_type`, message, retry count, and timestamp for failures. | Implemented | `models.py` (`DiscoveredUrl`, `CrawlJob`) |
| FR-053 | The system shall allow a failed document to be retried as a legal state transition. | Implemented | `test_failure_is_retryable` |
| FR-054 | The system shall quarantine unsafe content in a terminal state requiring human release. | Implemented | `test_quarantine_is_not_self_serve` |
| FR-055 | The system shall persist a resumable checkpoint per crawl run. | Implemented | `test_checkpoint_round_trips_as_json` |
| FR-056 | The system shall dead-letter jobs that exhaust their retries. | Planned | — |

## Classification and extraction

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| FR-060 | The system shall classify documents into the predefined taxonomy. | Partial | Taxonomy and storage implemented (`test_domain_documents.py`); no classifier yet |
| FR-061 | The system shall record classification confidence and classifier version. | Partial | Schema implemented; no classifier yet |
| FR-062 | The system shall report `unknown` rather than guess when classification is uncertain. | Partial | Vocabulary implemented; no classifier yet |
| FR-063 | The system shall extract typed structured fields from each document type. | Planned | — |
| FR-064 | The system shall record page, bounding box, extraction method, and confidence for every extracted fact. | Planned | — |

## Acquisition

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| FR-070 | The system shall download publicly available construction procurement documents. | **Mechanism implemented; blocked on source approval** | `test_download.py`, and `TestADocumentEndToEnd` takes a PDF from a URL through the guard, a redirect, a retried 503, a real socket, and onto disk with a matching digest. No source is enabled, so nothing has been downloaded from a real portal |
| FR-071 | The system shall rate-limit, retry with backoff, and bound concurrency per source. | Implemented | `test_fetch_ratelimit.py`, `test_fetch_controller.py`; see [fetch.md](fetch.md) FR-130–135, FR-140–148 |
| FR-072 | The system shall resume an interrupted crawl without duplicating work. | Planned | — |
| FR-073 | The system shall identify itself with a User-Agent carrying a contact address. | Implemented | `test_anonymous_user_agent_is_rejected` |

## Audit engine

| ID | Requirement | Status |
| --- | --- | --- |
| FR-080 | The system shall build an evidence graph relating documents, vendors, and materials. | Planned |
| FR-081 | The system shall evaluate versioned deterministic rules over the evidence graph. | Planned |
| FR-082 | The system shall perform all arithmetic and equality checks in deterministic code, never via a language model. | Planned |
| FR-083 | The system shall reference exact source evidence for every finding. | Planned |
| FR-084 | The system shall report missing mandatory evidence as a finding. | Planned |
| FR-085 | The system shall produce an explainable risk score from findings. | Planned |
| FR-086 | The system shall route findings to human review based on confidence thresholds. | Planned |
| FR-087 | The system shall make every finding reproducible from stored evidence, given the same dataset, code, model, prompt, and rule versions. | Planned |

## API

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| FR-090 | The system shall expose liveness and readiness endpoints that report per-dependency status. | Implemented | `test_api.py::TestHealth` |
| FR-091 | The system shall expose source registry metadata, including licence constraints. | Implemented | `TestSources` |
| FR-092 | The system shall correlate every request with an ID, propagated to logs and returned to the caller. | Implemented | `TestRequestCorrelation` |
| FR-093 | The system shall version its API paths. | Implemented | `TestOpenApi` |
| FR-094 | The system shall not expose internal connection details in error responses. | Implemented | `test_readiness_does_not_leak_connection_details` |
| FR-095 | The system shall accept document uploads and trigger audits. | Planned | — |
