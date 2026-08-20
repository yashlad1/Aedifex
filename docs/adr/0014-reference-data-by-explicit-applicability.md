# 14. Reference data enters a rule by explicit applicability, never by global scope

Date: 2026-08-20

## Status

Accepted (pre-implementation, deliberately deferred)

## Context

Aedifex distinguishes **project data** — contract agreement, Measurement Book, RA Bill / IPC,
variation orders, inspection reports, payment certificates — from **reference data** shared across
many projects: tender notices, standard specifications, Schedule of Rates, material specifications,
government circulars, contract clauses, procurement rules.

The current model holds project data and structurally cannot hold reference data. A document joins a
project through an identifier it states **about itself**, and rules compare facts only within one
project. Reference data has no such identifier by nature — a Schedule of Rates belongs to no tender —
so today it lands in `documents_without_project_key` and is invisible to every rule.

That scoping is not an accident, and this is the whole reason for writing this ADR before any code:
**strict project isolation is what makes cross-document comparison safe.** Two projects quoting
identical figures have nothing to say about each other, and a rule that could reach across projects
by default would eventually compare a quantity from one job against a rate from another and report it
as a discrepancy. The obvious fix for the reference-data gap — a "global" or "applies to everything"
document — removes exactly that protection, and it is the fix a future contributor is most likely to
reach for because it is one boolean column.

## Decision

**Project facts remain isolated by default. Project scoping is not weakened.**

Reference evidence reaches a rule through **explicit, evidence-backed applicability**, not through
global visibility. The shape is:

    project evidence  +  applicable reference evidence  →  rule evaluation

Applicability is a recorded, defensible claim that a particular reference document governs a
particular project — of the same standing as any other relationship in this system, and therefore
carrying provenance. Dimensions that may later express it include jurisdiction, issuing authority,
contract type, effective date, project type, or an explicit operator link. Which of those are needed,
and whether they are columns, relationship types or predicates, is **not decided here**.

**Nothing is built now.** Implementation begins only when a real document requires it, and the
document determines the design rather than the reverse.

## Alternatives considered

**A global flag on the document** (`is_reference: true`, visible to every project). One column, and
it silently discards the isolation invariant for every rule at once. An unapplicable circular from
the wrong state or a superseded rate schedule would be in scope for every project in the database,
and nothing in the finding would say why it applied. Rejected.

**A null project, treated as "matches all".** The same defect wearing different clothes, and worse
for being implicit: `NULL` as a wildcard is invisible at the call site, and the existing partial
unique indexes already depend on `NULL` meaning "not applicable" rather than "any".

**Copy the reference document into each project.** Preserves isolation and destroys identity: one
Schedule of Rates becomes forty documents, content addressing deduplicates the bytes but not the
facts, and a correction to the reference has to be applied forty times. Also makes "which projects
did this circular affect?" unanswerable, which is a question an auditor will ask.

**Resolve applicability with a model.** Jurisdiction and effective date are exactly the kind of
judgement an LLM appears good at. It is also a compliance decision, which the SRS puts permanently
outside what a model may do. A rule's threshold is evidence, not inference — the same conclusion
already reached for the prescribed bid-security rate.

## Consequences

A rule that consumes reference evidence will have to state which reference documents it applied and
why, so the finding remains walkable: Finding → Evidence → … → Document, with the applicability claim
itself provenanced. That is more work than a global flag and it is the point.

`project_documents` is already a join table, so the schema permits one document in many projects. No
migration is implied by this ADR, and none should be written until a real document forces the
question.

Until then the gap stays open and recorded, as N7 in
[the real-data findings log](../plans/2026-08-20-real-data-findings.md). Reference data being
unreachable is a visible, honest limitation; reference data being reachable for the wrong reasons
would not be.
