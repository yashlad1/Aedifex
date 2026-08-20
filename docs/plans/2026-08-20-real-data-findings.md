# Real post-award data — findings

Date: 2026-08-20
Source: `RFP_806.pdf`, an NHAI bid document already in the corpus with full provenance. Pages
164–171 hold a **real priced bill of quantities**: 35 numbered line items — one of them a credit,
two of them priced through sub-items — a stated total of ₹8,46,49,969.01, and none of the tidiness of
a generated fixture.

No new corpus was needed. The most realistic post-award document available was already acquired and
had been sitting unread.

## Starting point

The pipeline extracted **four** facts from this 247-page document — `nit_number`, `estimated_cost`,
`bid_security`, `document_date`, all from page 6 — and **zero** work items. An eight-page priced bill
of quantities worth ₹8.46 crore was invisible, because the only table reader was XLSX-only.

After this session: **190 facts** (37 priced rows × 5, plus the notice fields and the bill's stated
total), **37 work items**, and a bill that reconciles to its own total to the paise.

---

## BLOCKER — fixed

### B1. No PDF table reader; real bills of quantities are PDF
The XLSX reader could not see the real BOQ at all. Fixed with
[`extraction/pdf_boq.py`](../../src/aedifex/extraction/pdf_boq.py), deliberately narrow: it reads the
layout in front of it and refuses everything else.

### B2. Silent misattribution — one item reported with another's quantity and rate
Items whose description is short enough to fit on one line arrive as
`12 RCC Drain 1.0 metre x 1.0 metre on both sides Rm` — number, description and unit merged. Reading
only lone-integer lines meant item 11's block ran to the next lone integer and **took item 12's
figures**: item 11 was reported as 2,400 × ₹4,057.19 instead of its own 50 × ₹4,252.

The arithmetic check could not catch it, because item 12's figures are internally consistent. Fixed
with sequential item detection: a candidate is an item only if it continues the run 1, 2, 3…, which
also rejects the numbers that legitimately begin descriptions ("12 mm cement plaster" sits inside
item 27).

### B3. Sub-items silently collapsed to one row
Items 21 and 22 have priced sub-items `(a)` and `(b)`, each with its own unit, quantity, rate and
amount; the parent row is a heading with no figures. The reader reported sub-item (b) as the item.

First fixed by **refusing** the block with both triples named — the honest answer while the reader
had no representation for a parent with priced children. Superseded by B6, which reads them properly.
The multi-triple refusal remains as the guard against any *other* block holding two priced rows,
which is what it was really for.

### B4. Work items and findings were not persisted for the last project analysed
`reconcile_work_items` ran in the *printing* path, after the commit. A project's work items were
saved only by the next iteration's commit, so the last project's were **always rolled back**. The
real NHAI project sorts last, so its 32 work items were computed, displayed, and lost. Fixed by
moving reconciliation inside the committing transaction.

Found only because real data produced a second project. With one project it was invisible.

### B5. A credit row written in accounting parentheses was invisible
Item 35 of the real bill is `Recovery of Milled Material`, 661.50 Cum × **(1,785.60)** =
**(11,81,174.40)** — a credit, written the way construction accounting writes one. The money pattern
matched only unbracketed figures, so the row was dropped and the bill was **overstated by ₹11.8
lakh**. A recovery, a deduction and a credit note are ordinary post-award records, so the sign is
part of the value.

Worse than a missing row: dropping the bracket would have turned the credit into a charge. Fixed in
`_to_decimal`, which now reads `(x)` as `-x`.

### B6. Sub-items were refused, dropping four priced rows
Items 21 and 22 are headings whose figures live entirely in sub-items `(a)` and `(b)`. Refusing them
was the right call while the reader had no representation for them — reporting sub-item (b) as the
item would have been a silent misattribution — but it lost ₹65,951.50 and blocked the total check.

Now split on the sub-item markers into `21(a)`, `21(b)`, with the parent heading kept on each child
because `5th kilometre stone` on its own is not an item of work. **No schema change was needed:**
`21(A)` normalises distinctly from `21` under the existing rule. The real project went from 32 work
items to 37.

### B7. The bill total was summed from one row instead of thirty-seven
`persist_facts` returned one fact per type, and the runner passed that view to the calculation layer.
So the first version of the bill total was the value of whichever row was written last — ₹−1,181,174.40,
reported against a stated ₹84,649,969.01 as a REVIEW finding, with total confidence.

This is **the same defect as arbitrary fact selection** (the `{fact.fact_type: fact}` pattern), one
layer down, and it is the third time this shape has appeared. Fixed with `FactSet`, which returns
every persisted fact alongside the document-scoped ones, so the two views cannot be confused: a rule
asking for "the estimated cost" wants one fact, and a calculation summing a bill wants all 37.

Found by reading the output of a real document rather than by a test — the number was visibly absurd.

### B8. Thirty-eight PASS verdicts cited no evidence at all

Found by auditing the chain the platform exists to provide, rather than by reading a document:

    Finding -> Evidence -> Derived Fact -> Fact -> Document -> Page/Cell -> Immutable Raw Artifact

