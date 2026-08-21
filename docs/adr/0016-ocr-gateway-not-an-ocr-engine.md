# 16. Aedifex owns an OCR gateway and a trust boundary, not an OCR engine

Date: 2026-08-21

## Status

Accepted as direction. **Nothing is implemented by this ADR**, deliberately: the routing it describes
must not be built until a real building corpus settles which lanes are actually needed
(see [PRODUCT_FIRST_CORPUS_DISCOVERY.md](../research/PRODUCT_FIRST_CORPUS_DISCOVERY.md) §6.5).

Supersedes nothing. [ADR 0015](0015-ocr-execution-shape-on-apple-silicon.md) stands unchanged — its
measured execution shape becomes the configuration of one lane rather than of the whole pipeline.

## Context

Three research passes went into OCR: a bounded-parallelism optimisation, an engine comparison across
RapidOCR/GOT-OCR2/Surya, and a layout and table-structure survey. All three were useful and all three
answered the same shape of question — *which recogniser is best?*

That question is the wrong one to keep asking, for a reason the surveys themselves produced:

- **Every conclusion came from one document.** The handwriting problem, the table problem and the
  per-cell failure were all measured on a 2001 NHAI highway contract with handwritten rates. The
  corpus that arrived afterwards — real building bills — needed **no OCR at all**: every acquired PDF
  had a text layer, and the most valuable BOQs were `.xlsx`.
- **The best reader was unusable for reasons unrelated to accuracy.** Surya read the corrupted IPC
  payment value correctly and emitted real HTML table structure, and it is disqualified twice over:
  non-deterministic between identical runs, and non-commercially licensed.
- **The recogniser market moves faster than this project can.** Between the layout survey and this
  ADR, `microsoft/trocr-base-handwritten` (MIT) was confirmed as exactly the permissively-licensed
  handwriting recogniser the survey said was missing. Any architecture that has to be edited to
  adopt it is the wrong architecture.

Meanwhile the parts that are genuinely Aedifex's own — bounded execution, page provenance, engine and
version on every derived fact, `OCR_MAX_PIXELS` after a native crash, and precision-aware arithmetic
validation — are all engine-independent and none of them is OCR research.

## Decision

**Aedifex does not build, train or fine-tune an OCR model. It builds the gateway around one.**

Five commitments:

1. **Deterministic routing by document class.** The class decides the lane; a model never decides
   which model runs.

   ```text
   XLSX/CSV          -> native cell read          -> cell provenance
   PDF w/ text layer -> pdftext / pdf_boq         -> span provenance
   printed scan      -> RapidOCR (Apache-2.0)     -> page provenance
   typed table       -> layout model (TATR/Docling/PP-Structure)
   handwritten table -> handwriting lane (TrOCR / permissive VLM)
   photograph        -> deskew, then as above
   ```

2. **Engine identity is provenance.** Every fact derived through the gateway records the engine name,
   its version and the bounds in force. Facts from different engines must remain distinguishable for
   as long as they are stored, because a reading of pixels is not the same evidence as a span of a
   text layer.

3. **The trust boundary is deterministic, not probabilistic.** No engine's output becomes a money
   fact on the engine's own confidence. It becomes one when deterministic validation closes
   (`aedifex.calculation.row_arithmetic`, `verification.bill_total`) or when a human accepts it.
   Otherwise the outcome is `REVIEW` or `INCONCLUSIVE`. Stated as the product requirement it serves:
   **never turn uncertain document reading into a confident financial finding.**

4. **Swapping an engine changes no verification code.** The acceptance test for this ADR is that
   adopting a new recogniser is a registration, not an edit to the verification layer.

5. **RapidOCR remains the baseline for ordinary printed scans, and no further effort goes into making
   it do handwriting or complex tables.** It is Apache-2.0, deterministic, installs without a system
   binary, and reads printed prose at 1.00 digit recall. Those are the properties a baseline needs.

Permissively licensed options are preferred in this order, all licences read from model cards rather
than PyPI: **Apache-2.0 / MIT** (RapidOCR, PP-OCRv5, TrOCR, TATR, Docling, granite-docling,
GOT-OCR2, Florence-2, Qwen2.5/3-VL, InternVL3, olmOCR, DeepSeek-OCR) → **commercial API** where data
residency permits → **never** non-commercial or copyleft weights (Nougat CC-BY-NC, Surya CC-BY-NC-SA,
LayoutLMv3 CC-BY-NC-SA, Marker RAIL-M, DocLayout-YOLO AGPL code, MinerU AGPL).

**Fine-tuning is gated behind four conditions, all of which must hold:** enough representative
labelled examples; the same failure recurring; no permissively licensed off-the-shelf model solving
it adequately; and a material effect on a user workflow. Today **none** holds.

## Consequences

**Good.**

- The ML choice stops being an architectural commitment. Today's best model can be wrong in six
  months without the backend caring.
- The engineering that survives is the engineering that is actually Aedifex's: bounds, provenance,
  arithmetic, review. All of it is already written and none of it is engine-specific.
- Licence risk is contained at one seam instead of being spread through the extraction layer.
- It stops a real failure mode: three research passes in a row that improved a recogniser without
  moving a user through a workflow.

**Costs, stated plainly.**

- A gateway with one lane is indistinguishable from today's module plus indirection. **The abstraction
  is not worth building until a second lane is justified by a real document**, which is why this ADR
  implements nothing. Building it now would be exactly the speculative infrastructure the
  development priorities forbid.
- Multiple engines mean multiple provenance shapes, and comparing a `REVIEW` produced by one engine
  with a `REVIEW` produced by another is a genuine open problem.
- A commercial API lane sends evidence to a third party. That is a data-residency and confidentiality
  decision for the owner, per source, and it is not a technical default.

**What already exists and needs no change:** the `OcrEngine` Protocol (`name`, `version`, `read`) is
the seed of the gateway and was written for exactly this reason — so that replacing the engine is a
new implementation rather than a change to the module.

**What would falsify this ADR:** a target-corpus document class where deterministic validation cannot
be constructed at all, so the only available trust signal *is* model confidence. That would mean the
trust boundary has to become probabilistic, and commitment 3 would need revisiting rather than
patching.
