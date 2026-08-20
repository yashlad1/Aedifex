# Corpus roadmap — the construction document ecosystem

Date: 2026-08-20

## What this is, and what it is not

Companion to [CONSTRUCTION_INFORMATION_MODEL.md](CONSTRUCTION_INFORMATION_MODEL.md), which covers
what the information *is* — the four chains, the deterministic-versus-AI boundary per document, and the
minimum evidence needed for each kind of verification. This document is the survey of where it exists.

A survey of where construction evidence exists, what each document contains, and what Aedifex would
be able to do with it. **No design.** No tables, APIs, relationships or rules are proposed here; the
architecture stays frozen until a real document requires a change.

It is also **not source approval.** Nothing below has had its terms of use read, its `robots.txt`
fetched, or a reviewer recorded, and nothing may be collected until it has —
[DATA_SOURCES.md](../../DATA_SOURCES.md) steps 1–8. This document exists so that the legal judgement
has something concrete to act on, and so that the acquisition effort is spent on the documents that
unlock the most.

Confidence is marked throughout, because the value of a roadmap collapses if a guess reads like a
fact:

- **[V]** verified during this research, with the source linked at the end
- **[K]** established domain knowledge, specifics not re-checked
- **[?]** plausible and unverified — the thing to check before relying on it

## The lifecycle, and where the evidence actually is

Five phases. The asymmetry between them is the single most important fact in this document.

```text
 PRE-AWARD          AWARD            POST-AWARD          AUDIT           REFERENCE
 what is asked   what is agreed    what happened      what was found   what governs
 ───────────     ───────────       ───────────        ───────────      ───────────
 abundant,       partly public     essentially        public, but      public and
 public          (bid tabs [V],    absent from        secondary        durable
                 AoC notices)      public sources
                                   in India [V]
      └──────── Aedifex has these ────────┘         └── has none ──┘
```

**Public procurement transparency stops at award.** Every portal in the world is built to prove that
a contract was let fairly; none is built to prove it was paid correctly. Payment happens between two
parties after the public interest in the transaction has, institutionally, been declared satisfied.
That is why the corpus looks the way it does, and it is not a gap in the crawler.

---

## 1. Document catalogue

Columns: who produces it, who consumes it, what it carries, whether it is **primary** evidence (the
record itself) or **secondary** (a document reporting on records), and what Aedifex would make of it.

Aedifex object shorthand: **A** artifact, **F** fact, **DF** derived fact, **R** relationship,
**RI** rule input (a threshold that must itself be cited evidence, never configuration).

### Pre-award

| Document | Produced by | Consumed by | Carries | Evidence | Aedifex |
| --- | --- | --- | --- | --- | --- |
| Detailed Project Report / feasibility | Design consultant | Authority, lender | Scope, preliminary quantities, cost estimate, alignment | Primary (of the estimate) | A, F — the *original* estimate, for scope-creep comparison |
| Notice Inviting Tender / tender notice | Authority | Bidders | NIT number, estimated cost, EMD, dates, completion period | Primary | **A, F, R** — the project key. Already held |
| Request for Proposal / bid document | Authority | Bidders | ITB, conditions of contract, specifications, unpriced BOQ | Primary | **A, F, RI** — ITB clauses are rule inputs. Already held |
| Instructions to Bidders | Authority (inside RFP) | Bidders | Eligibility, bid security rate, evaluation method | Primary | **RI** — the precedent already set: bid-security rate cited from clause 13.2 |
| Unpriced BOQ / schedule of items | Authority | Bidders | Item numbers, descriptions, units, quantities | Primary | **A, F** — contracted quantity baseline |
| Priced BOQ | Bidder | Authority | The above plus unit rates and amounts | Primary | **A, F, DF** — already held: 37 rows, sums to its own stated total |
| Corrigendum / addendum | Authority | Bidders | Changes to any of the above | Primary | **A, R** — supersession. Already held; relationship type exists |
| Pre-bid meeting minutes / clarifications | Authority | Bidders | Interpretations that bind the contract | Primary | A, F — an interpretation is a rule input in disguise |
| Drawings (GA, structural, GFC) | Consultant | Contractor, engineer | Geometry from which quantities derive | Primary | A only, realistically. Quantity take-off from drawings is not a text problem |
| Technical bid / qualification submission | Bidder | Authority | Turnover, experience, plant, key personnel | Primary | A, F — heavy personal data; screen before storing |
| Bid opening minutes / comparative statement | Authority | Bidders, public | All bidders' quoted amounts, ranking | Primary | **A, F, R** — cross-bidder rate benchmarking |
| Technical evaluation report | Evaluation committee | Authority | Responsiveness findings, disqualifications | Secondary | A, F |

