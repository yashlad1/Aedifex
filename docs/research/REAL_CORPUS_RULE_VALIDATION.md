# Rule validation and reviewer session on the real building corpus

Date: 2026-08-24
Corpus: the Hostel 19 bundle (IIT Bombay, `IITB/DEAN (IPS)/CACI/H-19/NIT/R1`), 7 real documents,
plus the whole 48-document corpus for regression.

This is Phase 2 and Phase 3 of the product-validation plan: run the existing workflow as a quantity
surveyor would, record every point of friction, and validate each registered rule against real
project documents rather than synthetic fixtures. No design partner bundle exists yet, so the
strongest Tier 1 material available was used — a genuine ₹85.4 crore building tender.

## The headline

**82% of every finding in the corpus was `INCONCLUSIVE`, and not one was `FAIL`.**

| Outcome | Before | After the four fixes below |
| --- | --- | --- |
| `INCONCLUSIVE` | 255 (82.3%) | 254 |
| `PASS` | 51 (16.5%) | 51 |
| `REVIEW` | 4 (1.3%) | 5 |
| `FAIL` | 0 | 0 |

On the real building project specifically, before this session: **30 findings, of which 0 needed
human review.** A quantity surveyor could open the project, see seven documents correctly classified
and 3,319 facts extracted, and have nothing whatsoever to adjudicate.

Three of the four causes were defects, not absent evidence. They are fixed. The fourth is absent
evidence and no amount of engineering will change it.

---

## 1. Per-rule validation

Ten rules are registered: four document-scoped, four work-item-scoped, two project-scoped.

| Rule | Scope | On Hostel 19 | Validated on real building evidence? |
| --- | --- | --- | --- |
| `bid_security_share_of_estimated_cost` | document | 7 × `INCONCLUSIVE` | **Yes — correct.** True negative |
| `bid_security_matches_reference_policy` | document | 7 × `INCONCLUSIVE` | **No — structurally cannot be** |
| `bill_items_reconcile_to_stated_total` | document | 6 × `INCONCLUSIVE`, 1 × `REVIEW` | **Yes — after fix F1** |
| `priced_bill_matches_advertised_estimate` | document | 7 × `INCONCLUSIVE` | **No — scope mismatch (F3)** |
| `cross_document_fact_agreement` | project | 1 × `PASS` | **Yes — correct** |
| `bid_security_share_consistent_across_documents` | project | 1 × `INCONCLUSIVE` | Partly — one document states a share |
| `claim_within_measured_quantity` | work item | never ran | **No — F2 and missing corpus** |
| `claimed_rate_matches_contract_rate` | work item | never ran | **No — F2 and missing corpus** |
| `cumulative_claim_not_below_previous_certified` | work item | never ran | **No — F2 and missing corpus** |
| `work_item_evidence_unambiguous` | work item | never ran | **No — F2** |

### 1.1 `bid_security_share_of_estimated_cost` — correct, and the `INCONCLUSIVE` is honest

Expected: compute the bid security as a share of estimated cost, and judge it only against a rate
the document itself states.

Observed: share computed at **1.2971%** (₹1,10,76,980.00 ÷ ₹85,39,81,318.41), outcome
`INCONCLUSIVE`, `expected = NOT SOURCED`.

Verified by reading the document: the Hostel 19 NIT names its earnest money in six places
(pp. 2, 4, 5, 8, 44, 63 of the flattened text) and **never as a percentage**. It is a fixed amount.
There is no rate in the document to judge against, so `INCONCLUSIVE` is a true negative, not a
false one. This is the behaviour SRS §13 requires.

False positives: 0. False negatives: 0.

Reviewer comment: a QS still wants to know whether ₹1.10 crore is the *right* EMD. That needs a
norm from outside the document, which is the next rule.

### 1.2 `bid_security_matches_reference_policy` — cannot fire on any building document

Observed on all 7: `INCONCLUSIVE`, reason *"no `bid_security_share` provision of authority
`iitb_building_works` has been extracted"*.

