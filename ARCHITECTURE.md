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

## Aedifex acquires evidence; crawling is one way in

Not a crawler. An **evidence acquisition platform**, and acquisition is the broader word on purpose.
A document may arrive from a public procurement portal, a manual upload, a customer export, an email,
an ERP system, cloud storage or an API. **Every path converges into the same immutable pipeline**, and
the pipeline begins only once a document has been acquired.

Origin affects **provenance** and nothing else. A retrieval records a URL, an HTTP status and a
fetched-at time; an upload records a path, an uploader and an uploaded-at time. Downstream — text,
facts, calculation, rules, findings, the API — must not be able to tell the difference, because a
measurement is a measurement whether it was crawled or handed over.

That holds today, with the boundary in two places worth naming. `StorableFile` is a Protocol rather
than the acquisition layer's download type, so storing an uploaded file needs no fabricated HTTP
fields — the widening also removed the storage layer's dependency on the acquisition layer. And
`_document_origins` in [extraction/projects.py](src/aedifex/extraction/projects.py) unions retrievals
and uploads so neither path is privileged. That helper exists because the second query in the same
file once joined retrievals alone: filtered to an uploaded document's own source it saw zero of five,
so the one number whose job is to report what was overlooked had itself overlooked an entire
acquisition path.

Two streams are expected to meet in one evidence graph. Public crawlers supply **procurement context
and reference data**; customer-provided post-award records supply the **operational evidence** that
payment verification needs. Strengthening acquisition interfaces and business-object modelling is
therefore worth more than adding public crawlers.

## Two kinds of statement, and why they cannot share a table

A document states facts **about itself** and norms **about others**, and the difference is not
cosmetic. The NHAI Works Manual settled it: clause 4.14.1 reads *"two percent of the estimated cost
for works up to Rs. 20 crore"*, and a reader tuned on tenders recorded
`estimated_cost = ₹20,00,00,000` as a fact about a 297-page procedure manual — then cited it as
evidence in a finding. **A quoted amount inside a reference document is not a fact about that
document.**

So there are two types, not one with a flag:

| | `ExtractedFact` | `PolicyProvision` |
| --- | --- | --- |
| Answers | what does this document state about itself | what rule does this document impose on others |
| Has | a subject — the document it describes | an authority, a jurisdiction, an effective date, an applicability band |
| Lacks | applicability; a fact applies to nothing but itself | a subject; a norm is about whoever meets its condition |

Two consequences hold throughout. **Extractors on reference documents require positive evidence of
self-metadata** before emitting a document-scoped fact — the test is whether the document names the
procurement it concerns, one positive signal rather than an endless list of policy-language patterns.
And **a provision is a third kind of citable evidence**, alongside facts and derived facts, under a
check constraint permitting exactly one. The CLI labels it `policy` rather than `evidence` so a
reader can tell a cited threshold from a cited measurement.

## Reference data and project data

The useful axis is not public versus private. It is **shared across many projects** versus **specific
to one**.

| | Examples | Why it matters |
| --- | --- | --- |
| **Reference data** | Tender notices, BOQs, standard specifications, Schedule of Rates, material specifications, government circulars, contract clauses, procurement rules | Context, standards and baseline expectations. One document informs many projects |
| **Project data** | Contract agreement, Measurement Book, RA Bill / IPC, variation orders, site instructions, inspection reports, payment certificates, test reports, daily logs | The record of what happened on one job. This is what payment verification consumes |

**The current model holds project data and structurally cannot hold reference data**, and the reason
is worth stating precisely because it is not a bug. A document joins a project through an identifier
it states about *itself* — a tender number, a contract reference — and rules compare facts only
within one project, so that two projects quoting identical figures have nothing to say about each
other. That strict scoping is exactly what makes cross-document comparison safe.

Reference data has no such identifier by nature. A Schedule of Rates belongs to no tender and must be
comparable against *many* projects' bills. Under the present rules it would land in
`documents_without_project_key` and be invisible to every rule.

**Project scoping will not be weakened to fix that.** The design is settled even though nothing is
built: reference evidence reaches a rule through **explicit, evidence-backed applicability**, never
through global visibility —

```text
project evidence  +  applicable reference evidence  ->  rule evaluation
```

