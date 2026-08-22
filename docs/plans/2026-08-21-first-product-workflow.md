# Milestone: the first end-to-end product workflow, and an acquisition freeze

Date: 2026-08-21

## The decision

**Document acquisition is frozen.** Not abandoned — frozen. Acquisition, provenance, OCR
benchmarking, parser work and corpus research have reached the point where more of them yields
diminishing returns, and the last three research passes each improved a component without moving a
user through a workflow.

What replaces it:

```text
Create Project → Upload Documents → Automatic Classification → Evidence Extraction
              → Cross-document Linking → Deterministic Verification → Findings
              → Evidence Viewer → Human Review
```

The point is not that every document type works. It is that **the workflow exists**. If only BOQ,
agreement and certificate work, that is a product; a perfect parser with no workflow is not.

And it makes every later decision cheap. If users repeatedly upload something handled badly, that is
concrete evidence for a new extractor. **If nobody ever uploads a handwritten JMR, months of OCR work
were correctly avoided.**

### What the freeze does and does not stop

**Stopped:** new portals, new sources, broad corpus surveys, parser hardening, OCR/layout
benchmarking, anything measured in documents acquired.

**Still allowed, because each is small and unblocks the workflow rather than the corpus:**

- CPWD DSR — needed for the first rule a quantity surveyor cares about (applied rate vs scheduled
  rate), and its source entry is still `unverified`.
- Labour Bureau CPI-IW by centre — completes a price-adjustment clause already in the corpus.
- Anything a **design partner** hands over. That is Tier 4 and outranks everything.

## Honest inventory: how much of the workflow already exists

Measured, not estimated — the API surface is 19 endpoints and **every one is a `GET`**.

| # | Stage | State | Gap |
| --- | --- | --- | --- |
| 1 | Create Project | **Partial** | `Project` exists but is only ever *derived* from extracted identifiers by `reconcile_projects`. No user creates one. No `POST`. |
| 2 | Upload Documents | **Partial** | `ingest_file` works and is operator-only, from a local path, unattached to a chosen project. No API upload. |
| 3 | Automatic Classification | **Absent** | `classification_confidence` and `classifier_version` exist on `documents` and have **never been written**. Type is stated by the operator. |
| 4 | Evidence Extraction | **Exists** | — |
| 5 | Cross-document Linking | **Exists** | `reconcile_projects`, `link_work_items`, `evaluate_project` |
| 6 | Deterministic Verification | **Exists** | rules, derived facts, `row_arithmetic` |
| 7 | Findings | **Exists** | PASS/FAIL/REVIEW/INCONCLUSIVE with explanations and cited evidence. **Already no risk scores** |
| 8 | Evidence Viewer | **Partial** | read endpoints exist; no UI |
| 9 | Human Review | **Absent entirely** | no table, no model, no endpoint, no reviewer identity |

**The middle of the pipeline is built. Both ends are missing.** That is a better position than it
sounds: stages 4–7 are the hard, correctness-critical part, and they are done and tested.

## Order of work, and why

### 1. Human review — first

**USER PROBLEM.** A finding is currently terminal. A billing engineer looking at `REVIEW — 86 × 631
= 54,266.00 but the bill states 54,518.40` has nowhere to record that they checked it, what they
concluded, or that the next reviewer need not look again. Twelve such rows exist in one real bill.

**REAL EVIDENCE.** Stage 9 has no implementation at all, and it is the SRS's own terminal step
(`Findings → Human Review → Business Decision`). It also gates something already decided:
ADR 0016/0017 commitment 3 says no capability's output becomes a money fact on its own confidence —
*only when deterministic validation closes or a human accepts it*. **The second half of that
sentence is currently unimplementable.** The trust boundary the owner just elevated to Principle 0
does not exist in code.

**MINIMUM CHANGE.** One append-only table recording a decision against a finding: who, when, what
outcome, why. Reuse the retraction pattern — never mutate, never delete, the record is the evidence.
No workflow engine, no assignment, no notifications, no SLA.

**SUCCESS CRITERION.** A reviewer can accept or reject a real `REVIEW` row from the Hostel 19 bill,
the decision is durable and attributable, re-review appends rather than overwrites, and the
traceability audit still passes.

### 2. The write path — second. **Done, 2026-08-21.**

`POST /v1/projects`, `POST /v1/projects/{id}/documents`, `POST /v1/projects/{id}/process`,
`GET /v1/projects/{id}/documents`, `GET /v1/projects/{id}/summary`,
`POST /v1/documents/{id}/classification`. Recorded in
[ADR 0018](../adr/0018-declared-projects-and-product-intake.md).

Exercised over HTTP against the real IIT Bombay Hostel 19 project: seven documents attached, 3,311
facts, 28 document findings, 2 project findings, 17 seconds; re-upload created neither a second
artifact nor a second membership; a `needs_evidence` review named the two documents that would close
the open finding.

**What it found.** The first end-to-end run produced a `FAIL` from a fact that had already been
retracted — a threshold quoted inside the general conditions of contract (`Rs. 5 crores`, page 48).
`select_one` and `load_project_facts` both ignored retraction, so a withdrawn value was being
compared and `scripts/audit_traceability.py` failed on it. Fixed at three layers, regressed at two.
That defect is the milestone's own justification: no amount of parser work would have surfaced it.

**Deliberate limitations, all recorded in ADR 0018:** processing is synchronous; the corpus catalog
still hides uploaded documents; `document_uploads` records one row per (document, source), so a
repeated upload to the same project is idempotent rather than append-only.

