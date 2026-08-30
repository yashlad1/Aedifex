# The Reality Sprint — from 2026-08-24

> **Amended 2026-08-30.** The freeze clause is lifted by
> [ADR 0019](../adr/0019-synthetic-benchmark-corpus-and-conditional-unfreeze.md); its premise was
> that time not spent engineering would be spent acquiring market evidence, and six days later the
> interview count is still zero. **Targets 1 and 2 below stand unchanged and are still the goal.**
> The *Do not build* list stands unchanged. What changed is that a Tier 5 synthetic document is now
> an admissible evidence ID, and the reason is in the ADR.

Status: **standing direction, freeze clause superseded.** Supersedes the engineering cadence of
[2026-08-20-development-priorities.md](2026-08-20-development-priorities.md), whose priority order it
keeps. Origin: a full repository review on 2026-08-24 that read the architecture, SRS, ADRs, corpus
strategy, API, frontend, verification code and requirements, not just the Sprint 1 report.

## The finding

> The platform is sufficiently complete for the next experiment. Writing more code is now likely to
> **reduce** learning efficiency.

Roughly 26,300 lines of application Python and 19,600 lines of test Python exist. The vertical slice
runs: acquisition → understanding → reasoning → review, with every finding walkable back to
immutable bytes. Against that:

| | |
| --- | --- |
| Interviews recorded in [../research/CUSTOMER_DISCOVERY.md](../research/CUSTOMER_DISCOVERY.md) | **0** |
| Authentic measurement books in any corpus tier | **0** |
| Authentic RA bills in any corpus tier | **0** |
| Tests | 2,130 unit + 98 integration |

That asymmetry — enormous engineering evidence, almost no market evidence — is the thing to correct,
and it is not correctable by writing code.

## Two hypotheses, deliberately separated

Do not let evidence for one be counted as evidence for the other. This has been the standing failure
mode of the project and it now has a name.

**Hypothesis A — technical.** *Given real construction records, can Aedifex reconstruct evidence and
identify discrepancies without inventing facts?*

Progressing well. The most valuable property found so far is that the system can measure its **own**
incompleteness against a document's stated totals: not "661 rows extracted" but "0.68% short of what
this bill says it contains, localised to these sections". The Sprint 1 regression where adding the
unit `RM` fabricated a priced row out of the word *platform* matters more than the thirteen rows
recovered, because it fixed the correctness philosophy in place:

> **Under-reading is visible. Fabricated financial evidence is not acceptable at any coverage.**

**Hypothesis B — commercial.** *Does anyone care enough about this reconciliation workflow to use it?*

There is **no evidence at all**. Zero interviews.

## The freeze

**Sprint 2 engineering is frozen** pending either a real bundle or an observed customer workflow.

The one exception is not "small fixes". It is this rule:

> **New engineering must carry an evidence ID.**

Legitimate:

```
REAL-001
RA bill from project X repeats BOQ item numbers per floor.
The current canonical key merges 17 unrelated lines into one work item.
→ SCRUM-XX  work-item identity redesign
```

Not legitimate:

```
We might eventually need fuzzy item matching.
```

An evidence ID names a document or an observed workflow. A hypothetical is not an evidence ID. File
the ticket with the evidence attached; do not add it to the active sprint, and do not manufacture
tickets to fill a sprint.

### Do not build

Frozen regardless of how reasonable each sounds in isolation: Neo4j or any graph database ·
microservices · Celery · Redis · Kafka · agent frameworks · a generic rules DSL · vector database ·
RAG · LLM document reasoning · handwriting architecture · a multimodal vision pipeline · mobile UI ·
dashboards · production deployment · Kubernetes · multi-tenancy · authentication · sophisticated
frontend testing · near-duplicate detection · PII redaction infrastructure.

Some of these will eventually be necessary. **None of them resolves the present uncertainty.**

**One clarification, because the two rules could be misread together.** "Do not build authentication"
does **not** relax the standing constraint that external deployment is blocked until authentication
and tenant isolation exist. Both hold: do not build auth, and do not deploy outside a development
machine. The production guard in the write API stays exactly as it is.

### The frontend is not to be beautified

Its current philosophy — *a review workspace, not a dashboard* — is correct and unusually so. No risk
gauge, no charts, no "AI confidence: 93%". For this product the killer interaction is *"why are you
telling me this?"* → the two original places in the records and the arithmetic between them. That is
worth more than any amount of polish.