The rule selects a provision whose **authority matches the document's own source**. The entire
`policy_provisions` table holds **3 provisions, all `nhai`**. So the rule can only ever fire on
Tier 2 highway documents — and it does: its only two `PASS` results in the corpus are both NHAI.

This is not a defect. Applying CPWD's or the GFR's earnest-money norm to an IIT Bombay tender is a
legal judgement about which authority *governs*, and the rule is right to refuse rather than guess.
But it means the whole Tier 3 reference corpus is inert against Tier 1 product documents, and it will
stay inert for private developers, who publish no norms of their own at all.

Classification: **missing corpus**, with a real architectural question behind it — see §4.

### 1.3 `bill_items_reconcile_to_stated_total` — was silently disabled; now the corpus's best finding

Before: `INCONCLUSIVE` on the priced BOQ, summary *"The bill's 661 priced rows add up to
843720212.19, but the document states no total of its own to compare that against."*

**Page 1 of that document states `Total 854,391,859.40`.** The summary was an assertion about the
document that the document contradicts — the worst category of error this system can produce. See
F1 below for the two independent causes.

After: `REVIEW`, expected ₹854,391,859.40, observed ₹843,720,212.19, difference **₹1,06,71,647.21
(1.2490%)**, citing page 1 for the stated total and all 661 addends for the sum.

`REVIEW` rather than `FAIL` is correct and deliberate: the rule establishes that two figures
disagree and cannot establish which is wrong. In this case the rows are almost certainly the wrong
one — the reader is missing about ₹1.07 crore of them — and the check exists precisely so that gap
becomes visible instead of silent. That mechanism had been used before (the module records unit
spellings moving a bill "from 5.7% short of its own stated total to 0.47%") and was unavailable for
every bill the anchorless reader handles.

Second real bill: `iitb-vmcc-interior-renovation-priced-bill-of-quantities.pdf` now reads its total
of ₹23,90,10,920.09 from page 129, against 455 rows summing ₹20,26,17,718.59 — **15.2% short**, a
second real extraction gap that was equally invisible.

Third real bill: `iitb-coptb-priced-bill-of-quantities.pdf`, 1,193 rows, still `None`. Verified by
reading it: it states twenty-odd `TOTAL OF <section>` lines and no total of its own. A true negative.

### 1.4 `priced_bill_matches_advertised_estimate` — the scope is wrong for real bundles

Observed on all 7: `INCONCLUSIVE`, *"stated_bill_total, estimated_cost were not extracted from this
document"*.

The rule reads two facts and requires **both from one document**. In the Hostel 19 bundle they are
in different documents, which is how building tenders are actually issued:

| Figure | Value | Where |
| --- | --- | --- |
| Priced bill's own total | ₹85,43,91,859.40 | `iitb-h19-priced-bill-of-quantities.pdf` p1 |
| Advertised estimated cost | ₹85,39,81,318.41 | `iitb-h19-notice-inviting-tender-r1-2022-10-31.pdf` p2 |
| **Difference** | **₹4,10,540.99 (0.0481%)** | |

Aedifex holds both numbers, in one project, and produces no finding comparing them — the single most
obvious question a QS asks of a priced bill. Not built in this pass; see §4.

### 1.5 The four work-item rules — never ran on the real project

All four are evaluated by `reconcile_work_items`, which the CLI calls and **the product path does
not** (F2). Every work item in the corpus belongs to an NHAI project (37) or a synthetic one (3).

So the four post-award payment rules — the primary product value under SRS §14.1, *"is what I am
being billed supported by measured work?"* — have **never been exercised on a real building
document**, and per SRS §18a a Tier 2 document may not validate them on its own.

Wiring the call is a one-line change and it is deliberately not done, because doing so today would
activate a broken item key. Measured, not predicted: see F5.

---

## 2. Reviewer friction log

Classified as the plan requires, one category each.

