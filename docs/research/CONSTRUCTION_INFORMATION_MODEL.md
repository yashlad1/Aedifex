# Construction Information Model

Date: 2026-08-20

Companion to [CORPUS_ROADMAP.md](CORPUS_ROADMAP.md), which surveys *where* construction evidence
exists. This document is about *what the information is* — how it flows, what can be checked
deterministically, where a model may and may not help, and what the minimum evidence is for each kind
of verification.

No code, no schema. Where it disagrees with the SRS, §7 says so explicitly rather than quietly.

---

## 1. Three chains, not one pipeline

The SRS draws the relationship graph as a single chain (§11). Working through the lifecycle document
by document, it is really **three chains that start apart and are compared against each other at
every stage.** This is the central idea of this document, because *a verification is almost always a
comparison of two adjacent links in one chain, or of two chains at the same stage.*

```text
                PRE-AWARD          AWARD              POST-AWARD              FINAL / AUDIT

QUANTITY     estimated qty  →  contracted qty  →  measured qty  →  certified qty  →  final qty
   chain      (DPR, BOQ)        (contract BOQ)      (MB)             (IPC)            (final bill)
                                     ↑                                 ↑
                              variation order ─────────────────────────┘

RATE         sanctioned rate →  quoted rate  →  contract rate  →  applied rate  →  adjusted rate
   chain      (SoR)             (priced BOQ)     (agreement)        (IPC)          (+ escalation)
                                     ↑                                                  ↑
                              new-item rate                                       price indices
                              (variation)

MONEY        estimated cost  →  bid amount  →  contract value  →  gross claim  →  net certified
   chain      (NIT)             (bid, tabs)     (LoA, agreement)   (IPC)          (IPC, after
                                                                                   deductions)
                                                                        ↑
                                                    retention · advance recovery · LD ·
                                                    price adjustment · tax  (contract + circulars)

TIME         completion period → appointed date → progress → EoT-adjusted date → actual completion
   chain      (NIT, RFP)         (work order/NTP)  (MPR)       (EoT approval)     (completion cert)

QUALITY      specification    →  approval to proceed  →  test result  →  acceptance / NCR
   chain      (MoRTH, IS)        (WIR/MIR)               (MTC, lab)      (engineer)
```

Four chains once time and quality are included. Two properties matter:

**Each chain begins in reference or pre-award data and ends in audit.** A chain whose early links are
missing cannot be verified at its later links — which is exactly the corpus's present condition for
money and time.

**Adjacent links are where the money is.** `measured → certified` is over-certification.
`contracted → measured` without a variation is unauthorised work. `contract rate → applied rate` is a
rate substitution. `gross → net` is a deduction error. Every one of those is subtraction, and none of
them needs a model.

---

## 2. Document catalogue: verification and interpretation

The producer/consumer/contents columns are in [CORPUS_ROADMAP.md](CORPUS_ROADMAP.md) §1 and are not
repeated. What follows is the part that governs engineering: for each document, what a **deterministic
rule** could check, and what an **LLM** may legitimately contribute.

The split follows SRS §15 without exception. AI may locate, classify, map language to language, and
explain. **Every number comparison is deterministic.** A useful test when the boundary looks unclear:
*would the answer change if the model were replaced with a different model?* If yes, it may not
decide anything.

### Pre-award

| Document | Facts extractable | Derived facts | Deterministic verification | AI may |
| --- | --- | --- | --- | --- |
| NIT / tender notice | NIT number, estimated cost, EMD, completion period, dates | bid security share | EMD vs prescribed share; dates ordered; corrigendum supersedes | Classify the document; locate the header table |
| RFP / ITB | prescribed rates, eligibility thresholds, evaluation method, measurement standard | — | The threshold is *evidence*: cite the clause, then compare | Find the clause that states a threshold, for a human to confirm |
| Unpriced BOQ | item id, description, unit, quantity | total quantity by category | Item numbering continuity; unit vocabulary | Map a description to a standard item |
| Priced BOQ | + rate, amount, stated total | line total, bill total | **qty × rate = amount** per row; **Σ rows = stated total** | Nothing arithmetic. Locate the table across pages |
| Bid opening minutes / bid tabulation | each bidder's amount, per-item rates | rate dispersion, deviation from estimate | Arithmetic consistency of each bid; outlier detection against dispersion | Explain *why* a rate is an outlier |
| Corrigendum | changed values, effective date | — | Supersession chain has one head | Suggest which document it amends — a human confirms |
| Drawings | — | — | — | Not a text problem. Out of scope |

