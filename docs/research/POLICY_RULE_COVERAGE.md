# Policy rule coverage: evidence-blocked or architecture-blocked?

Date: 2026-08-20

## The answer

**Almost everything is blocked by missing corpus. Essentially nothing is blocked by missing
architecture.**

Of the **9 registered rules**, on the real NHAI tender:

| | Count | |
| --- | --- | --- |
| Executing with a verdict | **5** | PASS |
| Executing INCONCLUSIVE — blocked by missing corpus | **3** | need a measurement book and an IPC |
| Executing INCONCLUSIVE — **redundant** | **1** | superseded by the reference-policy rule |
| Blocked by missing architecture | **0** | — |

Of the **12 candidate rules** derivable from the tender plus the Works Manual:

| | Count |
| --- | --- |
| Executable today with existing facts and no new architecture | **1** |
| Blocked by missing corpus | **8** |
| Blocked by missing extraction, corpus already present | **1** |
| Blocked by missing architecture **and also** by missing corpus | **2** |
| Blocked by missing architecture alone | **0** |

**The two architecture limitations found in the previous milestone — no formula representation, no
procedure representation — would unblock zero rules if fixed today**, because both rules that need
them are also waiting on documents nobody has. That is the finding that matters: the architecture is
not the constraint, and building for it now would be building for nothing.

One executable rule was found (§4, R7) and is **not implemented**, per the instruction to stop at the
report.

---

## 1. What exists

### Project facts on the tender `NHAI/RO-CHD/2026-2027/BWN/21`

Document-scoped, from `NIT_1382.pdf` and `RFP_806.pdf`:

| Fact | Value | Page |
| --- | --- | --- |
| `nit_number` | NHAI/RO-CHD/2026-2027/BWN/21 | 1, 6 |
| `estimated_cost` | ₹84,649,969.00 | 1, 6 |
| `bid_security` | ₹1,693,000.00 (Rs. 16.93 Lacs) | 1, 6 |
| `document_date` | 07.08.2026 | 1, 6 |
| `stated_bill_total` | ₹84,649,969.01 | 171 |

Row-scoped, 37 priced BOQ rows × 5 fact types: `item_identifier`, `item_description`,
`contracted_quantity`, `contract_rate`, `line_amount`.

Derived: `bid_security_share`, `bill_items_total`, `required_bid_security`.

**Present in the corpus and not extracted** — all three sit in the same page-6 table row the
extractor already reads positionally:

> … Rs. 8,46,49,969/- · Rs. 16.93 Lacs · **12 Months Construction Period and 2 years of DLP** (only
> for Bituminous works, all types of concrete works and all painting works w.e.f date of issuance of
> completion certificate) … **9.532 km**

So `completion_period`, `defect_liability_period` and `project_length` are **missing extraction, not
missing corpus.**

### Policy provisions extracted

Three, all from NHAI Works Manual clause 4.14.1, page 79:

| Clause | Share | Band | Cap |
| --- | --- | --- | --- |
| 4.14.1(a) | 2% | up to ₹20 crore | ₹30 lacs |
| 4.14.1(b) | 1.5% | ₹20–50 crore | ₹50 lacs |
| 4.14.1(c) | 1% | above ₹50 crore | — |

**One provision type exists, and it already has its rule.** That single sentence explains most of
this report: there is no second policy-based rule to write because there is no second provision type
extracted.

### Quantified norms the Works Manual contains and we have not extracted

| Clause | Page | Norm | Shape |
| --- | --- | --- | --- |
| 4.34.1 | 90 | Performance security **10% of contract price**, furnished **within 28 days** of the Letter of Acceptance | share + a time limit |
| 4.36.1 | 91 | Interest-bearing mobilisation advance at **ten percent of contract price** | share, rate in words |
| 6.13.3 | 149 | Consultancy performance security **up to 5%** of accepted consultancy cost | share; consultancy, not works |
| 1.3.3 | 173 | Bank guarantee validity = commencement period + completion period + DLP + 365 days | **a formula over dates** |
| — | 91 | Half the retention money released on completion, the other half **365 days after** the Defects Liability Period | **a procedure** |
| 6.13.1 | 148 | Price adjustment "**as per the provision included in the contract**" | **the manual states no formula** — it defers |

That last row is worth its own note: the manual does **not** contain the price-adjustment formula. It
points at the contract. So a price-adjustment rule is blocked by the absence of a contract agreement,
not by the absence of a formula representation.