### Award

| Document | Produced by | Consumed by | Carries | Evidence | Aedifex |
| --- | --- | --- | --- | --- | --- |
| **Contract agreement** | Both parties | Everyone downstream | Agreed BOQ, retention %, mobilisation advance %, LD rate and cap, price-adjustment formula and base indices, defect liability period, measurement standard, variation limits | **Primary** | **A, F, RI — the single highest-value document in the lifecycle.** Nearly every post-award rule needs a threshold that only this document states |
| Letter of Acceptance / Letter of Intent | Authority | Contractor | Accepted amount, conditions precedent | Primary | A, F, R — links tender to contract |
| Work order | Authority | Contractor | Scope, start date, completion date | Primary | **A, F** — the appointed date, from which every time-based rule counts |
| Award of Contract notice | Authority | Public | Awardee, contract value, date | Primary | **A, F** — publicly available [K]; ties a public tender to a private contract |
| **Bid tabulation** (US state DOTs) | Authority | Public | Every bidder's price *per pay item*, with quantities, plus the engineer's estimate | **Primary** | **A, F, DF** — a priced BOQ per contract, publicly downloadable [V] |
| Performance bank guarantee | Bank | Authority | Amount, validity, conditions | Primary | A, F, RI — validity vs contract period is a checkable rule |
| Insurance policies | Insurer | Authority | Cover, period, insured amount | Primary | A, F, RI — same shape |
| Notice to Proceed / appointed-date certificate | Authority | Contractor | The date the clock starts | Primary | **A, F** — anchors EoT and LD arithmetic |

### Post-award — the operational record

| Document | Produced by | Consumed by | Carries | Evidence | Aedifex |
| --- | --- | --- | --- | --- | --- |
| **Measurement Book** (CPWD Form 23 [V]) | Site engineer, jointly signed | Billing engineer, QS, auditor | Measured quantity per item, location/chainage, dimensions, date, measurer identity | **Primary — the authoritative record of what was built** | **A, F** — `measured_quantity`. Nothing substitutes for it |
| **IPC / RA Bill** (CPWD Form 47 / PW 410 [V]) | Contractor claims, engineer certifies | Accounts, authority, lender | Quantity this bill and to date, rate, gross amount, deductions (retention, advance recovery, price adjustment, LD, taxes), net payable | **Primary** | **A, F, DF, R** — the document the payment rules were written for |
| Final bill | Contractor, engineer | Authority | Final quantities, total paid, closing adjustments | Primary | A, F, DF |
| **Variation / change / deviation order** | Engineer, sanctioned by authority | Contractor, accounts | Extra items, excess quantities, new rates and their derivation, sanction reference | **Primary** | **A, F, R, RI** — the missing piece: today a quantity above contract has no lawful explanation available to a rule |
| Extension of Time application and approval | Contractor / authority | Both | Delay events, days claimed, days granted, LD consequence | Primary | A, F, RI |
| Site / engineer's instruction | Engineer | Contractor | Instructed change, date | Primary | A, F, R — the origin of a variation |
| Hindrance register | Both | Both, arbitrator | Obstruction periods and responsibility | Primary | A, F — heavily disputed in practice |
| Daily progress / labour & plant report | Contractor site staff | Engineer | Manpower, plant, work done, weather | Primary | A, F — high volume, low value per document |
| Monthly progress report | Contractor | Authority, lender | Physical and financial progress, S-curve, issues | Secondary | A, F, DF — good for progress-vs-payment rules |
| Work Inspection Request / RFI | Contractor | Engineer | Item, location, offered date, approval | Primary | **A, F, R** — the check that a paid item was actually approved |
| Material Inspection Request / material-at-site | Contractor | Engineer | Material, quantity, source, approval | Primary | A, F, R |
| **Material / mill test certificate** | Supplier, lab | Engineer | Grade, batch, test values against specification | **Primary** | **A, F, RI** — specification compliance, where the threshold is in a reference standard |
| Test reports (cube, FDD, bitumen extraction) | Site or third-party lab | Engineer | Sample identity, measured values, pass/fail | Primary | A, F, RI |
| Non-conformance report | Engineer, QA | Contractor | Defect, item, disposition | Primary | A, F, R |
| Delivery challan / goods receipt note | Supplier / store | Contractor, engineer | Material, quantity received, date | Primary | **A, F** — the GRN half of the original product thesis |
| Purchase order to vendor | Contractor | Supplier | Item, quantity, rate | Primary | A, F, R |
| Subcontractor / supplier invoice | Vendor | Contractor | Amount claimed, tax | Primary | A, F |
| Labour and statutory records | Contractor | Authority, regulator | Muster roll, EPF/ESI remittance, minimum-wage compliance | Primary | A, F, RI — personal data throughout |
| Completion / taking-over certificate | Engineer, authority | Both | Completion date, exclusions, snag list | Primary | **A, F** — closes the time-based rules |
| Defect liability records | Both | Both | Defects, rectification, retention release | Primary | A, F, R |
| Utilisation certificate | Authority | Funder | Grant spent against sanction | Secondary | A, F, DF |

