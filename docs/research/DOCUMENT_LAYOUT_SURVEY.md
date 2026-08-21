# Document layout and table-structure engines, measured on the Aedifex corpus

Date: 2026-08-21
Research only. Nothing implemented, nothing added to Aedifex's dependencies. Every engine ran in a
throwaway virtualenv outside the project.

## The question

Not "which engine reads text better". RapidOCR already reads printed prose at 1.00 digit recall. The
question is whether any engine recovers

```text
Item | Quantity | Rate | Amount
```

as a **row**, with the handwritten rate attached to the right quantity, on a real priced bill of
quantities — and whether OCR can then be applied per cell.

Ground truth is self-verifying: all six data rows of the test BOQ satisfy `quantity × rate = amount`
exactly, so a reconstructed row can be checked without trusting anyone's reading of the page.

## Test pages

The same real pages throughout, from the Package V-A contract agreement (NH-2 Bihar, TNHP/7) and the
ABP-III payment register:

| Page | Why |
| --- | --- |
| **Priced BOQ** | printed item/description/unit/quantity, **handwritten rate and amount**, rotated 90° |
| **IPC payment register** | 37 payment rows, 1-bit `CCITTFaxDecode` fax scan, rotated 90° |
| Agreement prose | the fidelity control — money in digits *and* words |
| FIDIC contents | dense list, implicit columns, not a ruled table |
| Price-adjustment clause | formulae, the structure-without-a-table case |

---

## 1. Licensing — the gate, and it eliminates most of the field

Verified against model cards and `LICENSE` files, **not** PyPI metadata. PyPI reports code licences
and silently omits weights, which is exactly how Surya reads as Apache-2.0 when its weights are not.

| Candidate | Code | Model weights | Verdict |
| --- | --- | --- | --- |
| **Table Transformer (TATR)** | MIT | **MIT** | **Adoptable** |
| **Docling** (IBM) | **MIT** | CDLA-Permissive-2.0 · Apache-2.0 · MIT | **Adoptable** |
| **PaddleOCR / PP-Structure** | Apache-2.0 | Apache-2.0 | **Adoptable** |
| DocLayout-YOLO | **AGPL-3.0** | Apache-2.0 | **Blocked** — copyleft code |
| LayoutLMv3 ecosystem | MIT | **CC-BY-NC-SA-4.0** | **Blocked** — non-commercial |
| Nougat | MIT | **CC-BY-NC-4.0** | **Blocked** — non-commercial |
| MinerU (`magic-pdf`) | **AGPL-3.0** | — | **Blocked** |
| Marker | Apache-2.0 | **modified AI Pubs Open RAIL-M** | Owner decision |
| Surya 2 | Apache-2.0 | **modified AI Pubs Open RAIL-M** | Owner decision |

Three traps worth naming, because each inverts what a casual look suggests:

**LayoutLMv3's code is MIT and its weights are CC-BY-NC-SA-4.0.** Non-commercial weights remove the
entire LayoutLMv3 family from a proprietary product, however permissive the repository looks.

**DocLayout-YOLO is the mirror image** — AGPL-3.0 code inherited from the Ultralytics/YOLO lineage,
Apache-2.0 weights. Same outcome, opposite cause. This is the PyMuPDF decision again.

**Marker and Surya carry an identical RAIL-M weights clause** from the same vendor: free for research,
personal use and organisations under $5M funding or revenue; a paid licence beyond that, plus RAIL
behavioural use-restrictions. Evaluation falls inside the research clause and is what was done here.
Adoption is a payment obligation and is not a decision to make on accuracy grounds.

---

## 2. Table Transformer — structure only, and it is fast

`microsoft/table-transformer-detection` then
`microsoft/table-transformer-structure-recognition-v1.1-all`, both MIT, on MPS.