### Award

| Document | Facts extractable | Derived facts | Deterministic verification | AI may |
| --- | --- | --- | --- | --- |
| **Contract agreement** | retention %, retention cap, mobilisation advance % and recovery schedule, LD rate and cap, price-adjustment formula and base indices, defect liability period, permissible variation limit, measurement standard, agreed BOQ | — (these are rule *inputs*) | Every post-award deduction and time rule becomes possible; none is possible without it | Locate each clause and quote it. **Never interpret a clause into a number** |
| Letter of Acceptance | accepted amount, conditions precedent | LoA vs bid amount | Accepted = quoted, or the difference is explained | Link LoA to its tender |
| Work order / NTP | appointed date, completion date | contract duration | Duration = completion − appointed; matches NIT period | — |
| Performance guarantee | amount, validity | PBG share of contract value | Share vs contract requirement; **validity ≥ contract period** | Read the bank's non-standard wording |
| Insurance | cover, period, insured sum | — | Cover ≥ required; period spans works | Same |

### Post-award

| Document | Facts extractable | Derived facts | Deterministic verification | AI may |
| --- | --- | --- | --- | --- |
| **Measurement Book** | item id, measured quantity, location/chainage, dimensions, date, measurer | measured total per item; measurement interval | Dimensions reproduce the quantity; interval within limits (a real CAG finding); measured ≤ contracted + variation | Read handwriting/scan; map a site description to an item |
| **IPC / RA Bill** | item id, quantity this bill and to date, rate, gross, each deduction, net | quantity variance, rate variance, unsupported amount, cumulative continuity | **gross = Σ(qty × rate)**; **net = gross − Σ deductions**; certified ≤ measured; cumulative non-decreasing; retention ≤ cap; advance recovery follows schedule | Locate the deduction block; name a non-standard deduction |
| Variation order | new/extra items, excess quantities, new rate and its derivation, sanction reference | variation as % of contract value | Variation within permitted limit; **sanction reference present** (a real CAG finding); new rate derived from SoR or contract rate | Summarise the stated justification. **Never judge whether it is adequate** |
| EoT application / approval | delay events, days claimed, days granted | revised completion date, LD exposure | LD = f(delay beyond revised date, rate, cap); revised date arithmetic | Classify a delay event's stated cause |
| Site instruction | instructed change, date | — | Every variation traces to an instruction | Link instruction to variation |
| WIR / MIR | item, location, offered date, approval, approver | approval-before-payment lag | **Was the item approved before it was certified?** | — |
| Material / mill test certificate | grade, batch, measured values | pass margin against specification | Measured value vs specification threshold; batch traceable to a delivery | Read varied lab layouts |
| Test reports | sample id, values, frequency | test frequency vs required | Value vs threshold; **frequency vs required frequency** | Same |
| GRN / delivery challan | material, quantity received, date | received vs consumed vs paid | Paid quantity ≤ received quantity | Match a vendor's item naming |
| Monthly progress report | physical %, financial % | progress-to-payment ratio | Financial progress ahead of physical progress by more than tolerance | Summarise stated reasons for slippage |
| Completion certificate | completion date, exclusions | delay against revised date | Closes the time chain; triggers DLP and retention release | Extract the snag list |
| Final bill | final quantities, total paid | total paid vs contract value + variations | **Σ all IPCs = final bill**; final ≤ contract + approved variations | — |

### Audit

| Document | Facts extractable | Deterministic verification | AI may |
| --- | --- | --- | --- |
| CAG / AG audit report | contracted, measured, paid figures; the rule applied; the money at stake | Reproduce the auditor's arithmetic from *our own* evidence, where we hold it | **Highest-value use anywhere**: read a finding's narrative and propose the deterministic rule behind it, for a human to accept |
| Independent Engineer report | certified progress, quality observations | IE certification vs contractor claim | Summarise observations |
| Arbitration award / judgment | claimed vs certified vs awarded | The three values are distinct facts, never merged | Extract which party asserted which figure |
| Third-party technical audit | re-measured quantities, rate objections | Re-measurement vs MB | — |