### Audit — documents *about* records

Every row here is **secondary**. That is not a defect: a secondary document is real evidence of what
an auditor found. It must never be stored in a way that lets a finding claim primary measurement
authority for a figure quoted inside a narrative — this is why
[ADR 0014](../adr/0014-reference-data-by-explicit-applicability.md) exists in spirit and why the
distinction is recorded in [ARCHITECTURE.md](../../ARCHITECTURE.md).

| Document | Produced by | Consumed by | Carries | Aedifex |
| --- | --- | --- | --- | --- |
| **CAG audit reports** [V] | Comptroller and Auditor General | Legislature, public | Real contracted/measured/paid figures, the discrepancy, **and the rule the auditor applied** | **A, F, RI** — the only public source of *real audit rules*. See §3 |
| Lender's Independent Engineer report | IE appointed under concession | Lender, authority, concessionaire | Monthly certification of progress and quality, payment recommendation | A, F — closest thing to primary among the audit class [?] |
| Statutory / project financial statements | Auditor | Funder | Expenditure against budget, qualifications | A, F, DF |
| Third-party technical audit | State technical examiner, TPQA | Authority | Re-measurement findings, rate objections | A, F, RI |
| Arbitration award / court judgment | Tribunal, court | Parties, public | Claimed vs certified vs awarded amounts, with reasoning | A, F — figures are *contested claims*, often three values for one quantity |
| Vigilance / CVC report | Vigilance authority | Authority | Irregularity findings | A, F |

### Reference — what governs

| Document | Produced by | Carries | Aedifex |
| --- | --- | --- | --- |
| **Schedule of Rates** (DSR, state SoR, MoRTH SoR) | Rate-fixing authority | Sanctioned rate per standard item, with basis | **A, F, RI** — the baseline a quoted or variation rate is judged against |
| **Standard specifications** (MoRTH Specs, IRC, IS codes, CPWD) | Standards body | Material grades, tolerances, methods, acceptance criteria | **A, F, RI** — the threshold half of every material rule |
| **Method of measurement** (IS 1200 [V], contract-specified) | Standards body | How a quantity is legitimately computed | **RI** — decides whether a measurement is even valid |
| **Price indices** (WPI, CPI, published monthly) | Office of Economic Adviser, MoSPI | The index series the price-adjustment formula consumes | **A, F, RI, DF** — see §4 |
| Standard bidding documents (NHAI SBD, World Bank SBD, FIDIC, NEC) | Authority, FIDIC, ICE | Standard clause text, including default thresholds | **A, F, RI** — a contract's clauses are often verbatim from these |
| Government circulars / office memoranda | Ministry, department | Rate revisions, policy changes, with effective dates | **A, F, RI** — the archetypal applicability problem: which projects does this circular govern? |
| Tax notifications (GST rates, TDS) | Tax authority | Rates and effective dates | A, F, RI |
| Minimum wage notifications | Labour department | Rates by category and region | A, F, RI |
| CPWD Works Manual [V] | CPWD | The authoritative structure of MB and RA Bill forms | **A, RI** — lets Aedifex know an RA bill's shape before seeing a filled one |