Of 172 stored findings, **156 cited nothing**. Splitting by outcome is what made it actionable:

| Outcome | No evidence | With evidence |
| --- | --- | --- |
| pass | **38** | 10 |
| review | 0 | 4 |
| inconclusive | 118 | 2 |

The 38 were all `work_item_evidence_unambiguous`, which returned PASS with `evidence={}` — a summary
reading "every value used is stated by exactly one active document" that **named none of them**, and
an `observed` of "0 conflicts" a reviewer had no way to check. 37 of the 38 were the real NHAI
project's work items. A verdict that cannot be traced is the one thing this platform may not produce,
so: BLOCKER.

Fixed by citing the facts the rule actually resolved — it already held them in `item.selections` and
was discarding them. Evidence links across the corpus went **46 to 240**, facts reached **92 to
286**. A work item where *nothing* resolves now returns INCONCLUSIVE rather than PASS, because a
pass citing nothing would leave the same hole open in a case the corpus does not currently contain.

Two things the audit confirmed rather than found, which are worth stating because they were assumed
before: every one of the 286 facts reached resolves to a document with a provenance row and to a raw
object in immutable storage **whose digest still matches** the document record; and the page locator
needs no runtime check at all, because `extracted_facts.page` is NOT NULL with a `page >= 1`
constraint — mypy rejected the check as unreachable, which is the stronger outcome.

The audit is now [`scripts/audit_traceability.py`](../../scripts/audit_traceability.py) and
`make audit-traceability`, following the existing `scripts/validate_registry.py` pattern. It fails
only on a *conclusive* finding that cannot be traced. Run it against every new class of real
document.

---

## NEXT

### ~~N1. Extracted line items do not reconcile to the stated bid price~~ — RESOLVED, was a BLOCKER

Recorded first as "cause not established, and deliberately not guessed at". It has now been
established, and **the document was right; the reader was wrong.** The reconciliation closes to the
paise:

| | Amount |
| --- | --- |
| 32 rows accepted before this pass | ₹85,765,191.91 |
| plus 4 refused sub-item rows (N2) | ₹65,951.50 |
| minus item 35, a credit row never read (B5) | −₹1,181,174.40 |
| **computed** | **₹84,649,969.01** |
| stated "Total Estimated Cost", page 171 | ₹84,649,969.01 |
| **difference** | **₹0.00** |

Two parse omissions, and the larger one was a **sign error in a payment figure** — see B5 and B6
below, both promoted to BLOCKER because each on its own produces an incorrect finding. The 1.3% was
never evidence of anything about the document.

The check itself is now a rule: `bill_items_reconcile_to_stated_total` (FR-122), PASS on the real
bill. It is deliberately REVIEW rather than FAIL when it does not close, because a bill that does not
add up is as likely to mean the extraction is untrustworthy as that the document is — which is
precisely what happened here.

### ~~N2. Sub-item structure is unrepresented~~ — RESOLVED, see B6

### ~~N3. Units are corpus-specific and uncompared across sources~~ — case fixed, equivalence not

Recorded first as something a *second* real document would force. The one real document forces part
of it on its own. Its unit spellings, straight from the database:

| Spelling | Rows |
| --- | --- |
| `Nos` | 12 |
| `Cum` | 9 |
| `Sqm` | 8 |
| `Rm` | 3 |
| `Kg` | 1 |
| `cum` | 1 |

**One document spells cubic metres two ways.** `_comparable_pair` compared units with `!=`, so
`Cum` against `cum` was refused — declining to reconcile a payment over a typist's shift key, and
declining *silently*: the result is an INCONCLUSIVE where a discrepancy should have been found. That
is a false negative in a payment audit, so it is fixed, narrowly: comparison is case-folded, stored
evidence keeps the spelling the document used.

**Deliberately still refused: `Cum` against `m3`, and `Nos` against `Nos.`** Those may well be the
same unit and one document is no basis for saying so. Case-folding is safe because no construction
unit differs from another by case alone; an equivalence table is a different claim, and building one
from a single portal's spelling habits is the per-portal special case principle 10 names. A second
real document can answer it.

### N6. Five real objects sit in immutable storage with no provenance at all

Nine NHAI PDFs are in the raw tier; four have a document row. The other five have **no document row,
no retrieval row, and no frontier row** — the frontier's only four `downloaded` entries all carry a
`document_id`. Nothing in the database records where those bytes came from.

They include the two most valuable documents in the corpus: `65ab…`, the 145-page bid document whose
Instructions to Bidders prescribe 1% bid security at clause 13.2 — the only document that can drive
the bid-security rule to a PASS — and `cc8a…` at 232 pages.

**They cannot be admitted to the evidence graph, and must not be.** Ingesting them as uploads would
record an upload that never happened; writing retrieval rows would invent a URL and an HTTP status.
Either is a fabricated provenance row, which is the one thing the project's own rules name as never
permissible. Nor are they deleted: the raw tier is immutable.