### Reference

| Document | Facts extractable | Serves as | AI may |
| --- | --- | --- | --- |
| Schedule of Rates | sanctioned rate per standard item, basis, effective date | Baseline for quoted and variation rates | **Map a bespoke item description to a standard SoR item.** The single most valuable AI task in the system — and its output is a *suggested relationship*, confirmed by a human, never a silent equivalence |
| Specifications (MoRTH, IS, IRC) | material grades, tolerances, acceptance criteria, test frequency | Threshold half of every quality rule | Locate the clause governing an item |
| Method of measurement (IS 1200) | how a quantity is legitimately computed | Validity of a measurement | Explain a measurement convention |
| Price indices (WPI, CPI) | index value by month and commodity | Input to the escalation formula | Nothing. Pure arithmetic |
| Standard bidding documents | default clause text and thresholds | What a contract probably says where it is silent | Diff a contract against the standard form and show what changed |
| Circulars / notifications | changed rate or rule, effective date, applicability | Amends reference data mid-contract | Propose applicability; **never decide it** — SRS §15 puts compliance decisions outside AI |

---

## 3. Reference data, project data, audit evidence

Item (4) of the milestone. The classification is mostly clean, and the exceptions are the interesting
part.

| Class | Documents | Scope |
| --- | --- | --- |
| **Reference** | SoR, specifications, method of measurement, price indices, standard bidding documents, circulars, tax and wage notifications, codes | Shared across many projects; governed by effective date and jurisdiction |
| **Project** | Contract, work order, BOQ, MB, IPC, variation, EoT, site instruction, WIR/MIR, test reports, GRN, progress reports, completion certificate, final bill | One project. Isolated by default |
| **Audit** | CAG reports, IE reports, arbitration awards, technical audits, statutory audits | About a project, produced outside it; **always secondary** |

**Three documents are dual-class, and each is a trap.**

**A priced BOQ is project data for its own contract and reference data for every other.** Used as a
rate benchmark across contracts it becomes exactly the cross-project access ADR 0014 governs — and it
must be, because "the market rate for this item" is an inference from other projects' data and needs
explicit, provenanced applicability. Left ungoverned it would be the isolation invariant leaking in
through the side door.

**A tender notice is project data that behaves like reference data over time.** Aggregated, notices
are the basis of "which contractors repeatedly exceed estimated quantities?" — an SRS §16 question
that is inherently cross-project.

**An audit report is secondary about a project and reference-like about a rule.** Its figures may
never be cited as measurements. Its *rules* are the most valuable reference data available, and they
are extracted by a human reading it, not by the pipeline.

---

## 4. Minimum document set per verification domain

The core deliverable, and the thing that makes the acquisition order rigorous rather than intuitive.
**Held** counts only real documents.

### Quantity — "was this quantity actually executed?"

| Need | Document | Held |
| --- | --- | --- |
| Contracted quantity | Priced BOQ or contract BOQ | ✅ real (37 items) |
| Measured quantity | **Measurement Book** | ❌ synthetic only |
| Certified quantity | **IPC / RA Bill** | ❌ synthetic only |
| Authorisation above contract | **Variation order** | ❌ |
| Validity of the measurement | Method of measurement | ❌ |

**2 of 5, one of them real.** Rules already written: 3. Verifiable today: none, on real evidence.

### Rate — "is this the right rate, and may it be applied?"

| Need | Document | Held |
| --- | --- | --- |
| Agreed rate | Priced BOQ / contract | ✅ real (BOQ only, not contract) |
| Applied rate | IPC | ❌ synthetic only |
| New-item rate and its derivation | Variation order | ❌ |
| Sanctioned baseline | Schedule of Rates | ❌ |
| Escalation | Price indices + contract formula | ❌ |

**1 of 5.**

### Payment — "is the money right?"

| Need | Document | Held |
| --- | --- | --- |
| Gross claim and deductions | IPC | ❌ synthetic only |
| Retention %, cap; advance % and recovery schedule; LD rate and cap; escalation formula | **Contract agreement** | ❌ |
| Cumulative continuity | Prior IPCs | ❌ |
| Advance actually paid | Advance payment record | ❌ |
| Tax rates | Tax notifications | ❌ |

