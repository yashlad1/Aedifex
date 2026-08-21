# Aedifex Software Requirements Specification

## Project Vision, Mission & System Overview

**Version:** 0.1
**Status:** Living Document

> Read this before writing any Aedifex code. It defines what the project is *for*; every other
> document describes how a part of it works. Where a design decision and this document disagree,
> this document wins and the design is wrong.

---

## 1. Vision

Aedifex aims to become an evidence-driven construction intelligence platform that transforms
fragmented construction documentation into structured, explainable, and verifiable knowledge.

Instead of searching through thousands of PDFs, spreadsheets, drawings, emails, and reports, users
should be able to understand the complete state of a construction project through evidence-backed
findings.

Every conclusion produced by Aedifex must be traceable back to the original source documents.

The long-term goal is not document management. **The long-term goal is construction intelligence.**

---

## 2. Mission

Construction projects generate enormous amounts of information. Unfortunately:

- documents live in different systems
- information is duplicated
- relationships between documents are lost
- verification is manual
- auditing is expensive
- compliance is reactive
- fraud is difficult to detect
- project knowledge disappears over time

Aedifex exists to reconstruct those relationships automatically.

Instead of asking *"Where is this information?"* users should ask *"What does the evidence say?"*

---

## 3. Problem Statement

A single construction project may contain:

Tender Notices · Notice Inviting Tender (NIT) · Request for Proposal (RFP) · Bid Documents · BOQs ·
Contracts · Drawings · Technical Specifications · Measurement Books · Running Account Bills ·
Invoices · Payment Certificates · Material Registers · Inspection Reports · Quality Reports · Site
Photographs · Schedules · Correspondence · Variation Orders · Completion Certificates

Most of these exist as PDF, Excel, Word, images, HTML, XML, or email.

These documents reference each other but are rarely connected digitally. **Aedifex's purpose is to
recover these relationships.**

---

## 4. Product Goal

Aedifex is **NOT**:

- a crawler
- an OCR engine
- a PDF parser
- a document management system
- a chatbot
- an LLM wrapper

Those are implementation components.

Aedifex **IS** an evidence platform for construction projects. Everything else exists only to
support that mission.

---

## 5. Core Philosophy

Documents are not the product. **Evidence is the product.**

Documents contain facts. Facts become evidence. Evidence supports findings. Findings support human
decisions.

```text
Document
   ↓
Fact
   ↓
Evidence
   ↓
Rule
   ↓
Finding
   ↓
Decision
```

Human users remain responsible for final decisions. AI assists humans. **AI never replaces
evidence.**

---

## 6. Long-Term Architecture

Every source follows the same pipeline.

```text
External Source
   ↓
Discovery
   ↓
Acquisition
   ↓
Validation
   ↓
Immutable Raw Storage
   ↓
Text Extraction
   ↓
Structured Facts
   ↓
Relationships
   ↓
Evidence Graph
   ↓
Deterministic Rules
   ↓
Findings
   ↓
Human Review
   ↓
Business Decision
```

Every future component must fit into this pipeline.

---

## 7. Data Acquisition

Aedifex is an **evidence acquisition platform**, and acquisition is broader than crawling. A document
may arrive from a public procurement portal, a manual upload, a customer export, an email, an ERP
system, cloud storage or an API, and **every path converges into the same immutable pipeline.** The
pipeline begins only once a document has been acquired. Origin affects **provenance** and nothing
after it: a measurement is a measurement whether it was fetched or handed over.

The crawler is **NOT** the product. Its responsibility — and that of every other acquisition path — is
only to acquire evidence safely:

- discover documents
- download documents
- validate documents
- preserve provenance
- preserve metadata
- preserve hashes
- preserve timestamps

It must never perform business reasoning.

---

## 8. Types of Data

### 8.1 Unstructured Data

PDFs, drawings, images, emails, Word documents, HTML, scanned documents.

These become immutable raw artifacts.

### 8.2 Semi-Structured Data

Tables, Excel, XML, JSON, OCR output.

These retain partial structure.

### 8.3 Structured Data

*Pre-award and award:* Tender Number · Estimated Cost · Contract Value · Bid Security · Completion
Period · Contractor · Employer · Road Length · Project Location · Material Quantity · Invoice Number ·
Payment Amount · Dates · Units · Coordinates

*Post-award:* Item Number · Contracted Quantity · Measured Quantity · Certified Quantity · Contract
Rate · Applied Rate · Line Amount · Retention · Mobilisation Advance and Recovery · Liquidated
Damages · Price Adjustment · Variation Reference · Sanction Reference · Test Value · Appointed Date ·
Extension Granted