The only honest route is re-acquisition from the live source, which produces genuine provenance and,
because storage is content-addressed, resolves to the same five keys without duplicating anything.
That is blocked on the crawler contact address. NEXT, and blocked on the owner rather than on code.

**The general gap this exposes:** `scripts/audit_traceability.py` walks findings *down* to artifacts
and would never have found this, because these objects support no finding. Nothing walks the other
direction — artifact up to provenance — to detect bytes in the evidence store that nothing explains.
That check is a small extension of the existing script rather than new infrastructure, and it is
deliberately not written yet: the architecture is frozen pending real-corpus evidence, and this is
one instance found by hand, not a demonstrated need for a standing gate.

### N5. Inconclusive findings cite nothing, including what they did find

The 118 remaining chain breaks are all INCONCLUSIVE, and tolerated: an INCONCLUSIVE asserts only that
a fact was missing, and there is no evidence for an absence. The audit exits zero for them
deliberately.

But most of them found *something*. `claim_within_measured_quantity` on a real BOQ item has the
contracted quantity and the contract rate in hand and lacks only the measurement, and citing the two
it has would turn "inconclusive" into "inconclusive, and here is the half of the chain that exists".
That is explainability, not correctness — no finding is untrustworthy because of it — so it is NEXT
rather than BLOCKER.

### N3b. An item number written `21 (a)` will not link to `21(a)`

Probed rather than observed, and recorded on that basis. `normalise_item` unifies whitespace,
hyphens, slashes and underscores to `.`, so:

| Written | Normalised |
| --- | --- |
| `21(a)` | `21(A)` |
| `21 (a)` | `21.(A)` |
| `21-a` | `21.A` |

The first two are the same item to any engineer and do not link. **Not fixed**, because no real
document has been seen writing it the second way — the real bill puts `(a)` on its own line. If a
measurement book turns out to write `21 (a)`, this is the first thing to check, and the failure will
again be a silent INCONCLUSIVE rather than a wrong number.

Same class: a spreadsheet whose item-number cell is numeric gives `1.0`, which does not normalise to
`1`. Also unobserved, also silent.

### N4. Rounding differences of ₹10–13 exist between stated amounts and quantity × rate
Two rows near ₹9,000,000 are out by ₹10.20 and ₹13.10. Absorbed by tolerance (`max(₹100, 0.05%)`).
Real, immaterial, and worth knowing when a rule eventually compares totals.

---

## DEFERRED

- **A fact with no unit is compared against one that has a unit,** taking the other's. Not an
  oversight and left alone: a document stating no unit is not a document stating a *different* one,
  and refusing would make every record with an unlabelled column unreconcilable. It is the one place
  in the calculation layer where absent evidence is read as agreement, and it is now documented in
  the code as such rather than being an unremarked consequence of an `is not None` check.

- **OCR.** Still one image-only PDF. No real post-award document encountered yet needs it.
- **Multi-sheet and cross-sheet references.** Not present in either corpus.
- **Formulas instead of literals.** The XLSX reader already takes computed values; no real file has
  exercised the alternative.
- **Continuation-page headers.** The real BOQ has none, and item-number anchoring made them
  unnecessary.
- **Merged cells.** A PDF has none by the time it is text; an XLSX might, and none has yet.

---

## Product learning

**Consistently available in a real BOQ:** item number, a very long description, unit, quantity, rate,
amount, and a stated total. The description is the least useful field and the largest — one runs to
over 700 characters.

**Usually missing:** anything connecting the bill to a measurement or a payment. This document is
pre-award; it states what will be paid for, never what was measured or claimed. **Post-award records
are the gap, and no public source is likely to publish them** — the priority order in the brief is
right, and item 2 (sanitised industry samples) is where the value is.

**Identifiers that connect documents reliably:** the tender number connects documents of one tender;
the item number connects rows within one bill. Nothing observed connects a bill of quantities to a
measurement book except the item number — which restarts per contract and is therefore only
meaningful inside a project, as the model already assumes.

**Where manual review remains required:** any unit comparison across documents that spell units
differently (N3). The two items that previously needed it — sub-item rows and the total discrepancy —
no longer do.

**Commercially meaningful discrepancies seen so far:** none in this document, and that is now a
*result* rather than an absence of one. The bill adds up to what it says it does, checked
arithmetically over 37 rows including a credit. The 1.3% was our error, and the only reason it was
ever visible as a question is that the pipeline reports what it computed instead of what it hoped.

**The most useful thing learned:** *the checks that find document defects are the same checks that
find extraction defects, and that is a feature.* Every one of B2, B5, B6 and B7 was caught by a
number failing to reconcile — item-level arithmetic caught two, the bill total caught two more. A
pipeline that only compared documents to each other would have shipped all four. This argues for more
self-consistency checks on extracted tables, not more extraction.

**Personas** (from the SRS): the bill-total rule is the **Quantity Surveyor** and **Internal
Auditor** check, and it now exists. N3 blocks the **Billing Engineer** whenever two real documents
disagree on unit spelling, and is the next thing a real second document will force.
