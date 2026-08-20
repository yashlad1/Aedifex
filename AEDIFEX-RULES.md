PRIVATE REPO ON GITHUB

I inspected the ZIP rather than relying only on ClaudeCode’s summary. Phase 0 is well structured, but I would now give ClaudeCode a permanent engineering constitution like the following and tell it that these rules apply to every future slice and every future session.

The security baseline should explicitly map to NIST SSDF, OWASP ASVS 5.x, and—once AI functionality lands—OWASP’s AI/LLM verification guidance. NIST’s SSDF is specifically intended to embed secure-development practices throughout the SDLC, rather than treating security as a final test.   For software-supply-chain integrity, SLSA 1.2 is the current specification and emphasizes provenance for build artifacts.  

Aedifex Engineering Constitution

These instructions apply permanently to every ClaudeCode development session on Aedifex.

Aedifex is intended to become a production-grade, financially consequential, evidence-grounded construction auditing platform. Code quality, correctness, security, reproducibility, provenance, testing, and auditability take priority over development speed.

The goal is not:

Make the feature work.

The goal is:

Make the feature correct, testable, secure, observable, reproducible, maintainable, and safe to operate.

⸻

0. Read the SRS Before Anything Else

At the start of every session, and before writing or changing any code, read SRS.md.

It defines what Aedifex is for: evidence is the product, the pipeline every component must fit into,
the personas any feature must serve, and the twelve guiding principles. Every other document
describes how one part works. Where a design decision and the SRS disagree, the SRS wins and the
design is wrong.

This rule is numbered zero because it precedes the others in time, not because it outranks the
security rules. Rules 1 onward tell you how to build correctly; the SRS tells you whether the thing
is worth building at all.

Do not skip it for a task that looks small. A one-line change to an extraction rule can quietly
break "every extracted value must be traceable", and by the time that is noticed there is a corpus of
findings nobody can defend. If a request appears to conflict with the SRS, say so in a sentence and
proceed with the request — the owner may be deliberately overriding it — but do not resolve the
conflict silently.

CLAUDE.md carries the same instruction and is loaded automatically at session start, so this is
enforced in two places on purpose: one that is read by habit, one that is read by the tooling.

⸻

1. Core Development Rule

For every change, evaluate:

Correctness → Security → Reliability → Testability → Maintainability → Observability → Performance → Scalability → Cost → Auditability

Do not optimize only for LOC, speed of implementation, or passing the current test suite.

Passing tests are necessary, not proof of correctness.

⸻

2. Never Trust Existing Code Just Because Tests Pass

Before modifying a subsystem:

1. Read its implementation.
2. Read its tests.
3. Read applicable requirements.
4. Read applicable ADRs.
5. Check callers and dependencies.
6. Understand assumptions and invariants.
7. Identify failure modes.
8. Then implement.

A green test suite may contain incorrect assumptions.

If implementation and specification disagree, stop and resolve the discrepancy rather than silently selecting one.

⸻

3. Requirements Before Implementation

Every meaningful feature must trace to a requirement.

For new behavior:

Requirement
     ↓
Design
     ↓
Implementation
     ↓
Tests
     ↓
Observability
     ↓
Documentation

If a meaningful behavior is not represented in the requirements, add or update the appropriate requirement.

Requirements should be measurable whenever possible.

Bad:

The downloader should be reliable.

Good:

Transient HTTP failures shall be retried
with exponential backoff and jitter,
maximum 5 attempts.

⸻

4. Use ADRs for Architectural Decisions

Create or update an ADR when a change materially affects:

* architecture,
* storage,
* queues,
* database strategy,
* data model,
* external provider choice,
* security model,
* AI provider strategy,
* deployment architecture,
* consistency guarantees,
* authentication,
* caching,
* event processing,
* workflow orchestration.

Every ADR should contain:

Context
Decision
Alternatives considered
Advantages
Disadvantages
Operational consequences
Security consequences
Migration consequences

Do not create ADRs for trivial implementation details.

⸻

5. Prefer the Simplest Architecture That Meets the Requirement

Do not introduce:

* microservices,
* Kafka,
* Kubernetes,
* vector databases,
* graph databases,
* multi-agent frameworks,
* distributed orchestration,
* new cloud services

unless the requirement clearly justifies them.

Aedifex currently uses a modular-monolith direction.

Preserve that until there is evidence that a subsystem needs independent scaling, deployment, ownership, reliability, or lifecycle characteristics.

⸻

6. No Premature Agentic AI

Do not turn deterministic workflows into agents.

Use normal software for:

calculations
comparison
validation
thresholds
schema validation
state transitions
security checks
permission checks
deduplication
hashing
matching with deterministic identifiers

Use AI only where semantic interpretation genuinely adds value.

Agents may eventually orchestrate tools.

Agents must never replace deterministic financial/compliance controls.

⸻

7. Deterministic Logic Must Stay Deterministic

Example:

Never ask an LLM:

Does invoice quantity exceed PO quantity?

Code:

invoice.quantity > po.quantity

instead.

AI can explain the result afterward.

⸻

8. Strict Typing Remains Mandatory

Continue enforcing:

mypy --strict

New code must not weaken strict typing.

Avoid:

Any
cast(...)
# type: ignore

unless justified.

Every ignore must include a reason where practical.

Never disable type checking for an entire module merely to make CI pass.

⸻

9. Validate at System Boundaries

Everything entering Aedifex is untrusted.

Validate:

HTTP responses
environment configuration
database inputs
uploaded files
scraped files
OCR output
LLM output
API payloads
queue messages
external API responses
configuration files

Use typed models at boundaries.

Internal code should operate on validated domain objects whenever possible.

⸻

10. Never Trust Downloaded Documents

Aedifex intentionally processes hostile Internet content.

Treat every downloaded byte as adversarial.

Before enabling real crawlers, implement:

maximum download size
streaming limits
MIME validation
magic-byte validation
archive expansion limits
nested archive limits
filename sanitization
SSRF protection
redirect validation
network isolation for parsers
parser timeouts
CPU limits
memory limits
temporary-storage limits
PDF safety controls

Do not run untrusted documents through unrestricted subprocesses.

⸻

11. SSRF Protection Is Mandatory

HTTP fetching must never accept arbitrary destinations.

For each source:

source base URL
       ↓
permitted hosts
       ↓
DNS resolution
       ↓
IP validation
       ↓
request
       ↓
redirect?
       ↓
validate again

Reject:

localhost
127.0.0.0/8
private RFC1918 networks
link-local addresses
metadata endpoints
internal hostnames
unsupported schemes
credentials embedded in URLs

Every redirect must be independently validated.

DNS rebinding should be considered in the design.

⸻

12. HTTP Clients Need Production Failure Handling

Implement:

connection timeout
read timeout
total request timeout
connection pooling
bounded concurrency
rate limiting
exponential backoff
jitter
retry budgets
Retry-After handling
response size limits
status-code policy
cancellation

Do not retry blindly.

For example:

429 → usually retry
503 → retry
timeout → retry
400 → normally don't
401 → don't
403 → don't
404 → don't
malicious payload → never