Applicability is a provenanced claim that a given reference document governs a given project, and may
later be expressed through jurisdiction, issuing authority, contract type, effective date, project
type, or an explicit operator link. A "global document" flag is rejected: it is one boolean that
discards the isolation invariant for every rule at once, and it is the fix a future contributor is
most likely to reach for. See
[ADR 0014](docs/adr/0014-reference-data-by-explicit-applicability.md) for the alternatives and why
each fails.

Deliberately unresolved beyond that. `project_documents` is already a join table, so the schema
permits one document in many projects and no migration is implied. Which applicability dimensions are
needed, and whether they are columns, relationship types or predicates, is a question one real
Schedule of Rates required by an actual rule would settle — and that reasoning will not.

## Layers

```
Project data room  (contracts, BOQs, POs, invoices, challans, GRNs, MTCs, IRs, COs)
        │
        ▼
Acquisition            crawl → download → validate → hash → deduplicate → store
        │
        ▼
Document intelligence  classify → extract (typed, with provenance); OCR is one extractor
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
Findings               PASS / REVIEW / FAIL / INCONCLUSIVE, each citing its evidence
        │
        ▼
Human review           accepted / rejected / needs_evidence, append-only and attributed
        │
        ▼
Business decision      off-platform, and the only place judgement is final
```

**There is no risk engine, and its absence is deliberate.** An earlier version of this diagram had
one, producing a "weighted, explainable score". A score is the opposite of explainable: it collapses
the five things a reviewer needs — what is wrong, which values were compared, under which rule, where
each came from, what to look at next — into one number nobody can argue with. Findings carry those
five; nothing multiplies them together.

Data flows one way. A lower layer never imports from a higher one.

## Module boundaries

```
src/aedifex/
  config.py          typed settings; the only reader of the environment
  errors.py          exception hierarchy
  domain/            shared vocabulary. Imports nothing but errors.
  acquisition/       registry, content validation, crawlers, downloaders
  extraction/        classify → extract → persist facts; the analysis pipeline
  calculation/       derived facts, precision-aware row arithmetic
  verification/      deterministic rules, single- and cross-document
  review/            what a person concluded about a finding
  workspace/         the product surface: declare a project, attach documents, read state back
  classification/    proposes a document type; never decides one
  infrastructure/    database, storage, observability adapters
```