| # | Observation | Category | Status |
| --- | --- | --- | --- |
| F1 | A bill's own stated total is not read when the document has no "Bill of Quantities" heading, and is not read at all when the label and figure share a line | **Evidence failure** | **Fixed** |
| F4 | Several row-scoped facts from one document collapse to one candidate, silently, reported as unambiguous | **Rule failure** | **Fixed** |
| F6 | A reviewed money discrepancy is stated to ten decimal places | **Review UX failure** | **Fixed** |
| F2 | `process_project` never runs the work-item reconciliation pass the CLI runs | **Workflow failure** | Recorded, §4 |
| F5 | A composite bill's item numbering repeats, so 383 of 661 rows merge into 84 wrong work items | **Evidence failure** | Recorded, §4 |
| F3 | Bill-versus-estimate is document-scoped; real bundles state the two figures in different documents | **Rule failure** | Recorded, §4 |
| F7 | No measurement, RA bill, variation, material or quality document exists in any Tier 1 bundle | **Missing corpus** | Owner action |
| F8 | `model_agreement` maps to workflow category `reference`, so a project's own conditions of contract are excluded from contract coverage | **Workflow failure** | Recorded, minor |

### F1 — the bill's own total (fixed)

Two independent causes, both verified against the real document:

1. `_read_line_layout` — the reader used for every document with no BOQ heading, which is all three
   IIT Bombay bills — never looked for a total. It returned `PdfBoq(..., stated_total=None)`
   unconditionally.
2. `_SECTION_TOTAL` matched `Total 854,391,859.40` and skipped it as a section subtotal. Its comment
   asserted that "these bills state no single total of their own", which was true of the COPTB bill
   the comment was written against and false of the two others.

Fixed by collecting every bare total line the bill states and choosing the first that is not below
the sum of accepted rows. The magnitude guard is what separates a bill's total from a sub-bill's:
this reader can miss a priced row but never invents one, so the rows it accepted are a subset of
what a total of the *whole* bill covers. It earns its place on the VMCC bill, where four bare totals
from ₹4.33 lakh to ₹2.72 crore precede the real one — taking the first would have reported 87% of
the bill as missing.

Section totals (`TOTAL OF SECTION A`) and GST-inclusive totals (`Total with GST`) are excluded by the
label shape. Excluding the GST line matters: comparing rows quoted without tax against a total
quoted with it would report an 18% discrepancy that does not exist.

Regression across the whole corpus: two bills gain a correct total, one correctly gains none, the
NHAI RFP's existing total is untouched (it uses the heading-anchored path), and reference documents
never reach the reader at all — `is_reference` already excludes audit reports and manuals, which is
what stops "Total 100.00" in a price-index manual becoming a bill total.

### F4 — row order was an authority again (fixed)

`selection.py` exists to remove one line, `{fact.fact_type: fact for fact in facts}`, whose defect
its own docstring states: *"silently kept whichever fact the database happened to return last. Row
order is not an authority."*

`_newest_per_document` reintroduced it. Keyed on `document_id` alone, the 49 different priced rows
that normalise to Hostel 19's item `1.3` — quantities from 102 to 1,250 — arrived as candidates for
one work item and 48 were discarded because `4 > 4` is false. Measured directly:

```
item '1.3' spans 49 rows; 49 contracted_quantity facts
  selected     : 910.00 (row 203)      <- whichever row came back first
  considered   : 1
  conflicting  : False
  reason       : the only active document stating contracted_quantity
```

The reason is a false statement about the evidence, inside the field whose purpose is to explain the
evidence. Had a measurement book been uploaded, `claim_within_measured_quantity` would have compared
a claim against one arbitrarily chosen item's contracted quantity and returned a confident verdict.

Now keyed on `(document, row)`: two readings of one row still resolve to the newer, two different
rows stay two claims, and the existing disagreement policy refuses. The reason string was corrected
too — it counted candidates as documents, which was accurate only while there was one candidate per
document.

**No stored finding changed.** Verified before the change: no work item in the corpus pools two
distinct rows of one document at one extractor version, because the only bill that would have — Hostel
19's — has never been reconciled, thanks to F2.