---

## 2. Source ecosystem

Organised by **channel**, not geography, because acquisition paths converge and only provenance
differs. Reference-vs-project is noted, since that is the axis that matters.

### A. Public procurement portals — pre-award and award

| Source | Reach | Yields | Note |
| --- | --- | --- | --- |
| CPPP / eprocure.gov.in | India, central + many states | Tenders, bid documents, BOQs, AoC notices | Broadest Indian coverage [K] |
| NHAI | India, highways | Tender and bid documents, priced BOQs | **Already in the corpus.** CAPTCHA-gated search, POST-only API |
| GeM | India, goods and services | POs, contracts | Mostly behind registration [K] |
| State PWD / irrigation / municipal portals | India, per state | Tenders, SoRs, occasionally work orders | Highly variable [K] |
| **US state DOTs** (TxDOT, WSDOT, ODOT, AZDOT, VDOT, NCDOT, Iowa DOT, FHWA) | United States | **Bid tabulations with per-pay-item quantities and unit prices** [V] | The best public line-item priced data found anywhere. See §3 |
| SAM.gov / USAspending | US federal | Solicitations, awards, obligations | Award-level, not item-level [K] |
| TED / EU Tenders Electronic Daily | European Union | Notices, awards | Highly structured, low document depth [K] |
| Contracts Finder, Find a Tender | United Kingdom | Notices, awards, some contracts | Contract text sometimes published [K] |
| AusTender, Canadian Buy and Sell | AU, CA | Notices, awards | [K] |
| Open Contracting / OCDS publishers | ~40 jurisdictions | Structured buyer/tender/award/contract relationships | Ground truth for entity matching, not documents |

**Indian post-award sources are catalogued separately and exhaustively** in
[INDIAN_POSTAWARD_SOURCES.md](INDIAN_POSTAWARD_SOURCES.md) — all eight categories of public authority,
with the public/login/licence/robots determination for each, and why almost none is usable.

### B. Public oversight and audit bodies — audit phase

| Source | Yields | Note |
| --- | --- | --- |
| **CAG of India** (cag.gov.in) | Performance and compliance audit reports on highways, PWD, irrigation | **Real figures and real audit rules** [V] |
| State Accountant General offices | The same, per state | [V] |
| US GAO, state auditors | Federal and state programme audits | [K] |
| UK NAO | Value-for-money reports | [K] |
| World Bank IEG, ADB IED | Project completion and evaluation | [K] |
| Multilateral integrity/sanctions reports | Fraud and collusion findings | [K] |

### C. Judicial and arbitral

Indian judgments via official court portals and aggregators; international arbitral awards where
published. Rich in post-award figures and structurally hazardous: a quantity may appear as claimed,
as certified, and as awarded, and a reader who takes the first has taken the contractor's case as
fact. Heavy personal data. [K]

### D. Standards and rate-fixing bodies — reference

MoRTH, IRC, BIS (IS codes), CPWD (DSR, Works Manual), state SoR publications, Office of the Economic
Adviser (WPI), MoSPI (CPI), FIDIC, ICE (NEC), AIA. Mostly public; some standards are sold rather than
given, which is a licence question, not a technical one. [K] except CPWD Works Manual and IS 1200
[V].

### E. Customer-held systems — where project data actually lives

Not crawlable at all. Every one of these is an *acquisition interface* question, which is why
strengthening those interfaces beats adding crawlers.