## Target 1 — one authentic building bundle

The ask is already written and forwardable: [../DATA_REQUEST.md](../DATA_REQUEST.md).

**Change how it is used.** Four pages as a first contact asks for too much commitment. Use a funnel:

| Stage | What is sent | What is asked for |
| --- | --- | --- |
| 1 | Nothing | 15 minutes. No documents, no NDA discussion. Understand how RA billing actually happens |
| 2 | Nothing | *If* they recognise the workflow: "I'm testing something around exactly that — could I get a sanitised sample from a completed project?" |
| 3 | `DATA_REQUEST.md` / the PDF | The specific document set. The PDF is now supporting material, not the pitch |

Take a partial bundle. BOQ + measurement sheet + one RA bill, from one project, is dramatically more
valuable than another hundred public tenders. **Do not let the perfect bundle prevent acquisition.**

## Target 2 — ten interviews

`CUSTOMER_DISCOVERY.md` sets review checkpoints at 15 and 30. Do not wait for 30 to start thinking;
start at 10.

Talk to people who **touch payment evidence**: quantity surveyors, billing engineers, project
controls, PMC/consultant QS, contracts engineers, developer-side project accounting, internal
construction auditors, contractor billing teams.

Less useful at this stage: generic civil engineers, architects who do not certify bills, executives
far from the documents, construction-tech enthusiasts.

**The one question that matters most** is now in the interview template:

> *"Show me how you checked the last bill."*

Not "how do you usually check bills". People describe workflows badly in the abstract and demonstrate
them accurately. Watching someone say *"first I open this workbook, then I copy this, then I look up
the previous RA, then I ask site engineering because this item number changed"* is worth more than
twenty feature questions — and it is where the business-object model will come from.

## Do not design the canonical construction schema yet

`Project · Contract · BOQ · Work Item · Measurement · Bill · Payment · Variation · Inspection` is a
reasonable list. **Do not turn it into tables.**

The open question is not the list; it is identity. `item 1.3` is already known not to be unique
inside a single composite BOQ, because sub-bills restart their numbering. A work item's real key
might be `Part + Section + Item`, or a BOQ item code, or a customer's own billing code, or in places
a description. A real billing bundle answers this. One university tender does not.

## When the bundle arrives

**Do not modify Aedifex first.** Preserve the files exactly, and run them through HEAD unchanged.
That first run is the experiment; changing the parser first destroys it.

Record, per document:

```
accepted?  ·  classified correctly?  ·  text readable?  ·  rows extracted?
facts extracted?  ·  work items created?  ·  cross-document joins correct?
rules applicable?  ·  findings sensible?  ·  citations correct?  ·  reviewer able to verify?
```

Every failure lands in exactly one bucket, and the buckets are the architecture backlog:

| | |
| --- | --- |
| **A** | Extraction failure |
| **B** | Semantic / model failure |
| **C** | Reconciliation failure |
| **D** | Verification-rule failure |
| **E** | UX / workflow failure |

### Acceptance criteria for the first authentic project

Not "it processed successfully".

1. **Evidence integrity — zero fabricated financial facts.** Non-negotiable. A missing row is a gap;
   an invented one is money from nothing.
2. **Traceability.** Every conclusive finding reaches finding → rule inputs → extracted fact →
   source location → original artifact. `scripts/audit_traceability.py` already enforces this.
3. **Work-item matching.** Hand-sample 30–50 cross-document items and classify each as correct /
   wrong / missed / ambiguous. This is likely the first genuinely useful model-quality metric.
4. **Extraction completeness.** Wherever the source states a total or subtotal, compare Σ extracted
   against it. Sprint 1 proved how strong this is; make it a first-class evaluation technique.
5. **Finding precision, judged by a QS or billing person**, not by us: correct · incorrect ·
   technically correct but useless · useful · important. **Correct and useful are different axes, and
   a product can be 99% correct and commercially worthless.**

## The metric Aedifex should eventually own

Not document accuracy, not OCR accuracy, not AI accuracy. Recorded here as a definition only —
**not to be implemented under the freeze:**

> **Evidence Coverage** — what percentage of an RA bill's claimed monetary value can Aedifex trace
> through the required evidence chain?

```
RA Bill value              ₹10,000,000
Matched to contract rate    ₹9,600,000
Matched to measurement      ₹8,900,000
Fully evidence-backed       ₹8,500,000
                            ──────────
Evidence coverage                  85%
```