### F6 — money to ten decimal places (fixed)

`derived_facts.numeric_value` is `numeric(28,10)`. Every branch of `evaluate_bill_total` sends its
figures through `_money` except the `REVIEW` branch, which had never been reached by a derived total.
The first real reviewable finding in the corpus therefore read: *"661 priced rows add up to
843720212.1900000000, which is 10671647.2100000000 under 854391859.40"* — eight meaningless zeros on
a rupee figure, in the one sentence written to be read and acted on. Every sibling rule already
routes through a formatter; this was the only offender.

---

## 3. What the reviewer can now do

Re-running the workflow through the product API on the real project:

```
POST /v1/projects/{id}/process?reprocess=true
  → processed 7, unsupported 0, failed 0; 3,312 facts, 28 document findings, 2 project findings

GET  /v1/projects/{id}/summary
  → findings_by_outcome  {inconclusive: 28, pass: 1, review: 1}
  → findings_awaiting_review  1        (was 0)
  → stale_reviews  0
  → documents_by_status  {processed: 6, needs_attention: 1}
```

The priced BOQ is now flagged `needs_attention`, and the finding it carries is fully traceable: the
stated total cites `Total 854,391,859.40` on **page 1** so the reviewer can open the artifact at the
exact page, and the derived sum carries all 661 addends so the addition can be redone by hand, as its
summary promises. All five pre-existing reviews remain current; none was invalidated.

That is one finding, not a queue. It is nonetheless the first evidence-backed, reviewable,
non-trivial conclusion this system has produced from a real building document.

---

## 4. Recorded and deliberately not built

### F2 + F5 — the work-item pass, and why wiring it today would make the product worse

`process_project` runs each document's analysis and then `analyse_project`. The CLI runs
`reconcile_work_items` as well, inside the committing transaction, with a comment explaining that it
must. The product path omits it, so no project created through the API or the UI has ever had a work
item, and the four payment rules have never run for a customer.

Adding the call is one line. Measured on the real project, rolled back:

| | |
| --- | --- |
| Work items created | **278**, from 661 priced rows |
| Findings produced | **1,112** |
| `PASS` | 194 |
| `INCONCLUSIVE` | 750 — no measurement or bill document exists to compare against |
| `REVIEW` | **168** — two rules × the same 84 items |

The 278 is the problem. `normalise_item` treats a hierarchical number as unique within a project, but
a composite bill restarts its numbering in each part: item `1.3` appears on **49** rows across 13
pages, `1.3.5` on 24, `1.1` on 21. **84 identifiers collide and swallow 383 of the 661 rows.**

So wiring the pass would take the reviewer's queue from 1 high-value finding to 169, of which 168 are
the same sentence about repeated item numbers, burying the ₹1.07 crore discrepancy underneath. The
findings would at least be *honest* now that F4 is fixed — before it, the 84 would have been silent
false `PASS`es resting on an arbitrarily chosen row.

The blocker is F5, not F2. Deciding what a work item's canonical key *is* for a composite bill — part
plus section plus number? the description? a customer's own item code? — is a domain question that
should be settled against a real design-partner bundle, not invented against one university tender.
Wiring F2 without it would ship 168 findings per building project resting on a key that provably
merges unrelated rows.

**Recommendation:** wire F2 and fix F5 together, on the first real bundle.

### F3 — the project-scoped bill-versus-estimate rule

All the evidence is already stored: ₹85,43,91,859.40 from the bill, ₹85,39,81,318.41 from the notice,
₹4,10,540.99 apart. `PROJECT_RULES` already exists and already holds two members, so this is
horizontal expansion of the kind SRS §19 endorses, not new architecture.

Not built, for a substantive reason rather than caution: with one project I cannot tell what
₹4.1 lakh at 0.048% *means*. A percentage-rate tender invites bids above or below the estimate by
design, the bill states its own total to the paisa while the notice rounds, and no authority in the
corpus publishes a permitted variance. Whether the right outcome is `INCONCLUSIVE`-with-difference
(as `priced_bill_matches_advertised_estimate` already chooses, for exactly this reason) or something
sharper is a question a second and third real bundle answers and a single one does not.

