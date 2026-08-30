# The Tier 5 synthetic benchmark — plan, and the first run

Date: 2026-08-30. Governed by
[ADR 0019](../adr/0019-synthetic-benchmark-corpus-and-conditional-unfreeze.md) and rule 102.
Branch: `feat/synthetic-benchmark-corpus`.

> **Everything measured here is synthetic.** These numbers say a rule *executes* and is *specific*
> on generated input. They say nothing about whether it is right about documents a customer would
> upload. Quoting a detection rate from this document as a product accuracy figure is forbidden by
> rule 102.

## Why this exists

Interviews were not converting — 0.3%, measured, and six days at zero — so the freeze of 2026-08-24
was not trading engineering for market evidence. It was trading engineering for nothing. ADR 0019
lifts it and creates a fifth corpus tier so the four never-executed rules have something to run on.

## What was built

| | |
| --- | --- |
| `scripts/synthetic/spec.py` | The specification: 4 billing periods, 12 planted defects, each with hand-computed money at stake |
| `scripts/synthetic/catalogue.py` | 143 priced items across 11 trade groups, ₹11,02,91,018.00 |
| `scripts/synthetic/bundle.py` | Documents computed from catalogue + defects, with a self-check that every planted defect is present and worth what the specification says |
| `scripts/synthetic/workbooks.py` | Reproducible XLSX, byte-identical across a real time gap |
| `scripts/synthetic/render.py` | Printed PDFs via LaTeX, laid out as a bill is laid out |
| `scripts/synthetic/ground_truth.py` | The answer key, never read by the pipeline |
| `scripts/generate_synthetic_bundle.py` | Entry point — 23 files |
| `scripts/run_synthetic_benchmark.py` | Drives the product path and scores the result |

The bundle: 2 BOQ revisions, 4 measurement sheets, 4 RA bills, 1 variation order, as both
spreadsheets and PDFs. `data/synthetic/` stays gitignored — the generator is reproducible, so the
bytes are derivable and committing them would put 2 MB of fiction in the history.

## The first run

Stack: local PostgreSQL 18, MinIO from `docker-compose.yml`. **That compose file carried a note
saying it had never been executed; it has now**, and `alembic upgrade head` ran clean against a
fresh database.

```
work items created      143
findings produced       574     pass 330 · review 242 · fail 1 · inconclusive 1

planted defects         11 (plus 1 control)
  detected              5   SYN-D01 D02 D03 D04 D11
  missed, rule exists   1   SYN-D12
  missed, no rule yet   5   SYN-D05 D06 D07 D08 D10

false positives on clean rows
  systemic, one cause   223
  independent             0
controls that fired       0
```

**The four rules that had never executed on any document in any corpus tier now execute.**
`claim_within_measured_quantity`, `claimed_rate_matches_contract_rate`,
`cumulative_claim_not_below_previous_certified` and `work_item_evidence_unambiguous` ran 143 times
each and produced findings that cite both sides of the comparison. That was the point of the
exercise and it worked.

Everything below is more valuable than that.

---

## Finding 1 — the evidence model has no notion of a billing sequence

**All 242 review findings state the same cause**, verbatim:

> *N active documents state different values for `current_claim_quantity` and none supersedes the
> others, so which governs cannot be determined.*

Four RA bills are being read as four *contradictory claims about one fact*. They are not. They are
four measurements at four points in time, and RA-03 is not made obsolete by RA-04 — it is history,
and the comparison `RA-03 certified → RA-04 cumulative` is the entire product.

The only relationship the model offers is **supersession**, and supersession is the wrong relation.
A BOQ revision supersedes its predecessor. A running bill never does.

So the 223 false positives are not 223 defects. They are **one architectural gap seen 223 times**,
and every genuine finding is buried among them. A reviewer opening this project sees 242 items in
the queue, of which 5 matter.

This could only have surfaced on a bundle with more than one bill for the same items. No corpus tier
has ever contained one — which is exactly why the four rules had never run.

## Finding 2 — nothing compares a claim against the contracted quantity

SYN-D10 plants a floor area that grew after the slab was cast: 2,088.000 m² claimed against
1,960.000 m² contracted, ₹1,58,720.00. The measurement was inflated to match the claim, as it would
be by anyone doing this deliberately.

Every registered rule returns `PASS`. Claim is within measured ✓, rate matches ✓, cumulative has not
regressed ✓.

**The specification asserted this was detectable and the run disproved it.** The entry has been
corrected rather than the result explained away — that is the benchmark working. A finishing
quantity exceeding its contracted quantity is among the most ordinary overbilling patterns there is,
and no rule asks the question.

## Finding 3 — a spreadsheet bill's stated total is never checked

`bill_items_reconcile_to_stated_total` — the rule repaired on 2026-08-24 after it silently reported
that a bill stated no total when page 1 stated one — takes a `TenderNotice`, which only the **PDF**
path produces. `analyse_spreadsheet` emits `SheetFact`s and never reaches it.

SYN-D12 plants an RA bill whose printed total is ₹1,000.00 above the sum of its own rows. On the
spreadsheet path nothing looks. Given that customers send spreadsheets at least as often as PDFs,
the bill's own arithmetic is unchecked for half the intake paths.

## Finding 4 — the PDF reader cannot read a bill or a measurement sheet

Run against the rendered PDFs:

| Document | Rows read |
| --- | --- |
| BOQ (priced, 6 columns) | **143 / 143**, stated total ₹11,02,91,018.00 detected, sum matches exactly |
| Variation order | 1 / 1 |
| RA bill (7 columns) | **0** |
| Measurement sheet (4 columns) | **0** |

`pdf_boq._ROW_LINE` anchors on *unit followed by exactly three figures* — quantity, rate, amount.
A running bill has more (upto-date, previous, rate, amount); a measurement sheet has fewer (one
quantity, no money). Both fall outside the pattern entirely.

The BOQ result is genuinely good: a complete, self-consistent read of a realistically laid-out
printed bill, description wrapping across lines and all. But **the two documents the product exists
to reconcile cannot be read from PDF at all**, and PDF is how they arrive.

## Finding 5 — `cross_document_fact_agreement` compares item-scoped facts at project scope

The single `FAIL` in the run:

> *Documents of this project state different values for 7 of 7 comparable facts: `claimed_rate`:
> 68.00 in RA-Bill-02, 5,850.00 in …*

Those are two different items' rates. A project-scoped rule is treating `claimed_rate` as though a
project has one, so any real multi-item project fails it by construction. The `FAIL` is not
evidence of anything about the bundle.

## Finding 6 — kerning splits a total label, and no pattern survives it

The first render printed its total row in bold Computer Modern. pypdf recovered it as
`'T otal 11,02,91,018.00'`, and `_INLINE_TOTAL` matched nothing. The renderer was changed so the
benchmark measures what it is meant to measure, but the hazard is real and common in scanned and
typeset documents: a label split by kerning defeats an anchored pattern silently, and the failure
mode is the one that matters — the reader reports the document states no total.

---

## What this changes

Six tickets, each carrying a Tier 5 evidence ID, under epic **SCRUM-33**. Finding 1 is the one that
matters; the rest are ordinary work.

**And the honest caveat.** Every one of these is a finding about generated documents. Finding 1 in
particular predicts that a real four-bill bundle would behave the same way, and that prediction is
worth acting on — but it is a prediction, and SCRUM-10 is still the ticket that settles it.

## What would falsify this

The real bundle arrives, gets run through HEAD unchanged, and behaves differently. Then Tier 5 was
mis-shaped and gets rebuilt from what the real document showed. It does not get defended.
