# Real audit patterns, catalogued from CAG reports

Date: 2026-08-21
Source documents: five CAG audit reports acquired 2026-08-21 under source `india_audit_reports`.

## Why this document exists

Every rule Aedifex has implemented so far was derived from a document that *states a norm* — the
NHAI Works Manual's bid-security bands, a tender's Instructions to Bidders. That answers "what
should happen". It does not answer the question a verification platform actually has to get right:
**which discrepancies are worth flagging, and what does an auditor need in hand to flag one?**

A CAG report answers exactly that, because it *is* a completed verification. The auditor names the
rule, names the documents examined, performs the arithmetic, and states the money consequence. That
is the shape of an Aedifex finding, written by a professional auditor with the primary records in
front of them.

**So this catalogue is read backwards from a real finding to the evidence it required.** For each
pattern: the rule invoked, the comparison performed, the arithmetic, and then the honest answer to
*can Aedifex express this deterministically today, and if not, exactly which document is missing?*

## The boundary that must not be crossed

**A CAG report is audit evidence. It is never primary project evidence.**

Every quantity, rate and payment in this document was read by an auditor out of a measurement book,
a running account bill, an agreement or a sanction that Aedifex does not hold. The figures appear
here at the auditor's chosen precision, framed by the point the auditor was making, and often
rounded to lakh or crore. Treating one as though it came from a measurement book would manufacture
primary evidence out of secondary evidence.

What these documents *are* primary evidence of is the audit finding itself. That is why the source
entry sets `document_type: audit_report`, and why the extractor now suppresses document-scoped facts
from them — see [the Phase 1 report](../plans/2026-08-21-phase-1-acquisition.md) for the three false
`estimated_cost` facts that established the need.

---

## 1. Extra item paid at another BOQ item's rate — reproduced to the rupee

**Source.** CAG Report No. 3 of 2022, Government of Karnataka, Compliance Audit, Chapter II Part I,
paragraph 2.14, pages 66–68. Karnataka Urban Water Supply and Drainage Board, UGD scheme,
Nanjangudu town.

**Rule invoked.** Tender clause 35.3 — where the BOQ carries no rate for an additional, substituted
or altered item, the rate must be derived from the BOQ or from the Schedule of Rates applicable to
the area and current at award, plus or minus the overall tender percentage over the Current Schedule
of Rates. Plus the KPWD Code — variation payments require the approval of the authority that
accorded technical sanction.

**What happened.** "Excavation in hard rock by controlled blasting for STP" was not in the BOQ. The
Executive Engineer paid it at the rate for a *different* BOQ item — controlled blasting for a wet
well — instead of treating it as an extra item priced from MISR 2014-15 plus tender premium.

**The arithmetic, as the report states it and as re-computed here:**

| Depth | Quantity executed (CuM) | Rate paid (₹/CuM) | Rate admissible (₹/CuM) | Excess rate | Excess payment |
| --- | --- | --- | --- | --- | --- |
| 0–2 m | 12,550.28 | 1,688.34 | 671 | 1,017.34 | 12,767,901.86 |
| 2–4 m | 2,202.72 | 1,782.14 | 671 | 1,111.14 | 2,447,530.30 |
| 4–6 m | 735.26 | 1,875.93 | 671 | 1,204.93 | 885,936.83 |
| | | | | **Total** | **16,101,368.99** |

Re-computed in exact `Decimal`: `quantity × (rate_paid − rate_admissible)`, summed, gives
**₹16,101,368.99**, and the report's own narrative total is **₹1,61,01,369**. It reproduces to the
rupee.

**A detail worth keeping.** The report's *table* prints the total as `1,61,01,36.99` — a mangled
`1,61,01,368.99`, digits transposed in typesetting. The narrative two paragraphs later gives the
correct figure. This is a real instance of a stated total being wrong while remaining reconstructible
from its own line items, which is precisely what `bill_items_reconcile_to_stated_total` exists to
catch. It also shows why that rule returns `REVIEW` and not `FAIL`: the discrepancy here is a typo,
not a fraud.

**Can Aedifex express this today? NO — and the gap is one document.**