This is the strongest candidate for the next rule.

### F7 — the missing documents

`documents_by_category` for the real project: `contract 2, boq 1, reference 3, other 1`. Nothing in
**measurement, RA bill, variation, material, or quality**. The bundle is tender-stage only, which is
all a public university publishes.

Six of ten rules cannot be validated without post-award documents, and no engineering removes that.
This is the Phase 1 owner action, and it gates more value than any code in this repository.

### F8 — a project's own contract conditions are categorised as reference

`iitb-h19-conditions-of-contract.pdf` is typed `model_agreement` (human-confirmed) and
`WORKFLOW_CATEGORY` maps that to `reference`, so the project's own general conditions of contract do
not count toward contract coverage. For a *model* agreement published by an authority that is right;
for a bundle's own conditions it is not. Left alone: the distinction is between a norm and an
instrument, and one project is not enough to know which way real bundles lean.

---

## 5. What the next bundle must contain

To validate the six unvalidated rules, in priority order:

| Document | Unblocks |
| --- | --- |
| **Measurement sheet / JMR** | `claim_within_measured_quantity` — the primary product question |
| **RA bill** (two consecutive, ideally) | `claimed_rate_matches_contract_rate`, `cumulative_claim_not_below_previous_certified` |
| **Priced BOQ with the contractor's own item codes** | F5 — settles what a work-item key is |
| **Payment / architect certificate** | the certification link, currently absent from the model |
| **The employer's own EMD or security norm** | `bid_security_matches_reference_policy` against a non-NHAI authority |

One bundle containing a BOQ, a measurement sheet and two RA bills for the same items would validate
more rules than the entire 48-document public corpus has.

---

## 6. Cross-references

- [POLICY_RULE_COVERAGE.md](POLICY_RULE_COVERAGE.md) reached the same conclusion on 2026-08-20 from
  the NHAI tender — "almost everything is blocked by missing corpus, essentially nothing by missing
  architecture". This session confirms it on a building bundle and adds that three of the four
  Hostel 19 blockages were defects rather than absent evidence.
- [PRODUCT_FIRST_CORPUS_DISCOVERY.md](PRODUCT_FIRST_CORPUS_DISCOVERY.md) predicted the structural gap
  at Measurement and RA Bill. F7 is that gap, measured on a real project.
- [BUILDING_CORPUS_AVAILABILITY.md](BUILDING_CORPUS_AVAILABILITY.md) records why the priced-BOQ
  reader could not read these bills. F1 removes one of the reasons.

---

## 7. SCRUM-17: why priced rows went unread

Investigated 2026-08-24 against the three real IIT Bombay building bills and the NHAI bid document,
before changing any code. The instrument is each bill's **own section subtotals**: a section whose
accepted rows equal its stated subtotal is fully read, and anything else localises the gap to a span
of pages small enough to read by eye. That is what turns "1.25% short" into a cause.

### 7.1 The five questions

**1. How many rows, and how much?** On Hostel 19 the instrument accounts for the shortfall exactly:
41 leaf sections summing to ₹85,43,91,859.42 against a stated total of ₹85,43,91,859.40, and a net
of **−₹1,06,71,647.23** against the finding's −₹1,06,71,647.21. 31 of 41 sections reconciled to
within 5 paise; 10 were short.

**2. Which documents?** All three IIT Bombay bills. The NHAI bid document reconciles exactly — its
37 rows equal its stated ₹8,46,49,969.01 — so this is specific to the anchorless line reader, not to
the module.

**3. Systematic or isolated?** Systematic and localised. The civil schedules are near-exact: Hostel
19's civil half had **one** miss in 21 sections. The gaps are in the MEP schedules, and the
**fire-pump section under-reads in all three bills** — Hostel 19 −₹32,84,495.42, VMCC −₹3,22,670.00,
COPTB −₹17,42,506.00.