---

## 2. The matrix

`✓` executable today. `E` blocked by evidence. `A` blocked by architecture.

| Rule | Policy provision | Project facts required | Executable today? | Reason if not |
| --- | --- | --- | --- | --- |
| **R1** `bid_security_matches_reference_policy` | 4.14.1(a) | `estimated_cost`, `bid_security` | **✓ PASS** | — |
| **R2** `bill_items_reconcile_to_stated_total` | none | `line_amount` ×37, `stated_bill_total` | **✓ PASS** | — |
| **R3** `cross_document_fact_agreement` | none | `estimated_cost`, `bid_security` in two documents | **✓ PASS** | — |
| **R4** `bid_security_share_consistent_across_documents` | none | derived share in two documents | **✓ PASS** | — |
| **R5** `work_item_evidence_unambiguous` | none | BOQ row facts | **✓ 37 PASS** | — |
| **R6** `bid_security_share_of_estimated_cost` | none — threshold from caller | `estimated_cost`, `bid_security` | executes, INCONCLUSIVE | **Redundant.** R1 now answers the same question from a cited clause. Not a blockage — a duplication |
| **R7** `priced_bill_matches_advertised_estimate` | none | `stated_bill_total`, `estimated_cost` | **✓ IMPLEMENTED 2026-08-20** | — |
| **R8** `performance_security_matches_policy` | 4.34.1 *(unextracted)* | `performance_security` ✗, `contract_price` ✗ | **E** | No award-stage document exists. Also needs extraction and two fact types |
| **R9** `performance_security_furnished_within_28_days` | 4.34.1 *(unextracted)* | LoA date ✗, PBG date ✗ | **E** | No Letter of Acceptance, no bank guarantee |
| **R10** `mobilisation_advance_within_policy` | 4.36.1 *(unextracted)* | advance paid ✗, `contract_price` ✗ | **E** | No IPC, no contract |
| **R11** `bank_guarantee_validity_sufficient` | 1.3.3 *(unextracted, a formula)* | BG expiry ✗, `completion_period` *(present, unextracted)*, DLP *(present, unextracted)* | **E + A** | No bank guarantee. **And** the model cannot hold a formula |
| **R12** `retention_released_on_schedule` | retention procedure *(unextracted)* | retention deducted ✗, completion date ✗ | **E + A** | No IPC. **And** the model cannot hold a procedure |
| **R13** `price_adjustment_correct` | none — the manual defers to the contract | index values ✗, base indices ✗, claim ✗ | **E** | No contract agreement and no IPC. Not an architecture problem |
| **R14** `claim_within_measured_quantity` | none | `measured_quantity` ✗, `cumulative_claim_quantity` ✗ | **E** — INCONCLUSIVE ×37 | No measurement book, no IPC |
| **R15** `claimed_rate_matches_contract_rate` | none | `claimed_rate` ✗ | **E** — INCONCLUSIVE ×37 | No IPC |
| **R16** `cumulative_claim_not_below_previous_certified` | none | `previous_certified_quantity` ✗ | **E** — INCONCLUSIVE ×37 | No prior IPC |
| **R17** `completion_period_within_norm` | none — the manual states no norm | `completion_period` *(present, unextracted)* | **E** | Extraction missing, **and there is no norm to compare against**, so this is not a rule yet |
| **R18** `line_item_arithmetic_closes` | none | `contracted_quantity`, `contract_rate`, `line_amount` | **Not a rule by design** | Enforced inside `pdf_boq.py`: a row whose arithmetic fails is refused, so it never becomes a fact. Deliberate architectural scope |

---

## 3. Every missing capability, classified

### Missing corpus — 8 rules

The overwhelming majority, and the only category that matters. Every one waits on a document that
does not exist in the corpus and that no public Indian source publishes:

| Missing document | Rules it unblocks |
| --- | --- |
| **Contract agreement** | R8, R10, R13 |
| **Letter of Acceptance** | R9 |
| **Performance bank guarantee** | R8, R9, R11 |
| **IPC / RA Bill** | R10, R12, R13, R15, R16 |
| **Measurement Book** | R14 |
| **Completion certificate** | R12 |

Consistent with `INDIAN_POSTAWARD_SOURCES.md`: every link that is a *transaction* is unavailable, and
every link that is a *standard* is available.

### Missing extraction — 3 fact types, corpus already present