**0 of 5. The emptiest domain, and the one every existing rule was written for.**

### Time — "is the delay and its consequence correct?"

| Need | Document | Held |
| --- | --- | --- |
| Appointed date | Work order / NTP | ❌ |
| Completion period, LD rate and cap | Contract (NIT gives the period only) | ⚠️ period only |
| Days granted | EoT approvals | ❌ |
| Actual completion | Completion certificate | ❌ |
| Responsibility for delay | Hindrance register, progress reports | ❌ |

**0 of 5 usable.** No time rule exists yet, correctly — there is nothing to write one against.

### Quality — "does it meet specification?"

| Need | Document | Held |
| --- | --- | --- |
| The threshold | Specification (MoRTH, IS) | ❌ |
| The measured value | MTC, test reports | ❌ |
| Approval before covering up | WIR / MIR | ❌ |
| Defect closure | NCR | ❌ |

**0 of 4.** Also the domain where the threshold is *reference* data, so it is the first real test of
ADR 0014.

### Contract compliance — "was the process followed?"

| Need | Document | Held |
| --- | --- | --- |
| Bid security rate | ITB | ✅ real (clause 13.2) |
| Guarantee and insurance validity | PBG, policies | ❌ |
| Sanction for extra items | Variation + sanction record | ❌ |
| Variation within limit | Contract | ❌ |
| Statutory compliance | Labour and tax records | ❌ |

**1 of 5**, and it is the only domain with a working real-evidence rule today.

### What the table says

| Domain | Documents needed | Real documents held | Rules written | Rules validated on real evidence |
| --- | --- | --- | --- | --- |
| Quantity | 5 | 1 | 3 | **0** |
| Rate | 5 | 1 | 1 | **0** |
| Payment | 5 | **0** | 3 | **0** |
| Time | 5 | 0 (partial) | 0 | — |
| Quality | 4 | **0** | 0 | — |
| Contract compliance | 5 | 1 | 1 | **1** |

**Eight rules exist. One has ever been validated against real evidence on both sides.** That is not a
criticism of the rules — it is a precise statement of what the corpus permits, and it is the honest
version of "the pipeline works end to end".

---

## 5. Acquisition roadmap, derived rather than guessed

Counting how many of the six domains each document unblocks turns the ordering into arithmetic.

| Rank | Document | Domains it serves | Why it wins |
| --- | --- | --- | --- |
| **1** | **Contract agreement** | Payment, Time, Rate, Contract compliance, Quantity (variation limit) — **5 of 6** | Every post-award threshold is in it, and *none may be configured*. The bid-security precedent settled that: two real tenders said 1% and 2%, and hardcoding either would have failed a legitimate one |
| **2** | **IPC / RA Bill** | Payment, Quantity, Rate — **3 of 6** | The document all three payment rules were written for and none has ever seen |
| **3** | **Measurement Book** | Quantity, Rate — **2 of 6** | The only primary record of what was built. Pairs with 2; alone it proves less |
| **4** | **Variation order** | Quantity, Rate, Contract compliance — **3 of 6** | Without it, a quantity above contract has *no lawful explanation available to a rule*, so the honest verdict is permanently REVIEW |
| **5** | Bid tabulations (US DOT) | Rate — 1 of 6, at scale | The only item on this list that needs nothing from anyone, and it converts rate benchmarking from configuration into evidence |
| **6** | Schedule of Rates | Rate, Quality-adjacent | First real test of ADR 0014's applicability model |
| **7** | Specification + test certificate pair | Quality — a whole empty domain | Opens the only domain with zero coverage |
| **8** | Price indices + contract formula | Payment | Pure arithmetic on a public monthly series; depends on 1 |
| **9** | Work order / NTP + completion certificate | Time | Cheap, and opens the second empty domain |

**Documents 1 and 2 together move four of six domains from unverifiable to verifiable.** Nothing else
in the lifecycle comes close, and that is the whole answer to "what next".

The efficient acquisition is therefore not a document but a **project bundle**: contract agreement,
one MB, the corresponding IPC, and any variation, for a single contract whose BOQ is already held.
Four documents, four domains, one provenance chain, and every existing rule exercised end to end for
the first time.

---