| Fact required | Status |
| --- | --- |
| Measured quantity per depth band | **Missing.** Needs a Measurement Book. |
| Rate paid per item | **Missing.** Needs a Running Account Bill. |
| Admissible rate (SR rate + tender premium) | **Missing.** Needs a Schedule of Rates, and the contract's tender percentage. |
| Item's status as extra / variation | **Missing.** Needs a Variation Order. |
| The arithmetic | **Present.** `Decimal` money arithmetic and the derived-fact chain already do exactly this. |

The comparison is `claimed_rate` against `contract_rate`, which
`claimed_rate_matches_contract_rate` already implements — it has run 40 times, against synthetic
data only. What is missing is not code. It is a real MB and a real RA bill for one project.

---

## 2. Mobilisation advance paid above the prescribed ceiling — expressible today

**Source.** CAG Report No. 3 of 2022, Karnataka, paragraph 2.15, pages 68–70. Karnataka Slum
Development Board.

**Rule invoked.** Section 200 of the Karnataka Public Works Departmental (KPWD) Code — mobilisation
advance to the extent of **5% of the agreement amount**, within 15 days of the work order, against a
bank guarantee from a scheduled bank.

**What happened.** The Board paid mobilisation advance at **10% of the tendered cost** for the
construction of 252 dwelling units at M R Jayanagar slum, Malleshwaram — twice the ceiling.

**Can Aedifex express this today? YES, structurally — the model already fits.**

This is the same shape as the NHAI bid-security rule that is already implemented and passing: *a
published share of a stated base, with an authority, a clause and a threshold.* The
`policy_provisions` table represents it without modification —
`provision_type: mobilisation_advance_share`, `authority: Karnataka PWD`, `clause: Section 200`,
`applies_to: agreement_amount`, `share: 0.05`. No formula, no procedure, no new applicability model.

What is required is evidence, not architecture:

| Fact required | Status |
| --- | --- |
| Prescribed share (5%) with authority, clause, page, span | **Acquirable.** The KPWD Code is a published state works code — a Phase-2 acquisition, directly analogous to the Rajasthan PWFAR volumes already held. |
| Agreement amount | **Acquirable.** Stated in a contract agreement; NHAI publishes these. |
| Advance actually paid | **Missing.** Needs an RA bill, IPC or payment certificate. |

**This is the highest-value next rule in the catalogue**, because it re-uses a proven mechanism and
needs only two documents, one of which is already a known public source.

---

## 3. Mobilisation advance not recovered within the contractual window

**Source.** Same paragraph 2.15.

**Rule invoked.** Clause 42 of the standard tender document — recovery commences from the next
interim payment certificate or three months from the first instalment, **whichever is earlier**, and
the advance must be fully repaid before expiry of the original or extended completion time. Plus the
Central Vigilance Commission's April 2007 direction that recovery be **time-based, not linked to
progress of work**.

**What happened.** Across five delayed works, ₹16.51 crore was released as mobilisation advance and
₹12.54 crore — 76% — remained unrecovered as at 31 March 2021, with no extension of time granted.
Audit computed the interest loss at ₹1.73 crore.

**Can Aedifex express this today? NO — and this one needs a time series, not a document.**

| Fact required | Status |
| --- | --- |
| Advance released, with its date | Missing |
| Recovery per interim payment certificate | **Missing, and it is a *series*** — one figure per bill, not one figure. |
| Original and extended completion dates | Missing |
| Interest rate for the loss computation | Missing — the report's rate is in a footnote |

The structural point: **this rule cannot be evaluated from any single document.** It needs the
sequence of IPCs for one contract. Every rule Aedifex implements today reads one document, or two
documents of the same project. A recovery schedule is the first pattern in this catalogue that
requires a *chronological series* of the same document type — and the acquisition strategy's
observation that Aedifex holds no post-award series at all is what blocks it.

The CVC direction is also worth recording as a representational question: "recovery shall be
time-based and not linked to progress" is a **prohibition on a method**, not a threshold. The
Reference Provision model represents thresholds and shares. It cannot represent "you may not
compute it that way." Noted, not built — no rule is blocked by it today.

---

## 4. Excess payment on price adjustment computed from the wrong index

**Source.** CAG Report No. 23 of 2021, Union Government (Civil), Ministry of Home Affairs,
Performance Audit of the Indo-Nepal Border Road Project, Chapter 4, page 11, Table 9 item 4.

**Rule invoked.** The contract's price-neutralisation clause.