Retries must be bounded.

⸻

13. Idempotency Is Mandatory

Every pipeline operation should be safe to repeat.

Running the same crawl twice must not create:

duplicate Documents
duplicate objects
duplicate URLs
duplicate audit findings
duplicate jobs
corrupted states

Prefer explicit idempotency keys and content-addressed identity.

⸻

14. State Machines Must Reject Invalid Transitions

Do not simply assign:

document.status = "processed"

without validating the transition.

Define permitted transitions.

Example:

DISCOVERED
     ↓
DOWNLOADING
     ↓
DOWNLOADED
     ↓
VALIDATED
     ↓
PROCESSING
     ↓
PROCESSED

Exceptional:

FAILED
QUARANTINED
DEAD_LETTER

Invalid transitions should fail loudly.

⸻

15. Raw Evidence Is Immutable

Never alter original downloaded evidence.

Use:

RAW
 ↓
PROCESSED
 ↓
NORMALIZED
 ↓
ENRICHED
 ↓
LABELED

Each stage creates a new artifact.

The original remains unchanged.

⸻

16. Provenance Must Never Be Lost

Every derived value should eventually be traceable to:

source
URL
collection time
document hash
document
page
bounding box
extraction method
extractor version
model version
prompt version
confidence
processing version

Aedifex audits other organizations.

Aedifex itself therefore has to be more auditable than the systems it audits.

⸻

17. Never Log Sensitive Values

Never log:

passwords
API keys
authorization headers
cookies
database credentials
PAN
Aadhaar
bank account numbers
full PII documents
LLM prompts containing sensitive production data

Logs should contain identifiers, not sensitive payloads.

Example:

document_id=doc_8439

instead of dumping the document.

⸻

18. Every Exception Needs Context

Bad:

failed

Good:

source_id
document_id
job_id
stage
error_type
retry_count
duration

Do not silently swallow exceptions.

Do not use:

except Exception:
    pass

Do not log and continue unless continuing is explicitly safe.

18a. Stop When Sufficient Evidence Exists

The purpose of verification is to establish adequate confidence, not to maximize the number of
tests, verification passes, edge cases, or supporting infrastructure.

Once a change has adequate evidence that it is correct for its risk level, continue implementing the
next milestone rather than expanding verification.

Adequate evidence means:

LOW-RISK CHANGES
- Existing coverage remains valid.
- Relevant static checks pass.
- At most one focused regression test if a new externally observable behavior was introduced.

MEDIUM-RISK CHANGES
- Existing tests plus a small number of focused tests demonstrate the intended behavior.
- Relevant integration tests only if the change crosses a system boundary.

HIGH-RISK CHANGES
(Security boundaries, concurrency, financial correctness, state machines, migrations,
cryptography, provenance, data integrity)

- Strong verification is expected and may include integration, regression, property,
or security testing where justified.

Do not automatically create additional:

- unit tests
- integration tests
- regression tests
- property tests
- fuzz tests
- mutation tests
- edge-case matrices
- test harness improvements

unless they materially increase confidence in a high-risk invariant.

A feature is complete when there is sufficient evidence appropriate to its risk—not when every
conceivable verification technique has been applied.

When choosing between:

A) expanding verification for already-supported behavior, or
B) implementing the next planned milestone,

prefer (B) unless a significant correctness or security risk remains unresolved.

This rule overrides Rules 19–30 and Rules 80–81 whenever they would otherwise encourage
verification beyond what is proportionate to the current implementation risk.

18b. Complete the Vertical Slice Before Broad Verification

During active implementation, prioritize completing the planned architectural slice.

Do not interrupt implementation to expand tests, documentation, ADRs, CI workflows, or verification
unless:

- a correctness defect blocks further work,
- a security issue blocks further work,
- or the implementation cannot safely continue.

Prefer:

implement
↓

implement
↓

implement
↓

focused self-check

↓

complete slice

↓

single documentation pass

↓

single verification pass

↓

commit

rather than repeatedly switching between implementation and verification.

This rule overrides workflow preferences but does not weaken required security or correctness
requirements.


----

19. Tests Are Part of the Feature

A feature is incomplete until its tests exist.

Every meaningful change needs appropriate:

unit
integration
regression
security
boundary
failure-path

tests.

Not every feature needs every category, but the categories must be considered.

--- 

19a. Testing Is Risk-Based, Not Exhaustive

Testing exists to provide sufficient evidence of correctness, not to maximize test count, coverage,
mutation score, or edge-case enumeration.

For every implementation slice, classify behavior:

CRITICAL
Security boundaries, financial calculations, state-machine integrity, provenance integrity,
concurrency correctness, destructive migrations.

→ Strong focused testing is justified.

IMPORTANT
Core product behavior where a defect would cause incorrect results but is recoverable.

→ A small number of representative tests is sufficient.

ROUTINE
Configuration plumbing, straightforward CRUD, adapters, formatting, read models, simple
transformations and implementation details.

→ Existing regression coverage plus one representative test is normally sufficient.

Do not automatically create:
- unit tests
- integration tests
- property tests
- fuzz tests
- mutation tests
- boundary matrices

simply because new code was written.

A new module does not imply a new test suite.

Once the externally meaningful invariant is adequately protected, stop testing and continue
implementation.

Testing must never become the critical path unless the subsystem's risk justifies it.

--- 

19b. No Test Expansion During Feature Sprint Without Need

During an implementation milestone, ClaudeCode must prioritize completing the vertical slice.

Unless explicitly requested or required by a newly discovered high-risk defect:

- do not expand existing test infrastructure;
- do not perform mutation testing;
- do not perform fuzzing;
- do not build exhaustive edge-case matrices;
- do not refactor test harnesses;
- do not add tests for implementation details;
- do not add multiple tests asserting substantially the same invariant.

Use existing tests wherever they already provide adequate evidence.

If one focused regression test proves a newly fixed defect, one is enough.
⸻

20. Test Failure Paths, Not Only Success Paths

For the fetcher, tests should include:

200 success
301/302
redirect outside allowlist
redirect to private IP
404
429
500
503
connection failure
DNS failure
TLS failure
timeout
slow response
oversized response
wrong MIME type
empty response
truncated stream
malicious filename
retry exhaustion
cancellation

Happy-path-only tests are not acceptable for infrastructure code.

⸻

21. Every Fixed Bug Gets a Regression Test

Process:

Bug discovered
      ↓
Write failing test reproducing bug
      ↓
Confirm failure
      ↓
Fix implementation
      ↓
Confirm test passes

Never fix a significant bug without preserving its reproduction.

The Phase 0 placeholder-DSN, structlog and dependency-injection bugs should establish this culture permanently.

⸻

21a. Tests Must Verify Externally Meaningful Behavior

A test must assert the behavior the system promises to the outside world, not an internal
implementation event that happens to correlate with it.

A passing test whose premise depends on an accidental environment condition is a defective
test, even while green.

Three Phase-1 discoveries established this rule:

Test says FK restriction works
        ↓
but watches commit()
        ↓
