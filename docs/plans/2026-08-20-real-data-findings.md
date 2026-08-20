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

### N3. Units are corpus-specific and uncompared across sources
The real BOQ uses `Cum`, `Sqm`, `Nos`, `Kg`, `Rm`. The synthetic set uses `m3`, `MT`. Nothing
converts, which is correct — but nothing recognises `Cum` and `m3` as the same dimension either, so a
real BOQ and a real measurement book using different spellings would be refused as a unit mismatch
rather than reconciled.

### N4. Rounding differences of ₹10–13 exist between stated amounts and quantity × rate
Two rows near ₹9,000,000 are out by ₹10.20 and ₹13.10. Absorbed by tolerance (`max(₹100, 0.05%)`).
Real, immaterial, and worth knowing when a rule eventually compares totals.

---

## DEFERRED

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
