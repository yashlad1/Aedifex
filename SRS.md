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

The crawler is **NOT** the product. Its responsibility is only to acquire evidence safely:

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

Tender Number · Estimated Cost · Contract Value · Bid Security · Completion Period · Contractor ·
Employer · Road Length · Project Location · Material Quantity · Invoice Number · Payment Amount ·
Dates · Units · Coordinates

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
Invoice
   ↓
Measurement Book
   ↓
Payment
   ↓
Completion
```

This becomes the Evidence Graph.

---

## 12. Rules

Rules consume facts. Examples: Bid Security complies · Invoice exceeds BOQ · Duplicate Payment ·
Quantity exceeds certified work · Retention released early · Missing approval.

Rules are deterministic. **Rules never guess.**

---

## 13. Findings

Findings are conclusions supported by evidence: `PASS`, `FAIL`, `WARNING`, `REVIEW`, `INCONCLUSIVE`.

Every finding must contain:

- rule
- evidence
- compared values
- explanation
- provenance

---

## 14. Personas

The same evidence supports different users.

| Persona | Needs |
| --- | --- |
| Contractor | Tender preparation, compliance checking |
| Consultant | Document review, technical validation |
| Quantity Surveyor | BOQ, quantity reconciliation |
| Site Engineer | Progress verification, drawing lookup |
| Finance | Invoice validation, payment verification |
| Internal Auditor | Compliance, fraud detection |
| External Auditor | Evidence, explainability |
| Executive | Portfolio risk, project insights |

**No feature should exist without benefiting at least one persona.**

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
Finding → Evidence → Fact → Document → Page → Original Source
```

without losing provenance.

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

The current milestone is **NOT** to build an auditing platform. The current milestone is to
establish the reusable evidence pipeline:

```text
Source → Document → Artifact → Text → Facts → Evidence → Rule → Finding → CLI/API
```

Once this vertical slice is complete, every future construction source should reuse the same
architecture.

Future work should expand **horizontally** (new document types, new sources, new facts, new rules,
new personas) rather than redesigning the pipeline.
