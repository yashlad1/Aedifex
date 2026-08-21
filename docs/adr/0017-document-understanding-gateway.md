# 17. A Document Understanding Gateway with capabilities, not an OCR pipeline with a router

Date: 2026-08-21

## Status

Accepted as direction, and it **refines [ADR 0016](0016-ocr-gateway-not-an-ocr-engine.md) rather than
replacing it**. 0016 said *don't build OCR, own the trust boundary*. This one fixes the shape: the
subsystem is not an OCR gateway with a router in front of it, it is a **classifier that selects a
capability**, and OCR is one capability among several.

**Nothing is implemented by this ADR**, for the same reason 0016 implements nothing: a gateway with
one lane is indirection, and the lanes must be justified by real target-corpus documents.

## On the request to make the trust-boundary sentence ADR 0001

The owner's instruction was to elevate *"Aedifex owns the trust boundary, not the recogniser"* to
ADR 0001 because everything else follows from it. The intent is right and it has been acted on — but
**not by renumbering**, and the reason is worth recording.

ADRs are an append-only decision log. ADR 0001 is *"record architecture decisions"*, dated when the
log began; rewriting it would falsify the record, break every existing cross-reference, and make the
numbering stop meaning "the order in which we decided things". A decision log that can be reordered
is not evidence of anything — which is the same argument this project makes about raw documents.

So the sentence was elevated **above** the ADR log instead, to where it actually governs: it is now
**Principle 0 in [SRS §18](../../SRS.md)**, the principle the other fourteen are consequences of. The
SRS is the document that wins when a design disagrees with it, so this is a stronger placement than
ADR 0001 would have been, not a weaker one.

## Context

ADR 0016 drew the boundary correctly and then drew the internals wrong:

```text
Gateway → Router → OCR          ← wrong: OCR is the destination, everything routes *to* it
```

That shape smuggles the old assumption back in. It implies the subsystem's job is reading pixels and
that non-OCR paths are exceptions, when the evidence says the opposite: **the most valuable documents
in the corpus needed no OCR at all.** Every acquired building BOQ had a text layer, and the best of
them were `.xlsx` with cell-level provenance already intact.

Naming it "OCR" also mis-describes what exists today. `aedifex.extraction` already contains a
spreadsheet reader, a PDF text-layer reader, two BOQ row readers and a policy reader. OCR is the
newest and least-used of them, and it is the only one the subsystem is named after.

## Decision

**The subsystem is a Document Understanding Gateway. Its unit of dispatch is a capability, selected
by a classifier from the document class.**

```text
Document
   ↓
Classifier                     format + document class + does it have a text layer?
   ↓
Capability
   ├── spreadsheet cells       XLSX / CSV        → cell provenance
   ├── native text             PDF w/ text layer → span provenance
   ├── printed recognition     scan              → page provenance      (RapidOCR)
   ├── table structure         typed table       → row + cell provenance
   ├── handwriting recognition handwritten       → cell provenance, LOW confidence
   └── image preparation       photograph        → deskew/dewarp, then re-dispatch
   ↓
Evidence objects               ← the contract; nothing downstream knows which capability ran
   ↓
Deterministic rules → cross-document validation → findings → human review
```

Five commitments, the first four inherited from 0016 and still binding:

1. **Routing is deterministic.** Document class selects the capability. A model never selects a model.
2. **Capability identity is provenance.** Name, version and bounds on every derived fact, forever.
3. **No capability's output becomes a money fact on its own confidence** — only when deterministic
   validation closes or a human accepts it.
4. **Adding a capability is a registration, not an edit to the pipeline.**
5. **New: capability precedence follows information preserved, not novelty.** Spreadsheet cells →
   native text → OCR → vision. Codified as SRS principle 14. A capability that recovers structure
   from pixels is always second-best to one that reads structure that was never destroyed.

**Consequence for priorities: the spreadsheet capability is the most under-invested part of the
system relative to its value**, and vision models are the least urgent. This inverts the order the
last three research passes implicitly used.

## Consequences

**Good.**

- The name stops lying. Six extractors exist and one of them is OCR.
- Precedence becomes explicit, so "should we OCR this?" is answered by the classifier rather than by
  whoever is writing the feature.
- IFC and DWG have somewhere to go if a customer brings them, without a new subsystem.
- "Human review when uncertain" becomes implementable, because commitment 3 needs a review mechanism
  to be a real boundary rather than an aspiration. That mechanism does not exist yet and is the next
  thing to build.

**Costs.**

- **Classification is now a first-class concern, and it collides with an existing hard-won
  decision.** `runner.py` deliberately requires the *reference-versus-project role* to be **declared
  at ingest and never inferred**, because inferring it produced five false facts from real
  documents. So a classifier may propose a `document_type`, and it may not silently set the role that
  gates fact suppression. Those must stay separate fields with separate authority: a suggestion a
  human confirms, not a decision a model makes.
- `classification_confidence` and `classifier_version` exist on `documents` and have never been
  written. They are the right columns for a *suggestion* and must not be repurposed as the role.
- Comparing a `REVIEW` from one capability with a `REVIEW` from another remains unsolved.

**What would falsify this ADR:** a document class where no deterministic validation can be
constructed, so the only available trust signal is the model's own confidence. Commitment 3 would
then need revisiting rather than patching.
