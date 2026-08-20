# Real post-award data — findings

Date: 2026-08-20
Source: `RFP_806.pdf`, an NHAI bid document already in the corpus with full provenance. Pages
164–171 hold a **real priced bill of quantities**: 34 numbered line items, a stated bid price of
₹8,46,49,969.00, and none of the tidiness of a generated fixture.

No new corpus was needed. The most realistic post-award document available was already acquired and
had been sitting unread.

## Starting point

The pipeline extracted **four** facts from this 247-page document — `nit_number`, `estimated_cost`,
`bid_security`, `document_date`, all from page 6 — and **zero** work items. An eight-page priced bill
of quantities worth ₹8.46 crore was invisible, because the only table reader was XLSX-only.

After this session: **160 facts** from the bill (32 items × 5), **32 work items**, and 128 findings.

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
Now **refused** with both triples named, because this reader has no representation for a parent item
with priced children and a positional guess would put a wrong quantity into a payment
reconciliation.

### B4. Work items and findings were not persisted for the last project analysed
`reconcile_work_items` ran in the *printing* path, after the commit. A project's work items were
saved only by the next iteration's commit, so the last project's were **always rolled back**. The
real NHAI project sorts last, so its 32 work items were computed, displayed, and lost. Fixed by
moving reconciliation inside the committing transaction.

Found only because real data produced a second project. With one project it was invisible.

---

## NEXT

### N1. Extracted line items do not reconcile to the stated bid price
32 accepted rows sum to **₹85,765,191.91** against a stated **₹84,649,969.00** — 1.3% over. Two
refused sub-item rows account for part of the gap but not its direction.

**Cause not established, and deliberately not guessed at.** It is either a remaining parse error or a
property of the document, and asserting the latter would be claiming a real tender contains an
arithmetic error. This is exactly the check a quantity surveyor would want: *do the line items sum to
the total?* It should become a rule, and until then the discrepancy is recorded rather than
published.

### N2. Sub-item structure is unrepresented
`21(a)`, `21(b)` are real and common. The data model has one identifier per work item and no notion
of a parent item. Two of 34 rows are refused for this reason.

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

**Where manual review remains required:** sub-item rows, the total discrepancy, and any unit
comparison across documents that spell units differently.

**Commercially meaningful discrepancies seen so far:** none in this document, because it is
pre-award. The 1.3% total discrepancy is meaningful *if* it survives investigation, and that is
precisely the check to build next.

**Personas** (from the SRS): N1 is the **Quantity Surveyor** and **Internal Auditor** question. N3
blocks the **Billing Engineer** whenever two real documents disagree on unit spelling. N2 matters to
anyone certifying payment against a bill that uses sub-items, which appears to be normal practice.