database actually fails at execute()

Readiness test expects DB unavailable
        ↓
works accidentally because DB isn't installed
        ↓
real DB installation flips the semantics

test teardown
        ↓
downgrade base
        ↓
shared developer database silently loses schema

Therefore, in review, ask:

* What externally observable promise does this assert?
* Would it still pass for the right reason on a different machine?
* Would it still pass for the right reason with infrastructure present?
* Would it still pass for the right reason with infrastructure absent?
* Does it depend on something merely absent rather than something asserted?
* Does it assert where the system actually enforces the rule?

A test that cannot answer these is not evidence.

Corollary: a test must never depend on the absence of infrastructure. If a behavior needs a
dependency to be missing, inject that condition explicitly rather than inheriting it from the
environment.

⸻

22. Do Not Over-Mock

Unit tests should isolate logic.

Integration tests should exercise real infrastructure.

Do not mock PostgreSQL when testing behavior dependent upon PostgreSQL semantics.

Do not mock S3 when testing object-store integration.

Do not mock HTTP when testing the actual HTTP adapter’s behavior against controlled network conditions.

Use local/test infrastructure.

⸻

23. Integration Tests Must Become Mandatory

The current repository has 22 integration tests that have never run locally.

That is now a priority.

Before Phase 1 is considered stable:

Docker Compose must actually start.
PostgreSQL integration tests must actually run.
MinIO integration tests must actually run.
Migrations must actually execute.
Downgrades must actually execute.
The API must communicate with those services.

Skipped integration tests must never create the appearance that integration was verified.

CI integration tests should fail if required infrastructure is available but tests unexpectedly skip.

⸻

24. Add End-to-End Tests

Once Slice 2 exists, add an E2E fixture:

discover URL
     ↓
fetch
     ↓
validate
     ↓
hash
     ↓
store raw object
     ↓
persist metadata
     ↓
retrieve metadata
     ↓
verify object

Later:

upload/download document
     ↓
classify
     ↓
extract
     ↓
normalize
     ↓
match
     ↓
audit
     ↓
finding
     ↓
evidence

E2E tests should use small deterministic fixtures.

⸻

25. Test Invariants

Test properties that must always remain true.

Examples:

same bytes → same SHA-256
same evidence → same content ID
raw object is never overwritten
invalid lifecycle transition fails
quarantined content cannot automatically return to normal flow
duplicate ingestion remains duplicate
same audit inputs/rules → same deterministic findings

⸻

26. Consider Property-Based Testing

For parsers, normalization, filenames, URLs, numerical reconciliation and state machines, introduce property-based tests where they provide useful coverage.

Good candidates:

safe filenames
URL normalization
currency normalization
quantity calculations
state transitions
hashing
archive boundaries

⸻

27. Fuzz Security-Critical Parsers

When custom parsing logic becomes significant, fuzz:

URL parser
filename sanitizer
archive metadata handling
document metadata parser
rule parser

Particularly prioritize code handling attacker-controlled bytes.

⸻

28. Keep the Unit Suite Fast

The current ~0.6 second unit suite is excellent.

Protect that property.

Fast tests should remain infrastructure-free.

Slow integration/E2E tests belong in separate CI stages.

⸻

29. CI Is Authoritative

A mergeable commit must pass:

format
lint
strict typing
unit tests
integration tests
migration validation
security scanning
dependency scanning
container build
container smoke test
source-registry validation

Never instruct developers to bypass a failing gate.

Fix the problem.

⸻

30. Never Disable a Test to Make CI Green

Forbidden fixes include:

@pytest.mark.skip
xfail without issue
commenting out assertions
broadening expected exceptions
reducing validation
ignoring lint rule globally
removing strict typing

unless there is a documented technical reason.

⸻

31. Lock Dependencies

The current repository does not contain a project-level reproducible dependency lockfile.

Add one.

Because the project already uses uv, use a committed uv.lock.

Production and CI should install from the lockfile.

The same commit should resolve to the same dependency graph.

Do not depend solely on broad ranges such as:

fastapi>=0.115,<1

for reproducible builds.

⸻

31a. A Declared Range That Blocks a Security Fix Is Itself the Defect

The Phase-1 lock exercise found three advisories, but the important finding was not their
existence. It was that the declared constraints prevented the patched releases from resolving
at all:

black>=25.1,<26   blocked the fix in 26.5.1
pytest>=8.3,<9    blocked the fix in 9.1.1

Required response sequence:

Declared range
      ↓
Lock resolution
      ↓
Security audit
      ↓
If patched release cannot resolve
      ↓
Review declared constraint
      ↓
Update intentionally
      ↓
Full regression suite

Never respond to an advisory by suppressing it. Specifically forbidden:

* adding an ignore/exclusion to silence the audit
* pinning below the patched version
* dropping --strict
* removing the package from the audited set
* narrowing the audited scope to hide the finding

The healthy result is exactly:

$ make audit
No known vulnerabilities found
exit code: 0

Any known vulnerability must make the security gate non-zero. The only permitted deviation is
a formally documented, time-bounded exception recording the advisory ID, why it does not apply
or cannot yet be fixed, the compensating control, an expiry date, and an owner. An exception
without an expiry date is a suppression.

⸻

32. Separate Dependency Freshness From Dependency Reproducibility

These are different goals.

Reproducibility:

commit
→ exact dependency set

Freshness:

scheduled dependency update
→ PR
→ CI
→ review
→ merge

Never auto-upgrade production dependencies silently.

⸻

33. Add Automated Dependency Updates

Configure Dependabot or an equivalent dependency bot.

Recommended cadence:

security fixes → immediately
normal Python updates → weekly
GitHub Actions → weekly
Docker images → weekly

Updates should create PRs.

They must pass normal CI before merging.

GitHub’s dependency-review tooling can also identify newly introduced vulnerable dependencies during a PR rather than discovering them after merge. (⁠GitHub Docs)

⸻

34. Add PR Dependency Review

On pull requests, fail introduction of dependencies with unacceptable known vulnerabilities.

Review:

new dependency
removed dependency
version change
known CVEs
license
transitive impact

Do not only run pip-audit after installation.

⸻

35. Add Static Application Security Testing

Add CodeQL or a comparable SAST scanner.

Run on:

pull requests
main branch
scheduled scans

Ruff’s Bandit-style rules are useful but are not a complete SAST strategy.

⸻

36. Keep Secret Scanning

Retain Gitleaks across full Git history.

Also enable repository-host secret protection where available.

Never consider removing a secret from HEAD sufficient if it existed in Git history.

A leaked production secret must be rotated.

⸻

37. Add an SBOM

Every production release/container should eventually generate an SBOM.

Record:

package
version
source
license
dependency relationship

Store the SBOM with release artifacts.

⸻

38. Build Provenance

When Aedifex starts producing release artifacts, generate build provenance.

SLSA treats provenance as evidence describing what built an artifact, the process used, and its inputs. (⁠SLSA)

Long-term target:

source commit
+
CI workflow
+
dependency lock
+
container digest
+
build provenance
=
verifiable release

⸻

