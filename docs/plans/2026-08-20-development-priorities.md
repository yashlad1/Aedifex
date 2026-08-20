# Development priorities — from 2026-08-20

Status: standing direction. Supersedes the vertical-slice sprint override, which achieved its
objective.

The platform architecture is **complete unless real construction data demonstrates otherwise.** No
new infrastructure, abstractions, frameworks or architectural layers without evidence from a real
corpus.

## The question every feature must answer

> What construction decision does this help a real user make?

If no real user decision improves, do not build it.

## Priority order

1. **Acquire real post-award construction documents.**
2. **Build a canonical construction business model** — Project, Contract, BOQ, Work Item,
   Measurement, Bill, Payment, Variation, Inspection.
3. **Populate the evidence graph using those business objects**, rather than documents alone.
4. **Implement deterministic audit rules from real industry workflows**, not synthetic examples.
5. **Build persona-specific views** over the same evidence graph.
6. **Use AI only for explanation, summarisation, search and report generation** — never for
   financial or compliance decisions.

Item 6 is not a priority so much as a boundary, and it already holds: no model is consulted anywhere
in the calculation or verification path.

## Why 1 gates 2 through 5

Items 2 to 5 are architecture, and the standing constraint is that architecture needs corpus
evidence. Designing the business model before the documents exist would mean inventing a schema from
imagination and then bending real records to fit it — which is the failure mode the SRS names as
principle 10, and the reason the vertical slice was built narrow.

Concretely: the existing model has `Project`, `Document`, `WorkItem`, `ExtractedFact`, `DerivedFact`,
`Finding` and `DocumentRelationship`. Whether `Contract`, `Measurement`, `Bill`, `Payment`,
`Variation` and `Inspection` should be tables, relationship types, or document classifications is a
question **one real IPC and one real measurement book would settle in an afternoon** and that no
amount of reasoning settles now.

## The ecosystem survey behind these priorities

[docs/research/CORPUS_ROADMAP.md](../research/CORPUS_ROADMAP.md) catalogues the construction document
lifecycle — 56 document types across pre-award, award, post-award, audit and reference — with producer,
consumer, contents, primary-or-secondary standing, and likely Aedifex mapping for each, plus a gap
analysis against the measured corpus and ranked acquisition recommendations.

Its two conclusions that bear directly on priority 1: the **contract agreement** unlocks more rules
than any other single document, because every post-award threshold lives in it and none may be
configured; and **US state DOT bid tabulations** are line-item priced construction data that is
already public and needs nothing from anyone, which makes them the only recommendation that is not
blocked.

## What the corpus cannot currently deliver

Every source in `DATA_SOURCES.md` — approved, candidate, and blocked alike — is **pre-award**:
tenders, notices, bid documents, schedules of rates, award notices. Not one of them publishes a
measurement book, an interim payment certificate, a variation order or an inspection record.

So priority 1 is not "crawl harder". It needs either a new class of source or a document handed over
directly, and both are decisions for the owner. Candidate post-award sources are recorded in
`DATA_SOURCES.md` for legal review; none is approved and none is being collected.

## The trigger for the next implementation work

No implementation work begins until one of these arrives:

- a real **Measurement Book**
- a real **IPC / RA Bill**
- a real **Variation Order**
- a real **Payment Certificate**
- a real **Schedule of Rates or other reference document required by an actual rule**

Then: run it through the current pipeline **first**, unchanged, and let the document determine the
next architecture change. Not the reverse.

One design constraint is already settled so that it cannot be got wrong under time pressure: project
facts stay isolated by default, and reference evidence reaches a rule by explicit, evidence-backed
applicability rather than by global scope —
[ADR 0014](../adr/0014-reference-data-by-explicit-applicability.md).

## The distinction the business model will have to make

Named here because the candidate sources force it, and because it is the one design conclusion that
current evidence does support.

A document that **is** a record — a measurement book, an IPC — states a primary fact: *this quantity
was measured*. A document that **reports on** records — a CAG audit report, an arbitration award —
states a fact about a fact: *the audit found that this quantity was billed and not measured*.

Both are real evidence and both are traceable to a page. They are not interchangeable, and a model
that stored them the same way would let a finding claim primary measurement authority for a figure
quoted second-hand in a narrative. Any business model built for priority 2 has to carry that
difference, whichever of the candidate sources is approved.