**4. Would recovery materially improve construction evidence?** Yes, and not only in money. Each
unread row is a work item with a quantity and a rate. A BOQ row that is absent gives a future RA-bill
claim for that item nothing to be verified against, which is the whole of `claim_within_measured_quantity`.

**5. Is the current behaviour actually incorrect?** For Hostel 19, **yes, provably**: its own leaf
sections sum to its own stated total, so nothing is un-itemised and every gap is a row the reader
missed. For COPTB, **unproven** — that bill states no grand total, so its extraction cannot be
validated against itself at all. Said plainly rather than assumed either way.

### 7.2 Classification

| Cause | Class | Rows | Amount (H19) | Action |
| --- | --- | --- | --- | --- |
| Unit spelled `RM`, `Pt.`, `pts.`, `sets` | **parser defect** | 13 | ₹48,56,587.46 | **Fixed** |
| Unit borrowed a letter from the description (`conductorMtr` → `rMtr`) | **parser defect** | 1 (COPTB) | — wrong label, not lost money | **Fixed** |
| Row split across lines: unit and quantity apart from rate and amount | **unsupported document structure** | ~24 | ₹58,15,059.75 | SCRUM-24 |
| Source states no unit for the row | **corrupt/malformed source** | 1 (+18 VMCC) | ₹7,81,570.88 | SCRUM-25 |
| Section subtotals differing by 1–2 paise | **intentionally non-data** | — | ±₹0.02 | None — the bill's own rounding |

Nothing was classified "ambiguous evidence" or "extraction defect": every case resolved to one of
the above once the page was read.

### 7.3 What was fixed, and what proves it

Four unit spellings, and `Rmtr` moved under the same guard. **The bills' own subtotals prove each
one, which is the difference between a fix and a coverage number:** Hostel 19's electrical section A
stated ₹1,19,52,516.44 against 12 rows worth ₹73,34,366.51, and the two rows measured in `RM` are
worth exactly the ₹46,18,149.93 difference. Sections D and E closed the same way on `pts.` and `Pt.`
— to the paisa, not to a tolerance.

| | Before | After |
| --- | --- | --- |
| Hostel 19 rows | 661 | **674** |
| Hostel 19 read | ₹84,37,20,212.19 | **₹84,85,76,799.65** |
| Shortfall against its own total | −₹1,06,71,647.21 (1.2490%) | **−₹58,15,059.75 (0.6806%)** |
| Sections reconciling | 31 of 41 | **34 of 41** |
| VMCC / COPTB / NHAI rows | 455 / 1193 / 37 | **455 / 1193 / 37** — unchanged |

Three NHAI rows additionally gained a unit (`Rm`) that they previously carried as null, with the row
count and total untouched.

**A regression test caught the fix trying to fabricate a row.** Adding `RM` unguarded made
"Providing and laying the platform 12 100.00 1200.00" a priced row measured in `rm`, taking the unit
from inside "platform" and asserting a quantity and a rate nobody wrote down. The first guard tried —
a word boundary on every unit — then refused **12 genuine COPTB rows**, because a flattened PDF really
does glue a unit to the last word of its description (`worksKg`, `4885No.`, `conductorMtr`). The
guard now applies only to the short names being added, which refuses the fabrication and keeps all
twelve.

The extractor version moved to **5**. A row that was absent is now present and a unit that was null
now has a value; both belong to a new version rather than silently replacing what v4 recorded, which
is what lets `_newest_per_claim` prefer the better reading per row while the earlier one stays
queryable.

### 7.4 Deliberately not fixed

`SCRUM-24` (exploded rows, ₹58,15,059.75) and `SCRUM-25` (rows with no unit) are filed with the
evidence. Neither is a regex widening: the first would run a positional block parser over pages where
90% of rows are already read correctly by the line reader, so the real question is how two readers
cooperate over one document without counting a row twice — and over-reading money is worse than
under-reading it, because a missing row is a gap the bill's own total exposes and a double-counted one
is not.