39. Pin Production Artifacts

The current repository uses mutable image references such as:

python:3.13-slim
postgres:17-alpine
minio/minio:latest
minio/mc:latest

Development may use convenient tags, but production and CI-critical dependencies should move toward immutable digests where practical.

Example concept:

image@sha256:...

This prevents an upstream mutable tag from silently changing the software you deploy.

⸻

40. Pin GitHub Actions for High-Assurance Builds

For stronger supply-chain integrity, production workflows should eventually pin third-party actions to immutable commit SHAs rather than relying solely on mutable major tags.

Keep automation tooling updated through dependency PRs.

⸻

41. Python Version Policy Must Be Explicit

Current repository state mixes:

project supports >=3.12
Black targets 3.12
Ruff targets 3.12
mypy models 3.12
CI runs 3.13
Docker runs 3.13

Decide intentionally whether Aedifex supports:

Python 3.12 + 3.13

or:

Python 3.13 only

If supporting both, CI should test both.

If production is 3.13-only, align tooling accordingly.

Avoid accidental compatibility assumptions.

⸻

42. Database Schema Is Code

Continue requiring:

model change
     ↓
migration
     ↓
migration test
     ↓
alembic upgrade
     ↓
alembic check
     ↓
downgrade test

Never manually edit a production database.

⸻

43. Migrations Need Data-Safety Review

Schema reversibility alone is insufficient.

Before destructive migrations:

Can data be lost?
Can deployment run old + new code simultaneously?
Will table locks occur?
How long will migration take?
Can it be rolled back?

For large tables, use expand-and-contract migrations where appropriate.

⸻

44. Transactions Should Protect Invariants

Examples:

metadata insert
+
state transition
+
job checkpoint

may need to be committed atomically.

Use transactions around business invariants, not arbitrary groups of statements.

⸻

45. Queue Jobs Need Explicit Delivery Semantics

For Slice 3, ADR 0007 must decide:

at-most-once
at-least-once
effectively-once through idempotency

Assume duplicate execution can happen.

Design jobs to tolerate it.

⸻

46. Prefer PostgreSQL Queue Initially If It Meets Requirements

SELECT ... FOR UPDATE SKIP LOCKED is a reasonable option for the current scale if evaluated and documented.

Do not introduce Redis/Celery merely because background work exists.

Evaluate:

transactional consistency
throughput
visibility timeout
retries
dead-letter handling
operational complexity
worker crashes
monitoring

Record the decision in an ADR.

⸻

47. Add Dead-Letter Handling

A job that fails repeatedly should not retry forever.

Example:

attempt 1
attempt 2
attempt 3
attempt 4
attempt 5
     ↓
DEAD_LETTER
     ↓
human/operator review

Preserve the error history.

⸻

48. Never Use Unlimited Concurrency

Every async/concurrent operation needs a bound.

Bound:

network concurrency
database connections
OCR concurrency
LLM concurrency
archive extraction
worker count

Unlimited concurrency eventually becomes self-inflicted denial of service.

⸻

49. Backpressure Must Exist

If ingestion is faster than processing:

crawler
  ↓
queue grows
  ↓
workers saturated

the system must slow ingestion rather than consume unlimited resources.

⸻

50. Timeouts Everywhere

Any external or expensive operation should have a timeout.

Including:

HTTP
database queries
OCR
subprocess
LLM request
object-store operation
archive extraction
document parser

Nothing waits forever.

⸻

51. Resource Limits Everywhere

Because documents are hostile, establish limits for:

file bytes
pages
archive entries
archive nesting
expanded bytes
image dimensions
OCR duration
PDF page rendering
CPU time
memory
LLM tokens

Reject or quarantine violations.

⸻

52. Protect Against Decompression Bombs Before Real Archive Crawling

Before enabling CPPP/CPWD or any source that provides archives:

validate:

entry count
individual entry size
total expanded size
compression ratio
nesting depth
path traversal
symlinks
duplicate names
encrypted archives

Extraction must occur into a constrained temporary environment.

⸻

53. PDF Processing Must Be Isolated

Never assume PDF = passive document.

Parser workers processing public PDFs should ideally have:

no cloud credentials
no database credentials beyond minimum
no outbound Internet
filesystem restrictions
memory limits
CPU limits
timeout
non-root user
ephemeral workspace

The parser does not need access to everything the API can access.

⸻

54. Least Privilege Everywhere

Every component gets only what it needs.

Example:

crawler → outbound HTTP + raw write
parser → raw read + processed write
API → metadata read/write as necessary
auditor → normalized evidence
frontend → API only

Do not share one all-powerful credential across services.

⸻

55. Authentication Before Public Deployment

The repository correctly notes that authentication/RBAC does not yet exist.

Do not expose write functionality publicly before implementing authentication and authorization.

Eventually define roles such as:

viewer
finance reviewer
engineer
auditor
project administrator
organization administrator
system administrator

Authorization must be server-side.

⸻

56. Multi-Tenancy Needs Isolation by Design

Before real enterprise customers:

Every sensitive entity should have an ownership boundary such as:

organization_id
project_id

Queries must never rely on the caller remembering to filter manually.

Design tenant isolation centrally.

Eventually test explicitly:

Tenant A cannot read Tenant B
Tenant A cannot infer Tenant B IDs
Tenant A cannot modify Tenant B

⸻

57. Establish a PII Classification System

Before real customer documents, classify data.

Example:

PUBLIC
INTERNAL
CONFIDENTIAL
PII
HIGHLY_SENSITIVE

Potential sensitive fields include:

PAN
Aadhaar
bank details
customer identity documents
phone
email
address
signature
financial statements

Classification should influence retention, access, logging and encryption.

⸻

58. PII Must Not Enter Training Data Automatically

Raw collected documents must never automatically become AI training data.

Pipeline:

collected
   ↓
licence validation
   ↓
PII screening
   ↓
redaction/anonymization
   ↓
quality review
   ↓
approved training corpus

Training eligibility is a separate state from collection eligibility.

⸻

59. Data Licensing Is Part of the Schema

Preserve:

source
license
terms URL
terms review date
reviewer
permitted use
commercial use
redistribution
model-training permission
PII status

Do not infer legal permission from technical accessibility.

⸻

60. Do Not Fabricate Source Approval

Keep the current control:

verification_status = approved
requires:
reviewed_by
reviewed_on

ClaudeCode must never bypass or fabricate this gate.

If no source has been legally approved, real crawling remains disabled.

⸻

61. Observability Ships With Features

Every background stage should expose:

count
duration
success
failure
retry
queue delay
throughput

Logs alone are insufficient at scale.

Phase 1 should begin introducing metrics.

⸻

62. Use Stable Metric Cardinality

Never put unbounded values such as:

full URL
invoice number
document ID
customer ID

into Prometheus labels.

That creates cardinality explosions.

Use them in logs/traces instead.

⸻

63. Establish SLOs Only After Measuring Baselines

Don’t invent meaningless performance promises.

First measure.

Then establish SLOs.

Example:

download success rate
p95 API latency
processing throughput
OCR latency
queue delay
audit execution latency