These become Facts.

---

## 9. Facts

Facts are objective statements extracted from documents. Examples: Estimated Cost, Bid Security,
Contractor Name, Project Name, Tender ID, Completion Date, Road Length.

Fact extraction answers: **"What does the document state?"**

Facts never contain judgement.

---

## 10. Derived Facts

Derived facts are deterministic calculations. Examples: Bid Security %, Delay, Payment Difference,
Quantity Difference, BOQ Difference, Completion %, Risk Exposure.

Derived facts answer: **"What can be calculated?"**

They still contain no judgement.

---

## 11. Relationships

Construction documents rarely exist alone. Relationships eventually connect:

```text
Tender
   ↓
Contract
   ↓
BOQ
   ↓
Measurement Book
   ↓
Invoice / IPC
   ↓
Payment
   ↓
Completion
```

A **measurement precedes the bill it justifies** — work is measured, then claimed, then certified.
Stated the other way round, the question that matters (*is this claim supported by a measurement?*)
reads backwards.

This single chain is a simplification. Quantity, rate, money and time each run their own chain from
reference data to audit, and **a verification is almost always the comparison of two adjacent links**:
`measured → certified` is over-certification, `contracted → measured` without a variation is
unauthorised work, `gross → net` is a deduction error. See
[docs/research/CONSTRUCTION_INFORMATION_MODEL.md](docs/research/CONSTRUCTION_INFORMATION_MODEL.md) §1.

This becomes the Evidence Graph.

---

## 12. Rules

Rules consume facts. Examples: Bid Security complies · Invoice exceeds BOQ · Duplicate Payment ·
Quantity exceeds certified work · Retention released early · Missing approval.

Rules are deterministic. **Rules never guess.**

---

## 13. Findings

Findings are conclusions supported by evidence: `PASS`, `FAIL`, `REVIEW`, `INCONCLUSIVE`.

`REVIEW` means a person must look: the rule established a discrepancy but not its cause, and calling
that a failure would assert more than the evidence supports. `INCONCLUSIVE` means the evidence needed
was absent — not a failure of the document, and it must never be displayed as one.

Every finding must contain:

- rule
- evidence
- compared values
- explanation
- provenance

---

## 14. Market and personas

### 14.1 The primary market, and why this is stated here

**Primary: residential real estate, commercial real estate, and general building construction.**

**Secondary, later: highways, metro, utilities, industrial civil works, other public
infrastructure.** NHAI is a *validation corpus* — it exists to prove the pipeline survives a real
2001 contract with handwritten rates, and it defines nothing about the product.

This is in the SRS rather than in a plan because the failure it prevents is a slow one. Public
infrastructure agencies publish far more than private developers do, so research drifts toward
highways by gravity, and the corpus starts defining the product instead of validating it. That
happened here and had to be reversed. **Availability must never determine the canonical domain
model.** See [docs/research/PRODUCT_FIRST_CORPUS_DISCOVERY.md](docs/research/PRODUCT_FIRST_CORPUS_DISCOVERY.md).

The canonical workflow is horizontal and must work across every vertical above:

```text
Project → Contract → BOQ → Measurement → RA Bill / Claim → Certification → Payment → Variation
        → Quality Evidence
```

Reference documents — schedules of rates, codes, methods of measurement, price indices — **govern**
that flow without belonging to it.

### 14.2 Personas

The same evidence supports different users. Primary personas are the ones a building project has on
it every day.

| Persona | Primary? | Needs |
| --- | --- | --- |
| Developer / Owner | **yes** | Is what I am being billed supported by measured work? |
| PMC | **yes** | Certify progress and payment defensibly |
| Quantity Surveyor | **yes** | BOQ, quantity reconciliation, rate verification |
| Billing Engineer | **yes** | Prepare and check RA bills against measurement |
| Contracts Engineer | **yes** | Variations, deviations, claims, entitlement |
| Finance | **yes** | Invoice validation, payment verification, retention and recovery |
| Internal Audit | **yes** | Compliance, over-certification, fraud detection |
| General Contractor | **yes** | Get paid for measured work, evidence a claim |
| Consultant | no | Document review, technical validation |
| Site Engineer | no | Progress verification, drawing lookup |
| External Auditor | no | Evidence, explainability |
| Executive | no | Portfolio risk, project insights |

**No feature should exist without benefiting at least one persona**, and a feature that benefits
only a non-primary persona is a deferral rather than a decision.

---

## 15. AI's Role

AI is not the source of truth.

AI **performs**: semantic extraction, summarization, classification, question answering,
relationship suggestion, explanation.