| Page | Detect | Structure | Reported | Ground truth | |
| --- | --- | --- | --- | --- | --- |
| Priced BOQ | 0.62 s | 0.56 s | **11 rows × 9 cols** | ~11 × **9** | **columns exact** |
| IPC register | 0.12 s | 0.52 s | 54 rows × 12 cols | ~41 × ~14 | over-counts rows |
| Agreement prose | 0.13 s | — | **no table** | none | **correct** |
| FIDIC contents | 0.12 s | 0.24 s | 56 rows × 5 cols | a list | debatable |
| Price-adjustment | 0.12 s | — | **no table** | none | **correct** |

**Both models load in 2.2 s and run in 0.12–0.62 s per page** — RapidOCR's league, and roughly three
orders of magnitude cheaper than a document VLM. It emits boxes and per-object confidences for rows,
columns, column headers and spanning cells, and it correctly declined to find tables on the two prose
pages, which matters: a layout stage that invents tables is worse than none.

On the BOQ it found **all nine column boundaries correctly** — `Item │ sub │ Description │ Unit │
Estimated │ Rate-in-words │ Rate-in-figures │ Amount-in-words │ Amount-in-figures` — with column
confidences 0.79–0.99.

**The rows are the problem.** The count is right but the bands drift where row heights vary. Verified
by cropping and looking: the band for row 9 contains **two** content rows, holding both `7.00` from
the row above and `857,000.00`. On a table whose rows are uniform this would not matter; on a real BOQ
where one item's description runs to three lines, it does.

### Integration cost, measured

TATR's published checkpoints **do not load on current `transformers` without three shims**:
`dilation: null` where a bool is now required; the same null nested inside `backbone_config` on the
v1.1 checkpoint; and a `preprocessor_config` carrying only `longest_edge` where DETR's resize now
demands a complete size pair. None is deep. Together they mean adopting TATR is adopting a config shim
against checkpoints nobody is updating.

---

## 3. The per-cell experiment, and why it failed

This is the architecture the brief proposes — layout first, then OCR per region — and it was tested
directly rather than assumed. TATR's row × column intersections give cells; each cell was cropped and
read on its own.

**The crops are correct.** The cell at row 4, column 6 contains exactly the handwritten `37,100.00`,
cleanly isolated, nothing else in frame.

| Per-cell recogniser | Correct | Notes |
| --- | --- | --- |
| RapidOCR (production weights) | **0 / 12** money cells | printed header cells read fine; **every handwritten cell returned empty** |
| RapidOCR, detection bypassed, padded, upscaled | **1 / 18** values | the second attempt, after fixing tight crops |
| GOT-OCR2 per cell | **1 / 12** money cells | `51180000`, `BAO`, `A200000`, `G84A000` |

Two separate conclusions, and both are negative:

**RapidOCR's recogniser cannot read cursive handwriting at all.** Not a cropping problem — it fails on
a perfect, isolated, upscaled crop of a legible handwritten number. PP-OCRv3's recognition model was
trained on printed text and handwriting is out of its distribution. No amount of layout analysis fixes
that.

**GOT-OCR2 gets *worse* per cell than on the whole page** — 1 of 12 isolated cells against 7 of 10 on
the full page. It is a VLM and it needs context; deprived of the surrounding table it degrades to
noise. **This is the finding that most changes the proposed architecture:** "segment, then OCR each
region" is not automatically better, and for a generative reader it is measurably worse.

My first run of this experiment was also **under-engineered and I nearly reported it as a result** —
cells cropped at their exact bounding box with the OCR detector still running over them, which clips
text that a padded crop reads fine. The corrected run is the one tabulated above.

---

## 4. Surya 2 — the best reader, and unusable

Architecturally different: a single VLM served through **vllm (CUDA-only) or llama.cpp**, so on Apple
Silicon it spawns a `llama-server` process. `brew install llama.cpp` was required to evaluate it.

| Page | Time | Printed digits | Handwritten | Tokens | Structure |
| --- | --- | --- | --- | --- | --- |
| Agreement prose | 94 s | **1.00** | — | **1.00** | — |
| FIDIC contents | 317 s | **1.00** | — | **1.00** | — |
| Price-adjustment | 42 s | 0.75 | — | **1.00** | — |
| **Priced BOQ** | 36 s | **0.857** | **3 / 10** | **1.00** | **HTML** |
| **IPC register** | 106 s | **0.857** | — | 0.778 | **HTML** |

