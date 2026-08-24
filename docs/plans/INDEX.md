# Plan archive

Implementation plans for Aedifex development, newest first. Sits alongside [`docs/adr/`](../adr/) as
part of the engineering record: an ADR says what was decided, a plan says what was going to be built
and why.

Filenames are `YYYY-MM-DD-HHMM-<subject>.md`, where the timestamp is when the plan was written rather
than when it was filed here. Each file repeats that metadata in a header block, so a copy moved out
of this folder still says when it was written and what its status was.

| Created | Subject | Status |
|---|---|---|
| 2026-08-24 | [The Reality Sprint](2026-08-24-reality-sprint.md) | **Standing direction — engineering frozen** |
| 2026-08-24 | [Dependency review](2026-08-24-dependency-review.md) | Executed — one merge, two rejections, ten deferrals |
| 2026-08-21 | [First product workflow](2026-08-21-first-product-workflow.md) | Executed — review, intake, classification and the viewer all shipped |
| 2026-08-20 | [Development priorities](2026-08-20-development-priorities.md) | Standing direction |
| 2026-08-20 | [Real post-award data — findings](2026-08-20-real-data-findings.md) | Live record |
| 2026-08-19 | [Vertical slice — known limitations](2026-08-19-vertical-slice-known-limitations.md) | Live record |
| 2026-08-19 22:51 | [Reuse evaluation + finish the NHAI vertical slice](2026-08-19-2251-aedifex-reuse-evaluation-and-vertical-slice.md) | Executed |

## How this folder relates to the planning tool

These are **copies**. Plan mode's live working file stays at `~/.claude/plans/<generated-name>.md`
(currently `shiny-fluttering-volcano.md`) and is what the approval flow reads. Editing the copy here
does not change the plan under review — treat this folder as the record, not the source.

Aedifex plans only. One earlier plan exists for an unrelated project (Kaggriculture, a Kaggle
competition) and is deliberately kept out of this repo; it lives at
`~/.claude/plans/archive/2026-08-07-1738-kaggriculture-v0-smoke-test-agent.md`.

## Contents at a glance

**2026-08-19 — Reuse evaluation + finish the NHAI vertical slice.** Two parts. An
ADOPT/WRAP/BORROW/REJECT evaluation of Kingfisher Collect, Kingfisher Process, Scrapy and OCDS —
including a spike that corrected an earlier wrong claim about what Twisted can express — and the
remaining work to drive one real NHAI tender PDF through text extraction, field extraction, facts, a
deterministic rule, a persisted finding, and a CLI/API result whose evidence points back to a page
span.

**2026-08-19 — Vertical slice known limitations.** What the slice deliberately does not do, and the
testing debt taken on to finish it. Kept as a live record rather than closed, because a limitation
stops being one only when something replaces it.

**2026-08-20 — Real post-award data findings.** The live record of running real construction records
through the pipeline, classified BLOCKER / NEXT / DEFERRED. Started as an investigation of one real
priced bill of quantities that had been sitting in the corpus unread; now the standing log for
everything real data reveals.

**2026-08-20 — Development priorities.** The standing direction: architecture is complete unless real
data demonstrates otherwise, priority 1 is acquiring real post-award documents, and every feature
must name the construction decision it improves. Records why priorities 2–5 are gated on 1, and the
one design conclusion current evidence does support.

**2026-08-24 — The Reality Sprint.** Supersedes the cadence of the 2026-08-20 priorities while
keeping their order. Engineering is frozen: new work needs an **evidence ID** — a real document or an
observed reviewer workflow — and speculative tickets are not created. Separates the technical
hypothesis from the commercial one, and records what is currently true of each: strong evidence for
the first, **none at all** for the second. Contains the outreach funnel, the ten-interview target,
the protocol for the first authentic bundle (run HEAD unchanged, five failure buckets), the
acceptance criteria that replace "it processed successfully", the Evidence Coverage definition, and
the standing disposition of SCRUM-24, SCRUM-25, SCRUM-14 and the US DOT corpus.

## How real documents enter the pipeline

The operating rule for this phase, and the reason the findings document is a log rather than a plan:

1. **Run a real document through the pipeline unchanged first.** No preparatory refactor, no
   defensive parsing, no test written in advance of the failure. Let the document reveal the blocker.
2. **Classify every issue.** BLOCKER — prevents a trustworthy result on the real document, fix now.
   NEXT — a real improvement the current workflow can proceed without, record and continue. DEFERRED
   — speculative, or unsupported by the evidence in hand, do not build.
3. **Only a BLOCKER stops the flow.**

What this rule forbids, explicitly, because each has been tempting at least once: new equivalence
tables, identifier heuristics, document classifiers, parser abstractions and relationship types,
unless a real document demonstrates the need. Probing a function with plausible-looking inputs is not
such a demonstration — two normalisation gaps found that way (`21 (a)`, and a numeric spreadsheet
cell giving `1.0`) are recorded in the findings document and deliberately unfixed.

Raw evidence is preserved exactly. Normalisation is for comparison only, and any equivalence beyond
trivial case-folding must be backed by a document that shows it.

The goal is not a theoretically complete parser. It is for Aedifex to survive increasingly messy real
construction records while every finding stays explainable.