**What happened, verbatim:** "In two contracts pertaining to Araria Division, prices of Bitumen and
WPI index used for computing price neutralisation was different from actual Bitumen prices and WPI
index. Therefore, excess payment of ₹ 67.36 lakh was made under price neutralisation."

**Why this is the most interesting entry in the catalogue.** It is the one audit finding that names
a reference series Aedifex now actually holds. The WPI workbook acquired the same day carries
**Bitumen, commodity code 1202010007**, monthly from Apr-23 to Jul-26, published by the Office of
the Economic Adviser. The reference half of this rule is in the corpus. The project half is not.

**Can Aedifex express this today? NO — and precisely one thing is missing.**

| Fact required | Status |
| --- | --- |
| WPI index for the applicable month | **PRESENT.** Held as reference evidence with authority, base year and provenance. |
| The contract's price-adjustment formula and its named index | **Missing.** This is the blocker. |
| Base index and base month | **Missing** — stated in the contract. |
| Index actually applied in the bill | **Missing** — stated in the RA bill. |
| Quantity or value the adjustment applies to | **Missing** — stated in the RA bill. |

The formula is the blocker, and it is a genuine representational gap, not just an evidence gap.
`P = 0.85 × (Q × R) × (WPI_current − WPI_base) / WPI_base` is an **expression over named indices**,
and the `policy_provisions` table stores a share and a cap — a single multiplication. This is the
"no formula representation" limitation the second-source study already identified as a proven
limitation of the model. **This audit finding is the first real-world evidence that it will
eventually have to be closed.** It should not be closed until a contract in the corpus states such a
formula, because designing a formula representation against no example is how you get the wrong one.

**A base-year trap, recorded because it would silently corrupt every such calculation.** WPI now
publishes base 2022-23 alongside 2011-12, with official linking factors, and CPI carries base 2010,
2012 and 2024. A price adjustment that mixes bases is wrong by a large factor. The base year is part
of the fact, never an assumption.

---

## 5. Non-deduction of the below-BOQ tender percentage — expressible, and cheap

**Source.** CAG Report No. 23 of 2021, Indo-Nepal Border Road, Chapter 4, page 10, Table 9 item 3.

**Rule invoked.** The agreement itself: the agency contracted to execute the work at **9.65% below
BOQ**, so every payment was to be made after reducing the gross bill value by 9.65%.

**What happened.** The Road Construction Department did not lower the bill value, paying **₹21.19
crore instead of ₹19.14 crore** — an excess of **₹2.05 crore**.

**The arithmetic:** `21.19 × (1 − 0.0965) = 19.145` crore. It reproduces at the report's stated
precision.

**The auditor's closing line is worth quoting** because it is the whole philosophy of this platform
in one sentence: the department replied that the deduction *had* been applied, and audit answered
that the "calculation entered in the measurement book did not support reply". The measurement book
settled it.

**Can Aedifex express this today? NO — but it is the closest of any pattern here.**

| Fact required | Status |
| --- | --- |
| Tender percentage above/below BOQ | **Missing** — a new fact type, stated on the award or agreement. One extractor, no architecture. |
| Gross bill value | **Missing** — needs an RA bill. Aedifex extracts `stated_bill_total` from a BOQ already, so the reader exists in the right shape. |
| Net amount paid | **Missing** — needs an RA bill or payment certificate. |
| The arithmetic | **Present.** One multiplication in `Decimal`. |

This is a **pure arithmetic rule over three facts from two documents**, with no provision, no
applicability and no formula. If a real RA bill and its agreement arrive together, this is the
cheapest new rule available — cheaper than anything left in the existing coverage inventory.

---

## 6. Material supplied below specification, difference not recovered

**Source.** CAG Report No. 23 of 2021, Indo-Nepal Border Road, Chapter 4, page 9, Table 9 item 1.

**Rule invoked.** The agreement of June 2013, which specified **packed** bitumen (VG 30 and CRBM 55).

**What happened.** 2,545.56 MT of **bulk** bitumen was used instead, and the cost difference —
**₹1.18 crore** over December 2014 to January 2018 — was never recovered.