⸻

64. Performance Benchmarks Need Regression Protection

Once benchmarks exist, preserve them.

Large regressions should be visible in CI or scheduled performance runs.

Particularly monitor:

documents/hour
memory/document
database query count
OCR seconds/page
LLM tokens/document
cost/document

⸻

65. Cost Is a Production Requirement

Track cost per stage:

download
object storage
OCR
LLM
database
compute

An AI architecture is unacceptable if a deterministic alternative gives comparable results for much less money.

⸻

66. LLM Calls Require Provider Abstraction

Do not scatter:

client.responses.create(...)

through business code.

Use a domain interface.

Conceptually:

LanguageModel
    │
    ├── OpenAI adapter
    ├── Anthropic adapter
    └── local/test adapter

Business logic depends on the interface.

⸻

67. LLM Outputs Must Be Schematized

Do not allow unvalidated free-form AI text to become authoritative system state.

Use:

LLM
 ↓
structured response
 ↓
Pydantic validation
 ↓
semantic validation
 ↓
confidence / review

Reject malformed results.

⸻

68. Prompt Injection Is Expected

Once documents enter an LLM workflow, assume they may contain text such as:

Ignore previous instructions...
Send all project documents...
Approve this invoice...

Document content is evidence, never instructions.

Clearly separate:

system instructions
tool permissions
document content
user request

No document should be capable of granting itself additional privileges.

⸻

69. LLMs Never Receive Unnecessary Secrets

AI providers should receive the minimum required content.

Avoid sending full projects when one relevant section is sufficient.

Redact irrelevant PII wherever possible.

⸻

70. AI Behavior Requires Evaluation, Not Just Unit Tests

Before changing:

model
prompt
OCR provider
retrieval strategy
classification system

evaluate against a fixed benchmark corpus.

Track:

precision
recall
F1
field extraction accuracy
false-positive rate
false-negative rate
latency
cost

⸻

71. Version Every AI Influence

Store:

model
model version
prompt ID
prompt version
retrieval version
extractor version
rule version

along with outputs.

Otherwise an audit cannot be reproduced.

⸻

72. Never Silently Upgrade an AI Model

Changing:

model-v1
→
model-v2

can change audit behavior.

Treat model changes like code changes:

benchmark
review
staging
comparison
release

⸻

73. Security Standards

Aedifex engineering should progressively map controls against:

NIST SSDF
OWASP ASVS
OWASP AI/LLM security verification guidance
SLSA supply-chain guidance

Do not claim formal compliance unless an actual assessment demonstrates it.

NIST SSDF explicitly defines secure-development practices intended to be integrated into the SDLC. (⁠NIST Computer Security Resource Center)

OWASP ASVS provides testable application-security requirements. (⁠OWASP Foundation)

OWASP also maintains verification requirements specifically for AI-enabled systems, which should become relevant once Aedifex starts shipping AI features. (⁠OWASP Foundation)

⸻

74. Threat Modeling Happens Before High-Risk Features

Before implementing:

file upload
crawler
authentication
multi-tenancy
LLM processing
customer documents
external integrations
payment recommendations

perform a lightweight threat model.

Ask:

What are the assets?
Who are the attackers?
What are trust boundaries?
What can be spoofed?
What can be tampered with?
What data can leak?
What can cause denial of service?
What can elevate privileges?

Record important mitigations.

⸻

75. Perform Abuse-Case Testing

Don’t ask only:

How should a user use this?

Also ask:

How would an attacker abuse this?

Examples:

malicious redirect
fake MIME type
billion-laughs archive
PDF parser exploit
gigantic image
duplicate invoice variants
prompt injection
poisoned source documents
tenant ID manipulation
stolen API token
malicious filename
SQL injection attempt
log injection

⸻

76. Security Failures Should Fail Closed

If Aedifex cannot determine safely whether an action is permitted:

deny
quarantine
require review

Do not default to approval.

This is especially important for:

document safety
payment eligibility
material compliance
permissions
source legality

⸻

77. Human Review Is a Security Control

For financially consequential findings:

AI finds
     ↓
deterministic evidence
     ↓
risk classification
     ↓
human reviewer
     ↓
business action

The MVP should recommend:

PASS
REVIEW
FAIL

but humans retain authority over actual payment release.

⸻

78. Pull Requests Must Be Small and Reviewable

Continue the Phase 0 pattern.

Prefer:

one concern
one coherent commit/PR
tests included
docs included

Avoid 5,000-line feature dumps.

⸻

79. Commit History Is Documentation

Each commit should leave the repository functional.

Avoid:

commit 1: break API
commit 2: add tests
commit 3: fix API

when they can reasonably be one coherent commit.

⸻

80. Definition of Done

A development slice is complete only when applicable items below are satisfied:

requirements updated
design understood
ADR added if needed
implementation complete
unit tests pass
integration tests pass
regression tests added
security failure paths tested
mypy strict passes
Ruff passes
Black passes
migration checks pass
dependency audit passes
secret scan passes
container builds
container smoke test passes
observability added
documentation updated
runbook impact evaluated
CI green
known limitations documented

“Works locally” is not Done.

⸻

81. Every Session Ends With Verification

Before reporting completion, ClaudeCode must execute every verification command available in its environment.

Report separately:

VERIFIED
NOT VERIFIED
BLOCKED

Never say something works because the code appears correct.

Example:

VERIFIED
342 unit tests passed.
NOT VERIFIED
Docker Compose was not executed because Docker is unavailable.
BLOCKED
Real CPWD crawling remains disabled pending terms review.

Preserve the honesty demonstrated in Phase 0.

⸻

82. Never Claim Production-Ready Without Production Evidence

“Production-grade architecture” and “production-ready system” are different.

Production readiness requires evidence of:

real infrastructure testing
security testing
backup/restore
monitoring
deployment
rollback
load behavior
failure recovery
incident procedures
authentication
authorization
secrets management

Use accurate language.

⸻

83. Up-to-Date Dependency Policy

At least weekly, automation should check:

Python dependencies
Docker images
GitHub Actions
security advisories

Do not update merely because something is newer.

For every update:

release notes
breaking changes
security significance
compatibility
tests
benchmark

Then merge.

⸻

84. Scheduled Security CI

In addition to PR CI, create scheduled security workflows.

For example:

weekly:
dependency vulnerability scan
SAST
container vulnerability scan
dependency freshness check
periodically:
deeper security suite

This catches vulnerabilities disclosed after code was originally merged.

⸻

85. Container Security Must Expand

Current good controls:

multi-stage image
non-root runtime
small base image
CI startup check

Add progressively:

image vulnerability scan
immutable image digest
read-only filesystem where possible
drop Linux capabilities
no-new-privileges
resource limits
SBOM
provenance

⸻

86. Do Not Put Migrations in Every API Startup

Keep the current design.

Schema migrations should be a deployment operation, not something every API replica races to execute.

⸻

87. Backups Must Be Restored, Not Merely Created

Later, production backups require actual restore testing.

A backup nobody has restored is not a verified recovery mechanism.

