# Known limitations — NHAI analysis vertical slice

Date: 2026-08-19

What the first end-to-end analysis path does **not** do. Recorded rather than fixed, deliberately:
the slice exists to prove the architecture survives real construction documents, and each item below
is a decision to revisit with evidence rather than an oversight.

## Corpus coverage

Of nine acquired NHAI PDFs:

| | Count | Note |
|---|---|---|
| Yield a complete estimated cost + bid security pair | 4 | 2 distinct tenders, each appearing as both a short NIT and a full bid document |
| State their own prescribed bid-security rate | 1 | ITB clause 13.2, page 13 of a 145-page document |
| Image-only, no text layer | 1 | Needs OCR |
| Yield no fields at all | 3 | Corrigenda and notices using labels the extractor does not read (`Earnest Money`, `Name of work` without a `NIT No.`) |

**Only four of nine have provenance rows.** Five objects in the bucket are orphaned from an earlier
incident in which test fixtures truncated the live database. The bytes survive — the raw tier is
immutable and content-addressed — but without a `documents` row they are invisible to `analyse --all`.
They self-heal on re-crawl. Re-creating those rows by hand would be fabricating provenance and is not
an option.

Consequence worth naming: the one document that reaches a **document-sourced** `PASS` is among the
orphans. The judged path is therefore demonstrated with a caller-supplied rate
(`--prescribed-share`), which the finding labels as such. A document-sourced pass needs that document
re-acquired, which needs a real crawler contact address.

## Not built

- **OCR.** An image-only PDF reports `has_text_layer=False` and yields no facts. That is a recorded
  limitation, not a failure, and OCR is its own slice.
- **Entities and relationships.** Facts attach to documents, not to a `Tender` or `Contract`. So the
  two documents describing one tender are not linked, and the 1% rate stated in a bid document is not
  applied to its own NIT even though it plainly governs it. Cross-document inference needs entity
  resolution first.
- **Duplicate-tender detection.** Two artifacts of one tender produce two independent fact sets.
- **Parser isolation.** pypdf runs in-process. Bounds exist on pages and characters and every parser
  error is caught, but there is no process or memory sandbox around untrusted document parsing. This
  is the honest next hardening step.
- **User agent in provenance.** `document_retrievals` records status, headers, digest and storage
  location but not the User-Agent that fetched the document, which is arguably part of how the
  evidence was obtained.

## Extraction fragility

- **Positional table reading.** The two amounts are told apart by column order within a header block.
  A notice ordering its columns differently would swap them. Mitigated by a plausibility guard that
  refuses a bid security at or above 50% of the estimated cost, and by the rule reporting the ratio it
  actually computed — a swap yields 5000%, not a plausible-looking pass.
- **Currency marker required.** An amount written without `Rs.`/`INR`/`₹` is not read. One document
  states its estimated cost as a bare grouped number and so yields nothing from that cell. Refusing is
  correct here: the same pattern without a currency marker matches chainage, highway numbers and
  clause numbers, which a tender notice is dense with.
- **One document type, one source.** NHAI notices inviting tenders. Nothing generalises to CPWD, GeM,
  or CPPP yet, and it should not until more real documents say what generalising means.

## Testing debt

Deliberate, under the sprint's testing rules. Not covered by automated tests: the `analyse` CLI
command and both API endpoints (verified by execution only); `pdftext` bounds against a hostile PDF;
the prescribed-share extractor's rejection of the 15%/5%/10% distractors; idempotency of re-analysis
(verified by running it twice and counting rows). The money parser, the two extraction defects found
while building, and the ratio arithmetic are the parts that warrant tests first, because they are where
a silent wrong number could reach a finding.

---

# Addendum — cross-document milestone (2026-08-20)

## What the corpus can and cannot exercise

**One project exists**, `NHAI/RO-CHD/2026-2027/BWN/21`, holding `NIT_1382.pdf` and `RFP_806.pdf`.
Its two documents **agree** on both comparable facts, so running the pipeline exercises only the
`PASS` path. The `FAIL` path — the reason the rule exists — is covered by
`tests/unit/test_cross_document_agreement.py` rather than by real data, because no document in the
corpus disagrees with another.

The second tender (`.../JAL/22`) would have formed a second project, and is the one whose bid document
states a 1% bid-security rate its own notice does not. Both of its documents are among the five
objects orphaned by the earlier truncation incident, so neither is catalogued and neither can be
grouped.

## Not built

- **Derived facts are not first-class.** A computed difference lives in a finding's `detail`, not in
  a table, so two rules cannot share one derived value. This is the next architectural step named in
  the recommendation and is deliberately deferred: the milestone's deliverables did not include it,
  and inventing the table before a second rule needs it would be guessing at its shape.
