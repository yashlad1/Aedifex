# 18. Declared projects, and an intake path that separates identity from membership

Date: 2026-08-21

## Status

Accepted, and implemented. Unlike [ADR 0016](0016-ocr-gateway-not-an-ocr-engine.md) and
[ADR 0017](0017-document-understanding-gateway.md), which record direction, this one records code
that exists: `aedifex.workspace`, `aedifex.classification`, five write endpoints, and migration
`4a4f930da9cd`.

## Context

The middle of the pipeline was built first. Facts, calculations, rules, findings, evidence and human
review all worked, and both ends were missing:

* a project could only come into existence by being **derived** — reconciliation found two documents
  quoting an identical identifier and created the row. The real building project this milestone was
  built against has seven documents and **one** of them states the tender number, so it had no
  project at all;
* documents could only arrive through a shell command run by someone holding the object-store
  credentials.

And one measured defect made the gap worse than it looked. `catalog_entry` inner-joins
`document_retrievals`, so **every uploaded document was invisible** to `GET /v1/documents`,
`GET /v1/documents/{id}` and `GET /v1/projects/{id}/documents` — 41 of 45 documents in the corpus,
while `GET /v1/corpus` reported all 45 as held.

## Decisions

### 1. A project can be declared, and declaration converges with derivation

`projects.external_ref` becomes nullable and `established_by` carries either `declared:alice` or
`shared_fact:nit_number`. A declared identifier is normalised by the *same* function reconciliation
uses (`normalise_project_key`), so a project declared as `IITB/Dean (IPS)/CACI/H-19/NIT/R1` is the
row reconciliation finds when it reads `IITB/DEAN (IPS)/...` off page 1. Without that, one building
would end up as two projects and every cross-document rule would see half the evidence.

**Rejected:** synthesising an identifier from the project name. `external_ref`'s entire contract is
that it is never invented, and a slug in that column would be an invented identifier in the one
place the schema promises there are none.

### 2. Artifact identity is not project membership

The deduplication rules, stated because they are easy to get subtly wrong:

| Case | Artifact | Membership | Upload row |
| --- | --- | --- | --- |
| same bytes, same project | reused | reused | reused |
| same bytes, two projects | **reused** | **new, per project** | reused |
| same bytes, second source | reused | per project | **new** |

The second row is the point. One schedule of rates governs many projects; one bill can be given to
an auditor and to a PMC. The membership row carries its own `established_by` and `linked_at`, which
is where the second upload *event* is recorded — `document_uploads` is unique per
(document, source) by design, so a repeated upload is idempotent rather than append-only. That is a
deliberate limitation and it is the one thing here a future provenance change may want to revisit: a
second upload of identical bytes to the *same* project by a different person is visible only in the
log.

### 3. A classifier proposes; only a person decides

`documents.suggested_document_type` is a new column, and nothing promotes it. `document_type` gates
whether the extractor treats a quoted amount as a fact about the document, and inferring that role
has already produced five false facts from real documents.

`documents.type_authority` records who decided, with four values of which **two may appear today** —
`declared` and `human_confirmed`. `deterministic_classifier` and `model_suggestion` exist so that a
future policy of adopting a proposal has an honest place to record itself instead of being
indistinguishable from a person's judgement.

The classifier itself reads **only the filename**, which is not a placeholder for something better:
the names customers actually upload — `BOQ.xlsx`, `RA_Bill_17.xlsx`, `JMR_17.jpg`,
`Architect Certificate.pdf` — are written by someone who knew what the document was.

The most valuable output is *disagreement*. On the real project, the general conditions of contract
are declared `model_agreement` and the classifier proposes `contract`; both readings are defensible,
which is exactly why a person resolves it.

### 4. Processing is synchronous, and says so

`POST /v1/projects/{id}/process` runs the existing `analyse_document` / `analyse_spreadsheet` /
`analyse_project` and returns when they are done. Seven real documents, including a 261-page
agreement and a 5 MB specification, take 17 seconds.

**Rejected:** `202 Accepted` with a status field. There is no worker, so the status would be a lie
about work nobody is doing — and per [ADR 0007](0007-defer-queue-infrastructure.md) the queue arrives
when there are tasks, not when an endpoint would look nicer. This is the endpoint a queue replaces
first.

**Rejected:** running analysis inside the upload request. Upload stays fast and returns a status of
`uploaded`; a caller uploading twelve documents should not have the twelfth request carry the cost of
the first eleven.

### 5. Reconciliation is not run from the product path

Membership was declared by the person who owns the work. Re-deriving it from shared identifier facts
could only agree with that or invent a second project for the same documents.

### 6. The write API is not publicly deployable

`require_write_access` refuses every write when the environment is `production`, enumerated by a test
over the application's own routes so a new write endpoint cannot escape it. This is a stopgap that
makes the gap loud, not a control that closes it: there is no authentication, no authorization and no
tenancy, and project ids are global UUIDs with nothing scoping them to an owner.