| System class | Examples | Holds |
| --- | --- | --- |
| Construction ERP | SAP, Oracle, Highrise, In4Velocity, Tally-adjacent | Contracts, POs, GRNs, invoices, payments |
| Project management / PMIS | Primavera, MS Project, Procore, Autodesk Construction Cloud, Asite, Aconex | Progress, RFIs, submittals, correspondence |
| Billing and QS tools | CANDY, Bluebeam, in-house Excel | BOQ, MB, RA bill workings |
| Document management | SharePoint, Google Drive, Dropbox, Egnyte | Everything, unstructured |
| Government workflow | e-MB systems now live in several state PWDs [V] | MB and bills, digitally, per department |
| Email | — | Instructions, approvals, disputes. The real system of record for decisions |

The **e-MB** finding matters: several Indian state PWDs have moved measurement books onto electronic
systems [V]. Those systems hold exactly the missing evidence, in structured form, under a public
authority. Whether any of them exposes it — to the contractor whose work it records, to an auditor,
or through an API — is the single most valuable open question in this document. [?]

### F. Direct human channels

Sanitised industry samples from a contractor, consultant, client or arbitrator; RTI requests; and
**US-style public records requests**, which are a legally defined channel with a defined response
obligation rather than a favour. See §3.

---

## 3. Gap analysis against the current corpus

The corpus, measured rather than remembered:

| | Count |
| --- | --- |
| Documents | 9 (4 retrieved from NHAI, 5 uploaded synthetic) |
| Extracted facts | 256 |
| Distinct fact types | 16 |
| Derived fact types | 2 document-scoped, 4 work-item-scoped |
| Rules | 8 |
| Findings | 172 |
| Projects | 2 (1 real, 1 synthetic) |
| Work items | 40 (37 real, 3 synthetic) |

Against the lifecycle:

| Phase | Documents in catalogue | Real documents held | Coverage |
| --- | --- | --- | --- |
| Pre-award | 12 | 4 (NIT, RFP with ITB and priced BOQ, 2 corrigenda) | **Adequate for the rules that exist** |
| Award | 8 | **0** | **None** |
| Post-award | 21 | **0 real** (3 synthetic: BOQ, measurement, RA bill) | **None** |
| Audit | 6 | **0** | **None** |
| Reference | 9 | **0** | **None** |

Three findings follow, and the third is the uncomfortable one.

**The rules that exist are the rules the corpus permitted.** Eight rules, and five of the eight
(`claim_within_measured_quantity`, `claimed_rate_matches_contract_rate`,
`cumulative_claim_not_below_previous_certified`, and the derived variance and exposure calculations)
have never once run against real evidence on both sides. They return INCONCLUSIVE 37 times on the
real project and PASS or REVIEW only on synthetic data. **The payment engine is unvalidated, and its
unvalidation is currently invisible** because INCONCLUSIVE looks like normal operation.

**Every threshold a serious rule needs lives in a document class we hold none of.** Retention
percentage, mobilisation advance and its recovery schedule, liquidated damages rate and cap, price
adjustment formula and base indices, defect liability period, permissible variation limit, the
measurement standard — all of them are in the **contract agreement**, and none of them may be
configured, by the project's own rule that a threshold is evidence. The bid-security precedent
already proved the cost of guessing: two real tenders, 1% and 2%, and hardcoding either would have
failed a legitimate one.

**The synthetic set is shaped like the answer we expected.** It has clean `m3` and `MT` units, three
tidy items, no sub-items, no credit rows, no deductions, and one deliberate discrepancy. The one real
BOQ read this month had 35 items, two spelled units for one dimension, sub-items priced under
headings, a negative recovery row, and a total that did not appear to add up until three defects in
the reader were fixed. Every one of those defects was invisible to the synthetic set. **Confidence
from synthetic data is not evidence of anything except internal consistency.**

---

## 4. Recommendations, in order

Ranked by rules unlocked per unit of acquisition difficulty. Each names the construction decision it
serves, per the standing test.

### 1. Contract agreement for a project whose BOQ we already hold