- **Roles are unassigned.** Every `project_documents.role` is `unclassified`. Page count and filename
  would both distinguish a notice from a bid document, and both are heuristics that would put an
  unsourced claim under every relationship built on them.
- **Only `same_tender` is derivable.** The rest of `RelationshipType` is declared vocabulary. Nothing
  in the corpus establishes `amends`, `supersedes`, `measures` or `claims_against`.
- **No entity layer.** Facts attach to documents and documents to projects. There is no `Contract`,
  `BOQItem`, or `Invoice` object, so a rule cannot yet say "this claim line exceeds its BOQ item".
- **Projects never span sources.** Deliberate: two authorities can issue the same reference number
  and they are not the same tender.

## Defect found by execution

The generated `downgrade` for migration `31ee35a5a943` failed with `NotNullViolation` as soon as one
project-scoped finding existed, because restoring `findings.document_id NOT NULL` cannot succeed when
a cross-document finding is present. The migration now deletes project-scoped findings first. That is
sound because findings are derived and reproducible by re-running the analysis — no raw artifact,
provenance row, or extracted fact is touched — but it is data loss in a downgrade and is called out in
the migration itself.

## Testing debt

Verified by execution only: project reconciliation and its idempotency (two runs, `0 projects, 0
memberships, 0 relationships created`), all five project API endpoints, and the CLI output. Covered by
test: the four outcome paths of the agreement rule, including disagreement.

---

# Addendum — construction knowledge layer (2026-08-20)

## What is real

`bid_security_share` is computed once per document by the calculation layer, stored with its two
inputs and the arithmetic as text, and consumed by **two rules** that reach different kinds of
conclusion from it — the single-document rule against a prescribed rate, the project rule against the
other documents. Neither divides. That is the milestone's success criterion, verified by execution.

Chronology is real but thin: both documents of the one project are dated `2026-08-07`, so ordering is
correct and completely undemonstrative. A project whose documents differ in date would show more.

## Not built

- **Only one calculation exists.** `share_of`. The engine is a registry with a single entry, and its
  shape is a guess until a second calculation with different inputs arrives — which is why no
  abstraction was built over it.
- **No project-scoped derived facts.** The schema supports them (`derived_facts.project_id`), and
  nothing produces one, because every calculation currently takes its inputs from a single document.
  The example in the milestone brief — remaining contract value from a contract and a bill — is
  exactly the shape that needs it, and needs document types the corpus lacks.
- **`same_contract`, `amendment_of`, `supersedes`, `parent_document`, `child_document` are declared
  vocabulary, not derivable.** `RelationshipType.inverse` exists for the parent/child pair; nothing
  establishes them. `parent_document` is the one the corpus arguably justifies — the notice is bound
  into the bid document — but establishing it needs either a containment check or a document-type
  classification, and both are guesses today.
- **Chronology has no temporal rules.** Documents can be ordered; nothing reasons about the order.
  That was deliberate — the brief asked for chronology "without introducing workflow engines".
- **Derived facts are not recomputed when an extractor version changes.** A new extractor version
  writes new facts, but the derived fact keyed on `calculation_version` is not invalidated. Re-running
  `analyse` recomputes it, so this is an operational note rather than a defect: it means a stale
  derived value is possible between an extractor change and the next run.

## Defects found by execution

1. **`finding_evidence`'s primary key change was invisible to autogenerate.** Moving it from
   `(finding_id, fact_id)` to `(finding_id, role)` — needed because `fact_id` is now nullable — is not
   a change Alembic detects. Written by hand. Had it been missed, the model and the database would
   have disagreed silently.
2. **The generated downgrade would have failed again**, this time on `finding_evidence.fact_id`
   becoming `NOT NULL` while derived-only citations existed. Pre-empted by deleting them first, the
   same reasoning as the previous migration: evidence links are derived and rebuilt by re-running the
   analysis.
3. **Displayed value did not equal stored value.** The engine returns the unrounded quotient
   (`0.02000000732427911462082165677`) while the column is `NUMERIC(28, 10)`. Quantizing moved to
   persistence, so what a caller reads back is what the database holds.
4. **The single-document CLI printer silently dropped derived evidence** — I had updated only the
   project printer. The finding cited the derived fact correctly; the output just did not show it.

## Testing debt

Verified by execution only: derived-fact and evidence persistence, idempotent recomputation (repeated
runs leave 2 derived facts, 4 input links, 0 duplicates), the `/v1/knowledge` endpoint, and both CLI
printers. Covered by test: the share calculation including the not-exactly-2% case, every refusal
path, newest-extractor-version selection, and the registry's claim that it describes only types the
code can produce.