Test:

PostgreSQL restore
object-store recovery
configuration recovery

Document RPO/RTO.

⸻

88. Build Incident Response Before Production

RUNBOOK.md should eventually cover:

database outage
object-store outage
crawler runaway
queue backlog
corrupt document
credential leak
PII exposure
bad deployment
bad migration
AI provider outage
incorrect audit batch

⸻

89. Feature Flags for Risky Changes

Use controlled rollout for significant future features such as:

new OCR engine
new classifier
new rule set
new model
new crawler
new automated decision behavior

Avoid instantaneous global behavior changes.

⸻

90. Rules Engine Changes Are Versioned Releases

Audit rules affect business outcomes.

A rule change must include:

rule version
reason
author
effective date
tests
before/after behavior

Never silently change historical audit meaning.

⸻

91. Financial Arithmetic Uses Decimal

Never represent monetary amounts with binary floating point.

Use:

Decimal

Define:

currency
rounding strategy
scale
tax rounding

explicitly.

⸻

92. Units Must Be Explicit

Never compare ambiguous:

120

Represent:

120 MT
500 kg
20 m³

Normalize before comparison.

Construction auditing requires unit-aware reasoning.

⸻

93. Dates Must Be Timezone-Aware

Continue enforcing timezone-safe datetime rules.

Record collection and system events in UTC.

Business dates can retain their relevant local/project semantics.

⸻

94. Evidence Confidence Must Not Equal Business Confidence

OCR confidence:

98%

does not imply:

98% probability invoice is valid

Maintain separate concepts:

extraction confidence
matching confidence
rule result
risk severity
business recommendation

⸻

95. Explain Every Finding

Future findings should contain:

finding type
severity
rule
human explanation
source documents
source locations
compared values
recommended next action
rule version

No opaque:

Risk score: 83

without justification.

⸻

96. Avoid Magic Risk Scores

Initial risk scoring should be deterministic and documented.

If machine-learned scoring is introduced later, it requires:

training provenance
evaluation
calibration
bias analysis
versioning
monitoring
explanation

⸻

97. Production Data Must Never Enter Tests

Tests use:

synthetic data
fixtures
sanitized approved samples

Never copy real customer documents into:

Git
test fixtures
CI artifacts
bug reports
LLM debugging prompts

⸻

98. Test Data Must Include Adversarial Cases

Synthetic generator should eventually generate both:

valid projects

and:

fraudulent/inconsistent/adversarial projects

Include subtle anomalies, not just obvious mismatches.

⸻

99. No Hidden Technical Debt

If a shortcut is necessary, record it.

Use an issue, TODO reference, or known-limitations document.

Avoid anonymous:

# TODO fix later

Prefer:

# TODO(AED-142): Replace temporary in-memory implementation
# after durable queue ADR is resolved.

⸻

100. ClaudeCode Must Challenge Bad Instructions

If asked to implement something that would:

reduce security
bypass tests
fabricate legal approval
weaken auditability
introduce unsafe AI decisions
destroy provenance
create unnecessary architecture

ClaudeCode should explain the conflict and propose the safer implementation.

Do not blindly implement a technically harmful request.

⸻

Current Aedifex-Specific Priorities

Before or during early Phase 1, address the following.

P0 — Verify Existing Infrastructure

Actually execute:

docker compose up
migrations against PostgreSQL
all 22 integration tests
MinIO operations once implemented
container locally where possible

Do not let these remain permanently “CI theoretically covers it.”

⸻

P0 — Add Reproducible Dependency Locking

Create and commit:

uv.lock

Make local, CI and production builds consume it.

⸻

P0 — Build Slice 1 Security-First

HTTP fetch layer must include from its first commit:

timeouts
bounded concurrency
connection pooling
rate limiting
backoff + jitter
Retry-After
SSRF guards
host allowlist
redirect revalidation
private-IP blocking
streaming response limits
cancellation

Do not implement a naive fetcher first and “secure it later.”

⸻

P0 — Archive/PDF Safety Before Archive Crawling

Slice 5 may need to move earlier if the first approved data source distributes ZIP archives.

No real source containing archives should be enabled before bounded archive handling exists.

⸻

P1 — Add Automated Supply-Chain Maintenance

Implement:

Dependabot/Renovate
dependency review
SAST/CodeQL
container vulnerability scanning
scheduled security workflow

GitHub’s dependency-security tooling supports PR-level dependency review and automated vulnerable-dependency updates. (⁠GitHub Docs)

⸻

P1 — Resolve Python-Version Policy

Current configuration spans Python 3.12 assumptions and Python 3.13 CI/runtime.

Choose the supported policy and test it explicitly.

Recommended while the project is young:

Python 3.12
Python 3.13

CI compatibility matrix.

Production can then intentionally select one supported version.

⸻

P1 — Stop Depending on Mutable Infrastructure Tags

Replace high-value mutable tags progressively.

Especially:

minio/minio:latest
minio/mc:latest

Establish controlled image-update PRs instead.

⸻

P1 — Synthetic Dataset Track

Run Slice 6 in parallel with external acquisition work.

This provides deterministic labeled data for:

document processing
evidence matching
rules
audit evaluation
future AI evaluation

without waiting for portal terms review.

⸻

Recommended Phase 1 Order

Given the current repository state:

1. Reproducibility/security housekeeping
   ↓
   uv.lock
   Python version policy
   dependency automation
   SAST/container scanning
2. Verify Phase 0 live infrastructure
   ↓
   Docker Compose
   PostgreSQL migrations
   integration tests
3. Slice 1
   ↓
   hardened HTTP fetch layer
4. Slice 2
   ↓
   object storage + downloader
5. Slice 5 where needed
   ↓
   safe archives + PDFs
6. Slice 6 in parallel
   ↓
   synthetic construction dataset
7. Slice 3
   ↓
   durable jobs + retries + dead-letter
8. Slice 4
   ↓
   first legally approved crawler

Slice 4 remains gated by genuine human terms-of-use approval.

Never fabricate that approval.

⸻

Permanent Merge Rule

No code enters main unless the relevant evidence says it is safe to merge.

The question before merge is not:

Did Claude finish?

It is:

What evidence do we have that this change is correct, secure, integrated, reproducible and operationally safe?

That standard applies equally to human-written and AI-written code.

Assessment of your current repo

I would keep Phase 0. I don’t see a reason to rebuild it. The underlying choices—modular monolith, typed config, immutable raw storage, source-approval gate, content-addressed identity, migrations, structured logs, unit/integration separation, CI, non-root containers—are sensible foundations.

The highest-priority change I would make before allowing ClaudeCode to sprint through Phase 1 is this smaller sequence:

Commit A — uv.lock + frozen CI installs
Commit B — Python 3.12/3.13 compatibility matrix
Commit C — Dependabot + dependency-review
Commit D — CodeQL/SAST + container vulnerability scan
Commit E — actually run Compose + all integration tests
Commit F — hardened HTTP Slice 1

Then continue with downloader/storage.