**Unlocks the most, by a wide margin.** It is the only document that states retention, advance
recovery, LD, price adjustment, defect liability and variation limits, and each of those is a rule
that currently cannot be written at all — not "written and inconclusive", but not writable, because
its threshold would have to be invented.

*Decision served:* "Is this deduction correct?" — asked on every certified bill by both the billing
engineer and the auditor.

*Route:* Award-phase documents are published as AoC notices, and full contract agreements are
sometimes attached [K]. Otherwise a customer, or a public records request in a US state.

### 2. Measurement Book + IPC pair for one contract

Together they populate `measured_quantity` and the claim side, which is the pair the existing rules
were written for and have never seen real. **One real pair converts five rules from unvalidated to
validated or refuted** — and refutation would be the more valuable outcome.

*Decision served:* "Should I certify this bill?"

*Route:* Not from Indian public portals [V]. Three candidates, in order of realism: a US state DOT
**as-built item record plus final estimate**, which exists precisely so the final pay quantity "can
be easily audited" [V] and is obtainable by public records request; an Indian **e-MB** system [V, but
access unverified]; a sanitised customer sample.

### 3. US state DOT bid tabulations — the immediate, unblocked win

**The best public line-item construction data found anywhere**, and the only recommendation here that
needs nothing from anyone. Bid tabulations publish, per contract, every bidder's unit price against
the authority's quantities — Oregon explicitly publishes item description, quantity and bid price;
Washington publishes by bid item and contractor [V]. Multiple states, downloadable, and already
aggregated commercially, which is evidence that the terms permit analysis [?].

Why it matters beyond volume: it is a **priced BOQ per contract, at scale**, which gives the
contracted-quantity and contracted-rate side of every reconciliation, plus cross-bidder rate
dispersion — a rate benchmark that is evidence rather than a configured expectation. It also tests
the pipeline's genericity honestly: imperial units, different item numbering, no Indian numerals.
Principle 10 says build for the pipeline, not for NHAI; this is the cheapest available test of
whether that is true.

*Decision served:* "Is this quoted rate reasonable?" — the rate-benchmarking question, answerable
from public data alone.

### 4. Price index series, and the price-adjustment rule

Price adjustment is **deterministic arithmetic on a published index**, which makes it the ideal
Aedifex rule: no judgement, high value, and the reference data is public, monthly, and machine
readable. The MoRTH mechanism applies only to contracts longer than 12 months, and the formula is a
weighted index multiple of the form `(0.70·WPI + 0.30·CPI) / (0.70·WPI₀ + 0.30·CPI₀)` [V]. The lag
between index publication and application was reduced from three months to one with effect from 2026
[V] — which is itself a circular with an effective date, i.e. the applicability problem in its most
concrete form.

*Decision served:* "Is the escalation claimed on this bill correct?" — a recurring, material, and
entirely mechanical dispute.

*Caveat:* it needs the contract's base indices and weightings, so it depends on recommendation 1.

### 5. CAG audit reports — for the rules, not the figures

The only public source that states **the rule an auditor actually applied**, with a real case
attached. Real examples found: ₹5.81 crore paid for shifting stone ballast where the contract rate
was for finished items and therefore already inclusive; extra items ranging from 0.20% to 5,281% of
contract cost paid without the competent authority's sanction attached to the voucher; ₹5.29 crore of
excess payment traced to bills raised at intervals of up to six months so that no monthly value of
work had been recorded [V].

Each of those is a deterministic, checkable rule — *is this extra item already inside the finished-item
rate?*, *does every extra item carry a sanction reference?*, *is the interval between bills within
limits?* — and none of them would have been invented from first principles here.

*Decision served:* "What should I be looking for?" for the internal auditor persona.

*Caveat:* **secondary evidence.** A CAG figure is the auditor's reading of a record we do not hold. It
may seed a rule; it may not be cited as a measurement.

### 6. Reference data: MoRTH specifications, IS 1200, a Schedule of Rates

Needed for the material and rate rules, and each would arrive as the first genuine test of ADR 0014's
applicability model. Deliberately *after* the project data, because a reference document with no
project to govern is a document with no rule to serve.

### Not recommended yet