``workspace/`` sits above ``verification/`` and ``review/`` and is imported by nothing but
``apps/``. It orchestrates and projects; it extracts nothing, judges nothing, and stores no fact of
its own, which is what keeps "the product workflow" from becoming a second pipeline.

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
| HTTP fetch: SSRF guard, retries, redirects, rate limits | [acquisition/fetch/](src/aedifex/acquisition/fetch/) |
| Downloader, object storage, retrieval provenance | [download.py](src/aedifex/acquisition/download.py), [storage/objects.py](src/aedifex/infrastructure/storage/objects.py), [provenance.py](src/aedifex/acquisition/provenance.py) |
| robots.txt, frontier queue, discovery, crawl runner | [acquisition/crawl/](src/aedifex/acquisition/crawl/) |
| Corpus catalog and operational metrics | [catalog.py](src/aedifex/acquisition/catalog.py) |
| Operator entry point | [apps/crawler/main.py](apps/crawler/main.py) |
| Bounded PDF text extraction | [extraction/pdftext.py](src/aedifex/extraction/pdftext.py) |
| Indian money parsing, NIT field extraction | [extraction/quantities.py](src/aedifex/extraction/quantities.py), [extraction/tender_notice.py](src/aedifex/extraction/tender_notice.py) |
| Facts, findings, evidence links | [extraction/store.py](src/aedifex/extraction/store.py), `extracted_facts` / `findings` / `finding_evidence` |
| Deterministic rules and registry | [verification/](src/aedifex/verification/) |
| Analysis pipeline | [extraction/runner.py](src/aedifex/extraction/runner.py) |
| Shared fact model, relationship vocabulary | [domain/evidence.py](src/aedifex/domain/evidence.py) |
| Projects, membership, document relationships | [extraction/projects.py](src/aedifex/extraction/projects.py), `projects` / `project_documents` / `document_relationships` |
| Cross-document rules | [verification/cross_document.py](src/aedifex/verification/cross_document.py) |
| Calculation layer, derived facts | [calculation/engine.py](src/aedifex/calculation/engine.py), `derived_facts` / `derived_fact_inputs` |
| Knowledge registry | [knowledge/registry.py](src/aedifex/knowledge/registry.py), `GET /v1/knowledge` |
| Local-file ingestion, upload provenance | [extraction/ingest.py](src/aedifex/extraction/ingest.py), `document_uploads` |
| Construction spreadsheet reader | [extraction/spreadsheet.py](src/aedifex/extraction/spreadsheet.py) |
| Priced bill of quantities reader (PDF) | [extraction/pdf_boq.py](src/aedifex/extraction/pdf_boq.py) |
| Policy provisions: norms stated by reference documents | [extraction/policy.py](src/aedifex/extraction/policy.py), `policy_provisions` |
| Explicit reference-data applicability | [extraction/applicability.py](src/aedifex/extraction/applicability.py) |
| Reference-policy rule | [verification/reference_policy.py](src/aedifex/verification/reference_policy.py) |
| Bill total reconciliation rule | [verification/bill_total.py](src/aedifex/verification/bill_total.py) |
| Work items, deterministic item linkage | [extraction/work_items.py](src/aedifex/extraction/work_items.py), `work_items` |
| Payment reconciliation rules | [verification/reconciliation.py](src/aedifex/verification/reconciliation.py) |
| Document version state, supersession | [extraction/supersede.py](src/aedifex/extraction/supersede.py), `documents.version_state` |
| Deterministic evidence selection | [extraction/selection.py](src/aedifex/extraction/selection.py) |
| Human review of findings | [review/](src/aedifex/review/), `finding_reviews`, `POST /v1/findings/{id}/reviews` |
| Project workspace: declare, upload, process, read back | [workspace/](src/aedifex/workspace/), `POST /v1/projects`, `POST /v1/projects/{id}/documents`, `/process`, `/summary` |
| Deterministic document-type suggestion | [classification/](src/aedifex/classification/), `documents.suggested_document_type` |
| Product-facing status and workflow categories | [domain/workflow.py](src/aedifex/domain/workflow.py) |
| Artifact content, digest re-verified on the way out | `GET /v1/documents/{id}/content` |
| Review workspace (React, TypeScript, Vite) | [frontend/](frontend/) |

The pipeline is complete end to end and has been run against a real portal. NHAI's terms were
reviewed and recorded (ADR 0006, rule 60), its tender API was reverse-engineered from the portal's own
JS bundle, and a bounded crawl acquired real tender documents into immutable storage with provenance.
Those documents then went the rest of the way: bounded text extraction, field extraction with page
spans, facts and findings in PostgreSQL, a deterministic rule, and a result readable over CLI and API
whose evidence points back at the page it came from.

Running that path over real data, rather than over fixtures, is what has found every defect worth
finding. The clearest example: the corpus's one real priced bill of quantities reported line items
summing 1.3% above the total the document states for itself. The gap was entirely ours — a credit row
written in accounting parentheses that the reader could not see, and two items priced through
sub-items that it refused. Both are now read, and the bill reconciles to ₹0.00 across 37 rows.

The general lesson is worth more than the fix. **The checks that detect a defective document are the
same checks that detect a defective extraction**, and there is no way to tell which you are looking
at from the number alone. So arithmetic self-consistency is checked twice over — within each row by
[extraction/pdf_boq.py](src/aedifex/extraction/pdf_boq.py), and across the whole bill by
[verification/bill_total.py](src/aedifex/verification/bill_total.py) — and the cross-bill check
returns REVIEW rather than FAIL, because asserting that a real tender contains an arithmetic error is
a claim this project usually cannot support.

One property of that path is worth stating because it was nearly got wrong. A rule's threshold is
**evidence, not configuration**. The first notice read implied a 2% bid security; hardcoding it would
have failed a legitimate tender whose own Instructions to Bidders prescribe 1%. So the prescribed rate
is extracted as a fact with its own page and span, supplied to the rule as an input, and where no rate
can be sourced the rule measures the ratio and returns `INCONCLUSIVE` rather than inventing a
threshold to judge against.