## 6. Where AI belongs, concretely

SRS §15 draws the line. Applying it document by document produced four tasks that are genuinely
valuable and genuinely safe, and they share a shape: **each proposes something for a human or a
deterministic check to confirm, and none of them decides.**

1. **Map a bespoke item description to a standard SoR item.** "M-40 PQC, 25mm max aggregate" against
   a rate schedule's phrasing. Language to language, which is what models are for. Output is a
   *suggested relationship* with a confidence, confirmed before any rate comparison relies on it.
2. **Read an audit finding and propose the deterministic rule inside it.** The CAG paragraph about
   extra items already priced into finished-item rates *is* a rule statement in prose. A human accepts
   or rejects; the rule that ships is deterministic.
3. **Locate a table, a clause or a deduction block in a long document.** Already the weakest part of
   the pipeline: three of four real-data defects were the reader anchoring in the wrong place.
4. **Explain a finding in the reader's language.** The arithmetic is done and cited; the model
   narrates it and may not alter a number.

And the three that look attractive and are forbidden:

- **Deciding whether a variation's justification is adequate.** A compliance decision (SRS §15).
- **Deciding that `Cum` and `m3` are the same unit.** A model would say yes, confidently, and it would
  be inferring a conversion. Case-folding was permitted because a real document spelled one unit two
  ways on its own pages; equivalence still awaits evidence.
- **Deciding which projects a circular applies to.** Jurisdiction and effective date look like a model
  strength and are a compliance decision — ADR 0014, and the same conclusion already reached for the
  prescribed bid-security rate.

---

## 7. Refinements this analysis makes to the SRS

Recorded here rather than silently, since the SRS wins where a design disagrees with it.

**§11's chain has one link in the wrong order.** It reads
`Tender → Contract → BOQ → Invoice → Measurement Book → Payment`. A measurement **precedes** the bill
it justifies: work is measured, then claimed, then certified. With MB after Invoice, the natural
reading of a quantity variance is inverted, and the rule that matters — *is the claim supported by a
measurement?* — reads backwards. Suggested: `… → BOQ → Measurement Book → IPC/Invoice → Payment → …`.

**One chain should be four.** §11's single line hides that quantity, rate, money and time each have
their own chain and that verification is the comparison of adjacent links. §1 above is the refinement.

**§13's outcome vocabulary lists five values; the implementation has four.** `PASS`, `FAIL`, `REVIEW`,
`INCONCLUSIVE` are implemented and constrained in the database; `WARNING` is not. Recommend dropping
it — REVIEW already means "a person must look", and a second severity with no rule behind it invites
inconsistent use.

**§8.3's structured-data list is missing the post-award vocabulary** that this analysis shows the
product actually needs: measured quantity, certified quantity, retention, mobilisation advance,
liquidated damages, price adjustment, variation reference, sanction reference, test value. Worth adding
so the SRS describes the target rather than the first milestone.

**§17's chain omits two links the implementation has.** It reads
`Finding → Evidence → Fact → Document → Page → Original Source`. Derived facts and cells exist and are
traversable: `Finding → Evidence → Derived Fact → Fact → Document → Page/Cell → Immutable Raw
Artifact` is what `scripts/audit_traceability.py` actually walks.

**§7 understates acquisition.** "The crawler is NOT the product" is right and now too narrow: portal,
upload, customer export, email, ERP, cloud storage and API all converge into one immutable pipeline,
and after acquisition origin affects provenance and nothing else.

---

## 8. What would falsify this document

**The three-chain model.** If a real IPC turns out not to reference measurements per item — if
certification happens at bill level against a lump-sum or milestone basis — then the
`measured → certified` link does not exist for that contract type and quantity verification means
something different. Milestone-based and EPC lump-sum contracts plausibly work this way, and the
corpus contains only item-rate evidence. **This is the assumption most likely to be wrong.**

**The primacy of the contract agreement.** If real contracts turn out to incorporate their commercial
terms by reference to a standard bidding document rather than stating them, then the standard form is
the document to acquire and the agreement is a thin wrapper. Both are cheap to check on one real
contract.

**The claim that measurement precedes billing.** Where an e-MB system generates the bill directly
from the measurement, they may be one artifact rather than two, which changes the relationship but not
the comparison.