Drawings — quantity take-off from geometry is not a text-extraction problem. Daily progress reports —
high volume, low value per document. Arbitration awards — three values per quantity and an
adversarial frame; valuable later for dispute analysis, hazardous as an early corpus. GeM and any
registration-gated source — permanently out of scope, not pending.

---

## 5. What I checked, what I got wrong, and what to verify

**Corrected mid-research.** TxDOT's monthly-estimate dashboard looked initially like public
per-pay-item payment data, which would have been the single best find here. It is not confirmed as
such: the page describes contract-level "estimate paid this month" and "total estimate paid to date",
does not indicate per-item detail, offers no export, and states no licence [V]. The line-item claim in
recommendation 3 rests on **bid tabulations**, which are separately and clearly documented — not on
monthly estimates.

**Open questions, highest value first.**

1. Does any e-MB system expose measurement records to the contractor, an auditor, or an API? [?]
2. Do US state DOT as-built item records and final estimates reach per-item detail in practice, and
   are they released on a public records request? [?]
3. Are full contract agreements attached to award notices on any portal at scale? [?]
4. What are the actual terms of use for state DOT bid tabulations — the existence of commercial
   aggregators suggests permissive, which is an inference, not a licence. [?]
5. Do published Independent Engineer reports exist for Indian HAM or BOT projects, and are they
   closer to primary than the audit class? [?]

None of these is answerable by writing code, and all of them are answerable.

## Sources

- [TxDOT Construction and Materials Information System dashboard](https://www.txdot.gov/business/road-bridge-maintenance/contract-letting/construction-materials-system-dashboard.html)
- [TxDOT bid tabulations dashboard](https://www.txdot.gov/business/road-bridge-maintenance/contract-letting/bid-tabulations-dashboard.html)
- [WSDOT bid tabulations](https://wsdot.wa.gov/business-wsdot/contracts/about-public-works-contracts/public-works-contract-history/bid-tabulations)
- [ODOT bid item prices](https://www.oregon.gov/odot/business/pages/average_bid_item_prices.aspx)
- [AZDOT bid tabulations](https://azdot.gov/business/contracts-and-specifications/bid-tabulations)
- [FHWA bid tabulations](https://highways.dot.gov/federal-lands/business/construction-contracting/bids)
- [Caltrans Construction Manual, payment](https://dot.ca.gov/programs/construction/construction-manual/section-3-9-payment)
- [FDOT final measurements](https://fdotwww.blob.core.windows.net/sitefinity/docs/default-source/construction/manuals/cpam/newhistory/chapter5s15redline.pdf)
- [IDOT documentation of contract quantities](https://public.powerdms.com/IDOT/documents/2604144/Documentation%20of%20Contract%20Quantities%20Guide)
- [CPWD Works Manual](https://www.cpwd.gov.in/Publication/manualvolume2.pdf)
- [Running Account Bill, Form 47 / PW 410](https://easybids.in/R.A%20Bill.pdf)
- [Puducherry PWD computerised measurement book](https://pwd.py.gov.in/computerized-measurement-book-and-bills-be-submitted-contractor)
- [Tripura PWD e-MB implementation](https://pwd.tripura.gov.in/index.php/government/circulars/32-circulars/works/716-implementation-of-e-mb-electronic-measurement-book-and-generation-of-online-bill)
- [CAG Report No. 4 of 2017, contract variations in road works, Uttar Pradesh](https://cag.gov.in/uploads/download_audit_report/2017/Chapter_11_Contract_Variations_of_Report_No.4_of_2017_-_Contract_Management_in_Road_Works_Government_of_Uttar_Pradesh.pdf)
- [CAG compliance audit paragraphs, 2024](https://cag.gov.in/uploads/download_audit_report/2024/6-Chapter-III-066acd344852000.05574658.pdf)
- [Highway cost-escalation mechanism, WPI lag reduction](https://www.policyedge.in/p/highway-projects-to-get-monthly-cost-escalation-payments-as-govt-cuts-wpi-lag)
- [Effect of price escalation clause in highway construction](https://www.ijirset.com/upload/2023/july/205_Effect_NC.pdf)