Documents are no longer reasoned about in isolation. Two documents belong to one **project** when
both state the same tender identifier — exact string equality on an extracted fact, so the grouping
is evidence rather than inference — and their relationship is stored as a row carrying what
established it. A cross-document rule then compares facts across them and produces a finding scoped
to the project, because "these two documents disagree" is not a fact about either one. Verified on
two real NHAI documents of one tender: two files, one stored relationship, one finding whose evidence
cites a page in each.

A disagreement is **reported, never resolved**. The rule has no basis for deciding which document is
right, so it states both values, cites both spans, and stops. And a project with nothing stated twice
returns `INCONCLUSIVE`: nothing compared is not a pass.

Between facts and rules sits a **calculation layer**, and the boundary around it is hard: it turns
facts into derived facts and cannot produce a verdict, because `PASS`, `FAIL` and `INCONCLUSIVE` do
not appear in it and its return type has nowhere to put them. That is what makes a derived fact
reusable — `bid_security_share` is true whether the prescribed rate is 1%, 2%, or unsourced, and two
rules already consume the same stored row to reach different kinds of conclusion. Each derived fact
records its inputs, its calculation and version, and the arithmetic as text, so the number can be
redone by hand from the row alone.

Evidence therefore comes in two kinds, and they are never conflated: a finding cites exactly one of
an extracted fact or a derived fact per slot, enforced by a check constraint. Both are citable, but
nobody wrote the computed one down, so the CLI labels them `evidence` and `derived` and the API sets
`origin`.

Above projects sit **work items** — the thing a payment claim is actually about. A bill of
quantities, a measurement book and a running bill each make statements about "item 4.7.2"; until
those are attached to one object there is nothing to reconcile. Attachment is deterministic: an exact
item identifier, then a normalised form of it, with every link recording which layer matched so a
weaker match is visibly weaker in the database.

That completes the first post-award workflow. Contracted 500 m³, measured 470 m³, claimed 520 m³
produces a variance of +50 m³, an unsupported amount of ₹400,000 at the contracted rate, and a
`REVIEW` — with each number citing a named cell in a named file. `REVIEW` rather than `FAIL` because a
claim ahead of measured work may be an error, a timing difference, or an unrecorded variation, and the
rule can establish the discrepancy without establishing its cause.

Three properties of that path are load-bearing. Units are never converted: there is no density
table here, and comparing 520 m³ with 470 tonnes is refused rather than coerced. A discrepancy is
reported, never resolved — the pipeline has no basis for deciding which document is right. And
**which revision a rule used is an explicit decision with a recorded reason**, never whichever row
the database returned last.

That last one was a real defect, not a hypothetical. Reconciliation selected facts with a dict
comprehension, which is correct for exactly as long as every version of a document agrees. Selection
is now a policy: non-active documents are excluded, the newest extraction of a document wins, several
agreeing documents are not a conflict, and several *disagreeing* active documents resolve to nothing
at all — the item is reported `REVIEW` naming each conflicting document and value. Superseded
evidence is never deleted; a finding recorded against an old revision has to stay explicable after
the revision is replaced, and "what did the original bill of quantities say?" is a legitimate
question.

Not yet built: archive expansion, the entity layer between projects and work items (Contract,
Invoice, PaymentCertificate), variation orders, automatic staleness detection for derived facts (the
fingerprint makes it detectable; nothing sweeps for it yet), and any user interface. Directories for
those are created when their first real code lands, rather than kept as empty scaffolding.

**Known gap, measured:** `GET /v1/documents` and `GET /v1/documents/{id}` describe a document through
its most recent *retrieval*, so every uploaded document is missing from them — 41 of 45 in the corpus,
while `GET /v1/corpus` reports all 45 as held. The project workspace no longer depends on that query
(`project_inventory` reads memberships), but the corpus catalog still needs its own fix, and it is not
a one-line one: `CatalogEntry` has non-optional `requested_url`, `http_status` and `attempt_count`,
and an upload has none of them.

## Recorded design debt

Known, deliberate, and not blockers. Each is here so that the next person to hit it finds the
reasoning rather than rediscovering it, and so that none of them gets fixed by accident in a way that
loses the distinction it protects.

**1. `documents` has outgrown the retrieval-shaped catalogue.** A document's origin is now either a
retrieval or an upload, but `CatalogEntry` still requires `requested_url`, `http_status` and
`attempt_count` — so `GET /v1/documents` describes only crawled documents. The long-term shape
separates identity from origin:

