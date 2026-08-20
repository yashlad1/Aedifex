# Plan archive

Implementation plans for Aedifex development, newest first. Sits alongside [`docs/adr/`](../adr/) as
part of the engineering record: an ADR says what was decided, a plan says what was going to be built
and why.

Filenames are `YYYY-MM-DD-HHMM-<subject>.md`, where the timestamp is when the plan was written rather
than when it was filed here. Each file repeats that metadata in a header block, so a copy moved out
of this folder still says when it was written and what its status was.

| Created | Subject | Status |
|---|---|---|
| 2026-08-19 22:51 | [Reuse evaluation + finish the NHAI vertical slice](2026-08-19-2251-aedifex-reuse-evaluation-and-vertical-slice.md) | Approved for execution |

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