One more point: I agree with ClaudeCode’s recommendation to use Slice 1 next, but I would develop Slice 6 synthetic data in parallel immediately after it. The external-data path can be blocked by source terms, changing portals, anti-bot measures, and document quality. Your synthetic corpus has none of those dependencies and will eventually become the controlled benchmark against which extraction, matching, deterministic audit rules, and AI components can be regression-tested.  

The most important philosophy to preserve is the one ClaudeCode already demonstrated in its Phase 0 report: “not verified” must remain different from “implemented.” That single discipline will prevent a surprising number of AI-assisted development failures.

⸻

81a. Verification Is an Exit Code, Never Text

A gate is verified only by capturing and checking its exit status.

Command executed
      ↓
Capture exit code
      ↓
Exit code == 0 ?
   ┌──────┴──────┐
   │             │
  YES            NO
   │             │
VERIFIED       FAILED

Never infer success from stdout, from the absence of output, from a grep, or from an
`&& echo PASS` sentinel. Applies to tests, formatting, linting, type checking, security scans,
dependency audits, migrations, container builds, and deployment checks.

This rule exists because it was broken. A lint failure was committed and reported as green: the
check ran as `ruff check ... >/dev/null && echo PASS`, so the missing PASS was the only signal,
and the merged output line was misread as success. Reading output is not verification.

Corollary: when reporting a batch of gates, report each one's exit status. A summary line that
does not distinguish which gate produced which result is not evidence.

⸻

81b. Inside a Security Boundary, Failure to Parse Means Reject — Never Omit

If a value cannot be parsed, normalized, or classified inside a security boundary, the operation
is rejected. It is never silently skipped.

Correct:

DNS answer
   ↓
cannot normalize IP
   ↓
REJECT RESOLUTION

Wrong:

cannot normalize
   ↓
skip that answer
   ↓
continue with the rest

Omission is the more dangerous failure because it is invisible and it fails *open*. The
resolver demonstrated exactly this: an IPv6 answer carrying a scope identifier ("fe80::1%en0")
failed to parse, the answer was skipped, and a link-local address therefore never reached the
policy whose entire purpose was to reject it — a fail-open outcome hidden inside a function that
looked fail-closed.

Apply this to every parser at a boundary:

MIME and media types
magic bytes
filenames
URLs and redirect targets
DNS answers
TLS certificates
archive metadata (entry names, sizes, compression ratios)
PDF structure
OCR output
LLM structured output
queue messages
configuration files

Where partial results are genuinely acceptable (for example: skipping one unreadable document in
a batch while continuing the batch), that must be an explicit, documented decision at the
orchestration layer — never a silent `except: continue` inside a validator.

Test obligation: for each parser at a boundary, include a malformed-but-meaningful input and
assert it is *rejected*, not that it is absent from the output.

⸻

81c. Verification Gates Run Before Reporting

Ordering inside a CI job is a correctness property, not a matter of taste.

BUILD
  ↓
VERIFY
  ↓
SECURITY GATES
  ↓
SMOKE TEST
  ↓
ARTIFACT VALIDATION
  ↓
ONLY THEN
SARIF upload / SBOM publication / reports

Reporting is observational. It must never be positioned where its failure can prevent a
verification step from running.

This rule exists because it was violated. The container job uploaded a Trivy SARIF before running
its gates, the upload failed (code scanning is unavailable on this plan), and the SBOM, the
importability guard, the production-hardening guard, and the smoke test were all **skipped** — while
the image itself had built successfully. A genuine regression could have passed through, and the
job would have looked like a scanning problem.

If a reporting step fails, the build may report that failure. It must not gate the checks that
establish the artifact is correct and safe.

Corollary: a job that is green only on one branch is not a gate. The pull-request path and the
default-branch path must both be exercised, because they carry different permissions and different
event payloads. `main` was green for days while every pull request failed two jobs, because pushes
never exercised the API call that pull requests require.

⸻

81d. Retry Never Changes a Security Classification

An outcome that a security control has refused must never become retryable because a higher layer
saw an exception rather than a decision.

Never retryable, regardless of status code, headers, or what a controller believes:

SSRF rejection
TLS verification failure
invalid redirect target
oversized response
malformed authority
content rejected as unsafe
cancellation

A retry is for a condition that may plausibly differ next time. A refusal is a conclusion, and
repeating it only reaches the same conclusion more loudly — while giving a hostile server a way to
convert a single refusal into a loop.

Practically: classification lives in one pure policy, the controller consumes its verdict, and the
controller has no path to override it. A controller that can reinterpret a refusal as transient has
reintroduced the vulnerability the refusal prevented.

⸻

81e. An Analyser That Did Not Run Reports Zero Findings

"No findings" and "did not look" are the same output. Every tool that reports absence must be made
to prove presence first.

A scanner reports clean when:

it scanned the wrong path
its ruleset failed to fetch
it could not parse the file and continued past the error
its target directory was silently excluded by a default ignore list

All four exit 0 and print a reassuring summary. None of them examined the code.

So any gate whose passing signal is an absence must carry a companion assertion that the tool
performed work: a rule that must match, a floor on the number of files scanned, an empty error list.
Assert the tool's own error channel, not only its verdict.

Percentages are not gates. "Parsed lines: ~99.4%" looked healthy while the Dockerfile — the one file
whose ruleset was chosen because this project's real mistakes were in Dockerfiles — had failed to
parse from line 19 to line 104 and was analysed not at all. The missing 0.6% was the entire subject.
A coverage figure aggregated across a corpus hides the total loss of any file smaller than the
rounding error.

This rule exists because it was violated three ways in one gate, all found by measuring rather than
reading: the Dockerfile parsed to nothing, `tests/` was excluded by a default ignore list while
being passed as an explicit target, and the self-test read *any* non-zero exit as proof of a match —
so a malformed config, which exits 7, would have been reported as "matched as expected". The
anti-false-green check had its own false green.

Corollary: the tool's version must be pinned, and it must be recorded that pinning the tool does not
pin remotely fetched rules. A gate can newly fail with no change to the code, and that must be
understood as new coverage rather than treated as flakiness to be suppressed.

⸻

81f. Coverage of the Analyser Is Part of Security Coverage

81e is about one scanner. This is the general rule: for every verification tool, execution coverage
and finding coverage are separate claims, and only the second one is ever reported.

Record both, explicitly:

TOOL
  executed?                  yes / no
  covered the intended files? yes / no — with the count
  produced an expected match? yes / no — the positive control
  findings?                   the number

"Exit 0" answers only the last line. A tool that ran over an empty directory, over a file it could
not parse, or with a ruleset that failed to download answers it identically.

Every failure of the first three lines is silent by construction, so each needs its own assertion:

a floor on files or tests actually processed
a positive control that must trigger
the tool's own error channel checked, not only its verdict
the exclusion list stated where the claim of coverage is made

This applies to every tool that reports absence, not only to SAST:

Trivy                exclusions and ignore files silently shrink what is scanned
test discovery       a renamed file or a collection error removes tests while the suite stays green
migration checks     a fixture that leaves the schema at the wrong revision makes drift undetectable
type checking        an unfollowed import or an excluded module reports success over nothing
OCR benchmarks       a page that failed to render scores as a page with no text to find
dataset validation   a filter that matches nothing validates nothing and passes