AI **never performs**: arithmetic, compliance verification, security decisions, state transitions,
financial calculations.

Deterministic software remains authoritative.

---

## 16. End Goal

Eventually Aedifex should answer questions such as:

- Why was this invoice flagged?
- Show every document supporting this payment.
- Which contractors repeatedly exceed estimated quantities?
- Which projects have the highest financial exposure?
- Which tenders have inconsistent bid documents?
- What evidence supports this audit finding?

Every answer must be explainable.

---

## 17. Success Criteria

A successful Aedifex deployment allows a user to move seamlessly from:

```text
Finding → Evidence → Derived Fact → Fact → Relationship → Document → Page/Cell → Immutable Raw Artifact
```

without losing provenance. Derived facts and spreadsheet cells are part of the chain because computed
values and tabular evidence are both citable; `scripts/audit_traceability.py` walks exactly this path
over every stored finding and fails on a `PASS`, `FAIL` or `REVIEW` that cannot be traced.

- Every conclusion must be reproducible.
- Every extracted value must be traceable.
- Every rule must be explainable.
- Every document must remain immutable.

---

## 18. Guiding Principles

The following principles govern all future development:

1. Evidence over opinion.
2. Deterministic verification over AI guessing.
3. Provenance is never optional.
4. Raw data is immutable.
5. Every finding must be explainable.
6. AI assists; humans decide.
7. Every subsystem must contribute to the evidence pipeline.
8. The crawler is an ingestion mechanism, not the product.
9. Facts are reusable across multiple personas.
10. Build generic infrastructure, not one-off NHAI features.
11. Every new source should plug into the existing pipeline with minimal changes.
12. Optimize for correctness, traceability, and maintainability over implementation speed.

---

## 19. Current Development Strategy

**Superseded as of 2026-08-20:** the vertical slice below is complete, and the architecture is frozen
pending real-corpus evidence. Current priorities are in
[docs/plans/2026-08-20-development-priorities.md](docs/plans/2026-08-20-development-priorities.md).
The strategy is retained because its second half still governs.

The first milestone was **NOT** to build an auditing platform. It was to establish the reusable
evidence pipeline:

```text
Source → Document → Artifact → Text → Facts → Evidence → Rule → Finding → CLI/API
```

Once this vertical slice is complete, every future construction source should reuse the same
architecture.

Future work should expand **horizontally** (new document types, new sources, new facts, new rules,
new personas) rather than redesigning the pipeline.

---

## 20. Revision note

**2026-08-21, second revision.** Section 14 was rewritten from "Personas" to "Market and personas"
after the owner clarified the commercial target. Two things were added and nothing was removed: a
statement that the primary market is residential, commercial and general building construction with
infrastructure secondary, and a division of the persona list into primary and non-primary.

The reason is recorded because the mistake is repeatable: public infrastructure agencies publish more
documents than private developers, so three research passes drifted toward highways purely on
availability, and the NHAI corpus began to shape extractors, rules and OCR priorities. The corpus is
meant to validate the product, not define it. Nothing in the vision, mission, philosophy, AI boundary
or guiding principles changed — principle 10 already forbade one-off NHAI features, and this makes
the market it was protecting explicit.


**2026-08-20.** Six refinements were applied to this document as the output of the Construction
Information Model milestone. Each corrects a place where the SRS had fallen behind the implementation
or behind what real construction documents turned out to require. Nothing in the vision, mission,
philosophy, personas, AI boundary or guiding principles was altered.

| § | Change | Why |
| --- | --- | --- |
| 7 | Acquisition stated as broader than crawling; all paths converge, origin affects only provenance | Documents arrive by upload, export, email, ERP and API, not only by crawl |
| 8.3 | Post-award fact vocabulary added | The original list stopped at award and could not describe payment verification |
| 11 | Measurement Book moved before Invoice; the single chain noted as a simplification of four | A measurement precedes the bill it justifies; stated in reverse, quantity variance reads backwards |
| 13 | `WARNING` removed from the outcome vocabulary | Never implemented, and the database check constraint would reject it. `REVIEW` already carries that meaning |
| 17 | Derived Fact, Relationship and Page/Cell added to the traceability chain | All three exist and are traversable; the audit script walks this path |
| 19 | Superseded by the development priorities record | The vertical slice it describes is complete |

The analysis behind these changes, including the minimum document set for each verification domain and
what would falsify it, is in
[docs/research/CONSTRUCTION_INFORMATION_MODEL.md](docs/research/CONSTRUCTION_INFORMATION_MODEL.md).