```text
Document      identity, digest, filename, format, type, state, storage
Origin        upload{source, uploaded_by, uploaded_at}
              OR retrieval{requested_url, final_url, http_status, attempts, retrieved_at}
```

**Nothing may fabricate HTTP values for an uploaded document.** Until a global catalogue is actually
needed, the project workspace uses `project_inventory`, which reads memberships and is correct for
both origins.

**2. `projects.source_id` is an acquisition concept and must not become tenancy.** It made sense when
every project was inferred from one source's documents. A real customer project holds an
owner-uploaded BOQ, a contractor's RA bill, a PMC certificate, a RERA filing and CPWD reference
material — there is no single meaningful evidence source for it. The target ownership model is:

```text
Organization → Membership/User → Project → Documents → Findings → Reviews
```

with `Document → Origin(s)` orthogonal to it, and every future authorization query scoped through the
organization/project boundary rather than through a source id. Changing the column now would be
churn; **letting "source" quietly mean "tenant" would be a security defect**, because an
authorization check written against it would look right and scope nothing.

**3. `Document.document_type` and `ProjectDocument.role` answer different questions and must not be
synchronised.** *What is this document?* versus *what part does it play in this project?* One
document can be a `contract` by type and reference material by role — a signed agreement from another
project, held for comparison. Intake sets the role from a **declared** type only, and a classifier
never touches either. If changing a role independently is ever needed, it becomes an explicit
human-confirmed operation, not an inferred one.

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

- **No Redis or Celery.** The frontier table is the queue, using `FOR UPDATE SKIP LOCKED` with a
  lease ([0012](docs/adr/0012-postgresql-frontier-queue.md)). A broker would add a second store that
  can disagree with the database about what has been done.
- **No Neo4j.** The evidence graph is shallow and relational; PostgreSQL is sufficient until
  traversal depth actually demands otherwise.
- **No async SQLAlchemy.** The API does thin metadata queries; heavy work belongs in
  workers ([0005](docs/adr/0005-synchronous-sqlalchemy.md)).
- **No LLM integration.** Nothing yet needs interpretation. When it does, it goes behind a
  provider protocol with versioned prompts, never inline calls.
- **No agent framework.** Deterministic workflows are sufficient for acquisition, and are
  easier to trust for anything financially consequential later.
- **No job queue, and processing says so.** `POST /v1/projects/{id}/process` runs synchronously and
  returns when the work is done — seven real documents including a 261-page agreement take 17
  seconds. Returning `202 Accepted` with a status field would be a lie about work no worker is
  doing ([0007](docs/adr/0007-defer-queue-infrastructure.md)). This is the endpoint a queue replaces
  first.
- **No authentication on the write API, and it refuses to serve production.** The first five write
  endpoints exist behind a guard that returns 503 when the environment is production, because there
  is no authorization and no tenancy and project ids are global UUIDs
  ([0018](docs/adr/0018-declared-projects-and-product-intake.md)). The guard makes the gap loud; it
  does not close it.
- **No frontend state library, and no truth in the browser.** The viewer fetches and displays;
  it recomputes no outcome, re-derives no category and ranks nothing. Vocabulary — including the
  order of the construction chain — comes from `GET /v1/knowledge`, so a category added in Python
  appears in the UI without an edit. A second implementation of a deterministic decision is a second
  answer.
- **No product-specific schema.** The product hypothesis is unvalidated (see
  [README](README.md) and [customer discovery](docs/research/CUSTOMER_DISCOVERY.md)), so the
  pipeline stores documents, provenance, and classification — never invoice-shaped or
  payment-shaped structures. A schema that encodes one product's assumptions is the most
  expensive thing to unwind if discovery points elsewhere, because migrations and extraction
  code both settle around it.

## Testing shape

```
tests/unit/          no database, no network. Runs in under a second.
tests/integration/   real PostgreSQL. Skipped automatically when unavailable.
```

Migrations are checked twice: an offline DDL comparison in
[test_migration_matches_models.py](tests/unit/test_migration_matches_models.py) that needs no
database, and `alembic check` against real PostgreSQL in CI, which is authoritative.