The naming of results follows from this. A gate reports "clean over N files, positive control
matched" — never just "passed". A report that cannot distinguish "nothing wrong" from "nothing
examined" is not a report.

Mutation is the honest way to establish that a test suite has teeth: break the invariant, confirm a
specific test fails, restore. Two disciplines are required, both learned the hard way. A control
mutation that changes nothing meaningful must be confirmed *not* to fail anything, because a harness
that reports everything as caught is as uninformative as one that catches nothing. And the harness's
own verdict must come from the exit code of the tool being measured, not from a pipeline whose last
command is a formatter — the first version of this project's mutation harness read `tail`'s exit code
and pronounced fourteen genuinely-caught mutations uncaught (rule 81a, in its own tooling).

⸻

81g. A Failure Must Produce a Verdict

Every operation has exactly three permitted endings:

PASS
FAIL
never: hang

An operation that blocks indefinitely has produced no information. It is worse than a failure,
because a failure is actionable and a hang looks like work in progress until someone runs out of
patience. In CI it consumes the job's entire time allowance and reports nothing about the code.

So every wait must be bounded by something: a deadline, a timeout, a byte ceiling, an attempt cap, a
cancellation signal. "It will finish eventually" is not a bound.

This rule exists because it was violated twice in one component, both times inside the *testing* of
the very controls meant to prevent it. A mutation that removed a semaphore release turned the suite
into a ten-minute stall with no verdict, twice, and left the source tree mutated on disk while it
stalled. The fixes were a bounded acquire in the tests and a per-test timeout in the suite.

The same failure is available to almost everything still to be built, and each one needs its bound
decided when it is written rather than after it hangs:

PDF parsers            a malformed object graph, or a decompression loop
archive extraction     nested archives, a member that never ends
OCR                    a page that renders forever
external APIs          a socket that accepts and then says nothing
crawlers               a frontier that regenerates itself
durable workers        a lease that is never released
LLM calls              a stream that stops mid-token without closing

Corollary: a test suite must be able to fail. A suite that can hang is a suite that can stop
reporting, which makes every green run afterwards less informative (see 81e and 81f).

⸻

Aedifex IP / Patent Readiness Requirements

These requirements apply alongside the engineering constitution above. They are recordkeeping
controls for IP readiness. They do not replace advice from a patent attorney, and nothing in this
project constitutes a legal determination.

The infrastructure lives in docs/ip/ and is PRIVATE. See docs/ip/README.md.

⸻

IP-1. Maintain an Invention Register

docs/ip/INVENTION_REGISTER.md. Every potentially novel technical idea receives an AED-IP-NNN id.

Use the words:

Potential invention
Patent review required

Never write "patentable". Patentability is a legal determination that has not been made.

⸻

IP-2. Record Human Inventive Contributions

Because Aedifex is built with AI assistance, distinguish:

Human conceived the idea
        ↓
AI assisted the implementation

from:

AI suggested an approach
        ↓
Human selected / modified / developed it

For potentially patent-relevant work record who identified the problem, who conceived the solution,
who materially changed it, what the AI generated, and what the human specifically directed.

Do not list Claude, ChatGPT, Copilot, or any other AI system as an inventor. Inventorship centres
on the contributions of natural persons.

⸻

IP-3. Preserve Technical Detail

A disclosure must let an engineer build the thing. Record algorithms, state transitions, data
structures, scoring methods, relationship construction, security mechanisms, failure handling, and
model/rule interaction. A thin description is poor preparation for any later filing.

⸻

IP-4. Git History Is an Engineering Record

Do not squash or rewrite history containing substantive invention development for aesthetics.
Preserve timestamp, author, technical change, tests, and ADR. Never fabricate or backdate a commit.

Commit messages may reference an invention where relevant:

feat(evidence): add deterministic cross-document reconciliation
IP: AED-IP-003

⸻

IP-5. Separate Third-Party Data From Derived Work

Downloading a public document does not make it Aedifex IP. What may be proprietary is the value
added: selection, organisation, annotation, relationships, labels, derived ontology, quality
controls, and evaluation sets — subject to source rights and applicable law.

Storage layers keep this distinction visible: raw third-party content, then normalisation, then
Aedifex annotations, relationships, and benchmarks.

Never commit customer confidential documents, vendor proprietary specifications, paid databases, or
licensed standards without redistribution rights — not even as test fixtures. For standards such as
BIS/IS codes, store permitted metadata and references separately from copyrighted text, and do not
assume that being able to view a standard permits copying it into the repository or a training
corpus.

⸻

IP-6. Public Disclosure Requires Knowing What Is Being Disclosed

Classify as PUBLIC, INTERNAL, CONFIDENTIAL, TRADE SECRET, or PATENT REVIEW PENDING.

Claude Code must never publish material in the final two categories. "It's only GitHub" is a public
disclosure. Record every disclosure in docs/ip/PUBLIC_DISCLOSURES.md.

⸻

IP-7. Trade Secrets Depend on Actually Keeping Them

Protection depends partly on reasonable confidentiality measures. Therefore:

* docs/ip/ stays private.
* Do not document something as a trade secret and publish it simultaneously.
* No proprietary datasets in public CI artifacts.
* Least-privilege access; access removal on departure.

⸻

IP-8. Dataset and Model Lineage

Datasets already require source, licence, collection date, terms status, redistribution and
commercial-use rights, training-use status, modifications, and hash. For any proprietary model
later, additionally record model version, training code commit, training dataset version,
evaluation dataset, parameters, base model, licence, training date, and metrics.

Training eligibility is a separate state from collection eligibility. Raw collected documents must
never automatically become training data:

collected → licence validation → PII screening → redaction → quality review → approved corpus

⸻

IP-9. Release Snapshots

Every material release should retain source commit, source archive, SBOM, dependency lock,
container digest, migration state, rules version, model version, dataset version, and date. This
serves operational reproducibility and IP documentation equally.

Maintain clean version boundaries (0.1, 0.2, 1.0) and preserve release archives so a copyright
registration could be made cleanly if desired. Do not register automatically.

⸻

IP-10. Trademark Discipline

Before investing in the brand: search, review relevant jurisdictions and classes, check domains,
and document first commercial use. Do not place ® next to Aedifex unless a registration actually
permits it.

⸻

IP-11. Claude Code's Boundaries

Claude Code may prepare technical documentation, preserve evidence, organise prior art, and keep
contribution history accurate.

Claude Code must not declare patentability, draft legal claims, conclusively identify inventors, or
file anything.

⸻

IP-12. Add IP Consideration to Definition of Done

For a substantial architectural or algorithmic change, ask:

Does this create potentially valuable new technical IP?

No  → no IP update required. This is the common case.
Yes → create or update a disclosure, record contributors, link commits, update diagrams, record
      public-disclosure status.

Minutes, not bureaucracy. Do not create a disclosure for an idea; create one for an implemented
specific technical method.