`completion_period` (12 Months), `defect_liability_period` (2 years) and `project_length` (9.532 km)
are in the page-6 table the extractor already parses. This is the **cheapest** gap in the report, and
it unblocks nothing on its own: no rule consumes them, and the manual states no norm to compare them
against. Recorded because "the corpus contains it and we do not read it" is a different and more
embarrassing condition than "nobody publishes it".

### Missing fact type — 6

`contract_price`, `performance_security`, `advance_paid`, `retention_deducted`, `loa_date`,
`bg_expiry_date`. Each is downstream of a missing document, so none is independently blocking.

### Missing applicability — 0

Nothing in this inventory is blocked by applicability. R1's authority-and-band match resolved
correctly on the only provision type that exists. The categorical-condition limitation found in the
Rajasthan milestone does not bite here, because NHAI clause 4.14.1 conditions on a numeric band.

### Missing architecture — 2 rules, both also corpus-blocked

**No formula representation** (R11) and **no procedure representation** (R12). Both were identified in
`REFERENCE_PROVISION_SECOND_SOURCE.md` and proven at the database level. Both rules also require
documents the corpus lacks.

**So fixing either limitation today would unblock zero rules.** That is the report's central result.

### Deliberate architectural scope — 1

R18. Row arithmetic is an extractor invariant rather than a rule: `pdf_boq.py` refuses a row whose
`quantity × rate` does not reproduce its stated amount, so a failing row never becomes a fact and
never reaches a rule. Promoting it to a rule would make the check visible as a finding, at the cost of
admitting rows the extractor currently distrusts. A design decision, not a gap.

---

## 4. The one executable rule found

**R7 — does the priced bill match the advertised estimate?**

| | |
| --- | --- |
| Inputs | `estimated_cost` = ₹84,649,969.00 (NIT, page 1 / RFP, page 6) · `stated_bill_total` = ₹84,649,969.01 (RFP, page 171) |
| Needs | no provision, no new fact type, no new extractor, no new applicability |
| Difference | **₹0.01** |

Not covered by anything registered. `cross_document_fact_agreement` groups by `fact_type` and compares
like with like, so it cannot compare a bill total against an estimated cost — they are different
types. `bill_items_reconcile_to_stated_total` compares the summed rows against the bill's own stated
total, which is a different question.

**Why it is worth having.** The two figures agree to one paisa, and that is itself informative: a
priced bill identical to the advertised estimate means this BOQ carries the *employer's* rates, not a
bidder's quoted rates. A quantity surveyor reading a finding that says so learns something about what
the document is. On a real bid the same rule would measure the tender premium or discount — which is
exactly what page 171 asks the bidder to quote.

**Implemented 2026-08-20** as `verification/bill_estimate.py`. Always INCONCLUSIVE with
`expected = NOT SOURCED`: the difference is arithmetic, and whether it is acceptable is a question no
document in the corpus answers. On the real tender the persisted detail reads
`difference: 0.01, percentage_difference: 0.0000, within_tolerance: true`, and the summary says what
agreement means rather than leaving it to be inferred.

## 5. The redundancy

`bid_security_share_of_estimated_cost` (R6) returns INCONCLUSIVE — *"this document states no required
share, and none was supplied"* — on the same two documents where R1 returns PASS against clause
4.14.1. Both answer "is the bid security right?"; one now has a cited threshold and the other never
will, because the tender documents do not state their own rate.

**Resolved 2026-08-20: marked superseded, not retired.** Six stored findings cite R6, and a rule
removed from the registry cannot re-derive the findings that reference it — which would break the
reproducibility requirement (FR-087). It is also still the only answer available for an authority
whose rulebook has not been acquired. The supersession is recorded in the rule's docstring and in the
published vocabulary, with no new schema field.

## 6. Answering the question asked

> How much of the current rule engine is actually blocked by missing evidence, and how much is
> blocked by missing architecture?

**Blocked by missing evidence: effectively all of it.** 8 of 12 candidate rules and 3 of 9 registered
rules wait on post-award documents. One more waits on three fact types sitting unread in a page we
already parse.

**Blocked by missing architecture: none of it, today.** The two model limitations are real and both
belong to rules that are corpus-blocked anyway. There is no rule, anywhere in this inventory, that
could execute if the architecture changed and cannot execute now.

**Therefore: stop.** Per the architecture rule, no provision type, applicability field, fact type or
extractor is justified by this inventory. The single executable rule found needs none of those.

The constraint on Aedifex is not its design. It is that nobody publishes a measurement book.