**Can Aedifex express this today? NO, and this one is different in kind.** It requires comparing a
*material specification* in the contract against a *material actually supplied* recorded in a
material register or MB, then pricing the difference. That is a comparison between two things
Aedifex has no fact types for. It is also the pattern where quantity, rate, specification and
recovery all meet, and it is genuinely the hardest in this catalogue.

Recorded, not planned.

---

## 7. Duplicate payment: carriage claimed twice on the same stretch

**Source.** Indo-Nepal Border Road, Chapter 4, page 10, Table 9 item 2, and its resolution on the
following page.

**What happened.** Extra carriage lead was claimed for the same stretch under two claims. The
auditor's judgement: "approval of competent authority cannot justify the inadmissible double payment
of carriage on same stretch."

**Can Aedifex express this today? NO.** Duplicate-payment detection needs two bills for one project
and an item-level identity across them. Aedifex has work-item reconciliation
(`work_item_evidence_unambiguous`, which already returns `REVIEW` when two documents give
irreconcilable readings of the same item) but has never seen two real bills for one project.

**The important negative here is the auditor's principle, not the arithmetic:** an approval does not
make an inadmissible payment admissible. A rule that treated "sanctioned" as "correct" would have
passed this. Worth remembering when the sanction-reference fact type is eventually built.

---

## 8. Sanctioned provision exceeded, and items paid that were never sanctioned

**Source.** Indo-Nepal Border Road, Chapter 4, page 11, Table 9 item 5.

**Rule invoked.** Clause 124 of the MoRTH specifications — the contractor provides a vehicle for the
engineer's inspection work, paid as provided in the BOQ.

**What happened.** Across nine of twelve Detailed Project Reports, ₹3.42 crore was provisioned for
vehicles and sanctioned; ₹5.15 crore was spent — an excess of ₹2.46 crore. In two works the item was
in neither the original nor the revised DPR, yet appeared in the contract BOQ and was paid.

**Can Aedifex express this today? Half of it.**

- *Provision versus expenditure* is arithmetic over two money facts: expressible the moment a DPR and
  a payment record are held for one project. Structurally identical to
  `priced_bill_matches_advertised_estimate`, which is already implemented.
- *"An item exists in the contract BOQ that appears in no sanctioned DPR"* is a **set difference
  between two item lists**, which is a different operation from every rule implemented today. Every
  current rule compares two *values*; this compares two *populations*. Recorded as a genuinely new
  rule shape.

---

## What the catalogue establishes

**Eight patterns. Zero are executable today. Two are cheap, and neither is blocked by architecture.**

| # | Pattern | Blocked by | Cheapest unblocking document |
| --- | --- | --- | --- |
| 5 | Below-BOQ percentage not deducted | Evidence only | One RA bill + its agreement |
| 2 | Mobilisation advance above ceiling | Evidence only | KPWD Code (public) + one payment record |
| 8a | Sanctioned provision exceeded | Evidence only | One DPR + one payment record |
| 1 | Extra item at the wrong rate | Evidence only | MB + RA bill + SOR |
| 7 | Duplicate payment | Evidence only | Two RA bills for one project |
| 3 | Advance recovery schedule | Evidence — needs a **series** | Consecutive IPCs for one contract |
| 4 | Price adjustment from the wrong index | Evidence **and** formula representation | A contract stating a price-adjustment formula |
| 8b | Item paid but never sanctioned | Evidence, plus a new rule shape (set difference) | DPR + contract BOQ |
| 6 | Material below specification | Evidence, plus two new fact types | Contract specification + material register |

**The single most important conclusion is the same one the coverage inventory reached in August, now
confirmed against real completed audits: the constraint is the corpus, not the design.** Six of the
nine entries above are blocked by nothing but a missing document, and five of those six would be
unblocked by *the same two documents* — one running account bill and the agreement it was paid
against.

**One genuinely new architectural requirement appeared**, and only one: pattern 4 needs a formula
over named indices, which the Reference Provision model cannot represent. It should stay unbuilt
until a real contract in the corpus states such a formula. Pattern 8b's set-difference rule shape and
pattern 3's document-series requirement are also new, and are likewise recorded rather than built.

**And one thing this exercise proved about the arithmetic that already exists:** the Karnataka excess
payment reproduces to the rupee in exact `Decimal`, from three quantities and two rates, against a
figure computed independently by a state Accountant General. That is the deterministic core doing
exactly what it is for.