## The defect this milestone found

The first end-to-end run produced a **FAIL** on the real project: three documents stating an
`estimated_cost`, two at ₹85,39,81,318.41 and one at ₹5,00,00,000. The third was a threshold quoted
inside the general conditions of contract — *"works with an estimated cost put to tender of less than
Rs. 5 crores"*, page 48 — and it had already been **retracted** weeks earlier, correctly, by
extractor version 4.

`load_project_facts` did not filter retracted facts, and neither did `select_one`, whose entire job
is choosing what a rule reasons over. So a value the system had formally withdrawn was still being
compared, and produced a confident verdict. `scripts/audit_traceability.py` caught it independently
(*"conclusive finding cites a retracted fact"*), which is the guard working as designed.

Fixed in three places — the selection policy, the cross-document loader, and project membership
grouping (a retracted identifier must not group anything) — and the finding is now a **PASS** on the
two values that stand. Regression tests at both layers.

**This is the milestone's strongest argument.** No amount of parser work would have surfaced it; a
product workflow surfaced it on its first run.

## Correction, 2026-08-22: what `projects.source_id` means

The first version of this ADR, and the code it describes, said that `source_id` is "the column
tenancy will replace". **That was wrong**, and it contradicted
[ARCHITECTURE.md](../../ARCHITECTURE.md)'s own design-debt note, which had it right.

The column has exactly one job: `external_ref` is unique only within the authority that issued it,
so pairing the reference with a source is what stops reconciliation merging two authorities' identical
tender numbers into one project. That is acquisition metadata.

It is **not** ownership, and it must never become tenancy. The reason is not tidiness. An
authorization check written against an acquisition field *looks* like scoping and scopes nothing —
every query would appear guarded while returning rows from anywhere, which is worse than an obviously
missing check. Authorization arrives as `Organization → Membership → Project`, in new columns.

It also does not restrict what a project may hold, and the implementation never did: membership spans
sources by design, because a real project holds an owner-uploaded bill, a contractor's claim, a PMC
certificate and a published rate schedule. Each *document* records its own origin. The API request
description that said "projects never span sources" was describing reconciliation's grouping rule as
if it were a constraint on the project, and has been corrected.

One thing was added rather than only reworded: a `customer_provided` source now exists in the
registry, so a customer's own documents have an honest origin instead of borrowing whichever
acquisition source happened to be approved. Its `access` is `restricted` — the contents are not ours
to redistribute — which required scoping the registry's "restricted sources cannot be enabled" rule
to *fetching* methods. That rule exists because collecting from behind an access control would mean
bypassing the control; a document its owner hands over bypasses nothing.

## Correction, 2026-08-22: an upload is an event

Decision 2 above stated the deduplication table and called the single upload row per
(document, source) "a deliberate limitation... the one thing here a future provenance change may want
to revisit". An independent review revisited it, and it was wrong rather than merely limited.

The limitation was written while every source had one operator. `customer_provided` broke that: a
contractor's bill sent to both the owner and the PMC is **identical content supplied by two
different people**, and the narrow key discarded the second uploader, their filename, their timestamp
and their note. `document_retrievals` had been append-only from the start — one row per retrieval,
deliberately — so the asymmetry was inconsistent as well as lossy.

The key is now `(document_id, source_id, uploaded_by, original_path)`. Two people are two events;
one person re-running the same ingest is still idempotent, which is what the narrow key was actually
protecting. And `project_documents.filename` records the name *this* project's uploader used, because
`documents.original_filename` is content-level and content is shared — so a second project uploading
identical bytes had been shown the first project's filename.

## Consequences

**Good.** A real building project moves create → upload → process → findings → evidence → review
through HTTP alone. Uploaded documents are visible for the first time. `needs_evidence` reviews now
name missing documents in a reviewer's own words, which is a better corpus roadmap than anything
public.

**Costs.**

- `GET /v1/documents` still hides uploads. The project workspace no longer depends on it, but the
  corpus catalog needs its own fix and `CatalogEntry` has non-optional HTTP fields.
- Two document classes on the product's own priority list — material reconciliation statement,
  completion certificate — have no `DocumentType`, so they file as `unknown`. The classifier
  correctly proposes nothing rather than the nearest available label.
- `documents.document_category` remains unwritten on every row. It is derivable from
  `document_type`, nothing reads it, and the workspace derives a `WorkflowCategory` instead.
- Uploading the same bytes under a *second* source writes a redundant object under a second storage
  key, because `raw_key` includes the source id. Content-addressed and verified, so nothing is
  corrupted; it is wasted bytes.
- A repeated upload of identical bytes by the *same* person under the *same* filename is still one
  row. That is idempotence for a re-run rather than a lost event, and the membership's `linked_at`
  carries when each project received it.