It is the strongest reader in the whole investigation. It **does not hallucinate** on the agreement
page, where GOT does. And it is **the only engine that read the IPC payment value `87704866` without
corrupting it** — the tenfold error RapidOCR produces.

**Its HTML is real structure**, 11 `<tr>` and 64 `<td>` with `<thead>`, `<tbody>` and `colspan`:

```html
<tr><td>a)</td><td>Upto 3000 km run</td><td>Per Month</td><td>138</td> …
```

`Item │ Description │ Unit │ Quantity` recovered as one row — the first time any engine has done that
on this page. But the **handwritten money columns are offset by one row**: the rate misread as
`31,000.00` lands in the `120000` row rather than the `138` row. So printed cells are grouped
correctly and handwritten cells are misaligned.

**And it is non-deterministic.** The FIDIC contents page produced **different output on two identical
runs** (`77e7b2ae20dc` against `ef643341291c`). For a platform whose premise is that a finding can be
recomputed from stored evidence, an OCR stage that varies between runs is disqualifying on its own,
before licensing is even considered. 49× slower than RapidOCR compounds it.

---

## 5. Where this leaves the architecture

The proposed pipeline was:

```text
layout analysis → segmentation → OCR per region → cell reconstruction → validation
```

**The middle step does not hold up.** Per-region OCR was worse than whole-page OCR for both
recognisers tested, decisively so for the VLM. What actually recovered rows was a model that saw the
whole table at once and emitted structure directly.

So the honest shape suggested by the evidence is closer to:

```text
text layer?  ──yes──> existing extraction
     │no
     ▼
RapidOCR fast pass (printed text, discovery, deterministic)
     │
     ├── page has no table and no handwriting ──> use it
     └── table or handwriting present ──> whole-page structured reader, output as HTML/cells
                                          then arithmetic validation per row
```

with the structured reader **currently unavailable**: the one that works is licence-blocked and
non-deterministic, and the licence-clean ones do not solve the problem.

### The stop condition is not met

Material improvement was required in **both** exact financial digit recovery **and** table structure.

- **TATR** improves structure — genuinely, and cheaply, and with a clean licence — but recovers no
  money, because it is not an OCR model and the recogniser behind it cannot read handwriting.
- **GOT-OCR2** improves handwritten money on the full page (7/10 against 1/10) but destroys structure
  (an empty `\hline & & &` skeleton on the IPC), hallucinates on prose, and is 33× slower.
- **Surya 2** improves both, and is non-deterministic and licence-blocked.

**Recommendation: keep RapidOCR, adopt nothing.** No candidate clears both bars with an acceptable
licence and reproducible output.

### What would change the answer

1. **A handwriting-capable recogniser under a permissive licence.** This is the actual blocker — the
   gap between TATR's correct cell boundaries and a value nobody can read. TrOCR's handwritten
   checkpoints are worth checking on licence grounds specifically.
2. **A real building/RA-bill corpus**, where the priced tables are far more likely to be machine-typed
   than handwritten. Every conclusion above is drawn from a 2001 highway contract with handwritten
   rates; a modern RA bill may make the whole problem disappear, and optimising against this page
   would be optimising against the hardest possible case for reasons of availability rather than
   relevance.
3. **Docling and PP-Structure**, both licence-clean, not yet benchmarked here. Docling in particular is
   a full document-conversion pipeline with permissive models and is the most promising unexamined
   candidate.

### The financial safety rule holds, and was demonstrated

GOT-OCR2 misread `37,100.00` as `31,000.00`. That row fails its own arithmetic — 138 × 31,000 =
4,278,000, against a stated amount of 5,119,800 — so **the wrong value is detectable without knowing
the right one.** Arithmetic validation is not a nice-to-have layered over OCR; on this evidence it is
the only thing standing between a transcription and a false money fact.