Uncovered does not mean wrong. It means **Aedifex cannot prove it** — which is exactly what this
architecture is built to say, and is the honest version of a confidence score.

## Standing disposition of open engineering tickets

| | | |
| --- | --- | --- |
| SCRUM-24 | Split-line rows, ₹58,15,059.75 unread | **Parked.** The system already knows this value is missing, so the gap is bounded and visible. The real risk is a second parser double-reading rows the line parser already has. Priority changes the moment a *customer* document shows the same layout |
| SCRUM-25 | Rows with no unit in the source | **Leave alone.** A quantity with no unit is weaker evidence. Do not helpfully infer one. Aedifex's advantage is that it knows what it does not know — not that it usually guesses right |
| SCRUM-14 | Bill versus estimate | More interesting than SCRUM-24, still not now. ₹85,43,91,859.40 against ₹85,39,81,318.41 says there is a difference, not that it is a problem. Until the estimate's meaning, permitted deviation and contract rules are established, a deterministic `FAIL` is unjustified — `INCONCLUSIVE` plus the difference may be the right answer permanently. Let a real user say whether the comparison matters |
| US DOT bid tabulations | The "unblocked win" in the corpus roadmap | **Not this sprint.** Valuable only if no bundle arrives for a long stretch, or if discovery points at rate benchmarking rather than payment verification. Otherwise it recreates the exact failure the SRS names: public availability defining the product. Aedifex is for **buildings**; another abundant highway dataset pulls it sideways |

## Sprint 2, structured as learning objectives

Not seven engineering tickets.

Tracked as **Sprint 2 — reality**, 31 August to 6 September, on board SCRUM.

| Objective | Success | Ticket |
| --- | --- | --- |
| Authentic data | 1 real building bundle in hand | SCRUM-10, carried from Sprint 1 |
| Customer discovery | 10 interviews recorded | SCRUM-28 |
| Workflow observation | ≥3 people actually demonstrate billing or reconciliation | SCRUM-29 |
| Product signal | A recurring pain, quantified, from independent people | SCRUM-30 |
| Technical validation | First bundle run through **unchanged** HEAD | SCRUM-31 |
| Evidence validation | A human checks the generated findings and citations | SCRUM-32 |
| Architecture decision | Only changes the bundle demanded are approved | *Not a ticket — rule 101* |
| Engineering | Bugs required by the above, and nothing else | *Not a ticket — rule 101* |

The last two are deliberately not tickets. They are standing policy, and turning a policy into a
sprint item is how it quietly becomes optional. Epic **SCRUM-27 — Customer discovery** is new; the
board had four epics and none of them covered talking to anybody.

**Stretch:** a second project. One project tells you what is possible; two begin telling you what is
general.

## The commercial question to keep open

Payment verification is plausible, not proven. Interviews must be allowed to **kill** it. The bigger
pain may turn out to be preparing RA bills rather than auditing them, or reconciling BOQ items
between contractor and consultant spreadsheets, or variation tracking, certification delay, material
reconciliation, subcontractor reconciliation, document retrieval, rate analysis, compliance evidence
or tender comparison.

If ten people independently say *"RA checking isn't really the problem — our nightmare is
variations"*, Aedifex moves there. The lower-level architecture survives that pivot intact, which is
precisely why a product-agnostic evidence pipeline was worth building first.

## The order of operations

1. Send the data request through warm construction contacts — people who can reach completed-project
   commercial files.
2. Book five interviews. Do not pitch Aedifex.
3. Ask each one to walk through a recent RA-bill verification.
4. Create no speculative engineering tickets.
5. Engineering stays frozen pending a bundle or an observed workflow.
6. Documentation consistency only. *(Done 2026-08-24.)*
7. When the bundle arrives: preserve it exactly, run HEAD unchanged, change nothing first.
8. Record every failure from that run as experimental evidence, in its bucket.
9. Have the person who supplied the files review the resulting findings.
10. Then decide what Aedifex actually needs next.

## The line to keep in view

The dangerous outcome is spending another month taking 2,130 tests to 4,000 while still holding
**0 measurement books, 0 authentic RA bills and 0 customer interviews** — arriving at one of the
best-tested implementations of the wrong product.

**The next significant Aedifex commit should exist because a real construction professional or a real
project document forced it to exist.**