### 3. Classification — third, and deliberately narrow. **Done, 2026-08-21.**

A **suggestion** with a confidence, written to the columns that already existed and had never been
written. It does **not** set the reference-versus-project role: `runner.py` requires that role to be
declared and never inferred, because inferring it produced five false facts from real documents.
Suggestion and authority are separate fields, and `documents.type_authority` records which of a
declaration and a human confirmation set the type.

The classifier reads the filename and nothing else — `aedifex.classification`, 23 ordered rules, no
model. On the real project it agreed with five of six declarations and disputed one: the general
conditions of contract, declared `model_agreement` and proposed `contract`, which is precisely the
case a person has to settle because nothing in a filename can.

### 4. The viewer — fourth. **Done, 2026-08-21.**

[frontend/](../../frontend/) — React, TypeScript, Vite, no state library, no component library, 44
npm packages. The seven surfaces exist and were verified by driving a real browser against the real
corpus rather than against a fixture.

Every finding answers the six questions in the order a reviewer asks them, and there are no risk
scores anywhere — `ARCHITECTURE.md`'s layer diagram lost the "risk engine" box it used to carry,
because a score collapses the five things a reviewer needs into one number nobody can argue with.

**What the viewer found, which is the point of building it:**

1. `GET /v1/projects/{id}/facts` returned **500 for every project holding any fact** — the response
   is built after the session closes and reads `retraction`. Three real projects, 3,319 / 578 / 120
   facts, two with no retractions at all: all three failed. The document-level endpoint had the
   eager load and the project-level one did not.
2. **Policy provisions were dropped from the API.** A finding that judged a bid security against
   NHAI clause 4.14.1(a) was served with the threshold missing; the CLI printed it.
3. **A failed analysis left no trace on the document.** Extraction raises before the first state
   transition, so a PDF that could not be opened showed as `uploaded` — indistinguishable from one
   nobody had tried. A reviewer would press Process forever.

Two additions were needed and are recorded as requirements rather than smuggled in:
`GET /v1/documents/{id}/content` (the artifact itself, digest re-verified, sandboxed) and
`GET /v1/findings/{id}` (so a finding is a place a reviewer can link to).

**Deliberately not fixed:** the corpus catalogue still hides uploaded documents, spreadsheets are not
rendered in the browser, and there are no frontend tests. All three are recorded in
`ARCHITECTURE.md` or `frontend/README.md`.

### 5. Consistency pass after a code review — 2026-08-22

A read of the repository at `fdc0694` produced seven findings, all of them about the architecture
being internally inconsistent rather than about anything missing. Six were acted on and one was a
disagreement worth conceding.

| # | Finding | Resolution |
| --- | --- | --- |
| 1 | `Project.source_id` had three meanings — acquisition origin, ownership, tenancy placeholder | The code's comments were wrong and the architecture note was right. Audited and corrected everywhere; `customer_provided` added so a customer's documents have an honest origin |
| 2 | The frontend decided which findings need review, listing every INCONCLUSIVE as work | One definition, in `domain/workflow.py`, served as `needs_human_review` per finding and `requires_human_review` per outcome. The browser now only sorts by it |
| 3 | Spreadsheet cell provenance never reached the API | `sheet_name` stored and backfilled; sheet, row, column and cell exposed on facts and evidence |
| 4 | The frontend was not in CI | A `viewer` job: `npm ci`, `npm run build`. Make switched to `npm ci`; Dependabot watches the lockfile |
| 5 | A failed summary rendered as a dash | "Summary unavailable — *reason*", verified by making the request fail in a real browser |
| 6 | Refusing to render spreadsheets was too strict | Conceded, and it was the right call: the *strongest* evidence we hold was the hardest to review. `GET /v1/documents/{id}/sheet` serves a bounded window read by the extractor's own library, so the grid cannot disagree with the facts |
| 7 | Create Project and Upload still needed curl | Both are in the UI, and both were driven through a real browser to confirm it |

Finding 6 deserves its own note, because the reasoning changed rather than the standard. The
objection to rendering was that a re-rendering is our interpretation of the evidence. That still
holds for a PDF, where a faithful renderer already exists in the browser. For a workbook there was no
renderer at all, so the choice was not "artifact or interpretation" but "reviewable or not" — and the
danger the original rule was guarding against, a *second* reader disagreeing with the extractor, is
avoided by reading the cells on the server with the same library and the same settings. The workbook
remains authoritative and the screen says so.

## Where this leaves the product

A real building project — IIT Bombay Hostel 19, seven documents, 3,319 facts — goes from a URL to a
recorded human decision without a shell. What a reviewer sees includes the imperfections, which is
the point: **Measurement, RA Bill, Variation, Material and Quality are all absent**, so the checks
that matter most cannot run, and the workspace says so on the first screen rather than presenting a
clean result.

The next decision should come from using it, not from this document.

## Explicitly not in this milestone

New parsers · new OCR capabilities · handwriting · the layout/table lane · vision models · a rules
DSL · notifications · multi-tenancy · authentication beyond what a single-operator deployment needs ·
IFC/DWG.

## The unknown this milestone is designed to resolve

**Is handwriting common in the target workflow?** Every handwriting conclusion in this repository
comes from one 2001 highway contract. The building corpus that followed needed no OCR at all. A
single design partner could invalidate the entire handwriting investment — or justify it — and until
the workflow exists there is no way to find out. **That is the strongest argument for building the
workflow before any more document work.**
