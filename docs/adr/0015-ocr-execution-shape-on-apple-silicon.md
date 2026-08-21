# 15. OCR runs on three CPU threads with a bounded ONNX pool, and CoreML is rejected

Date: 2026-08-21

## Status

Accepted, and every number below is measured rather than reasoned. Implemented in
`src/aedifex/extraction/ocr.py`: `OCR_WORKERS = 3`, `OCR_THREADS_PER_WORKER = 3`, ndarray input, and
`CPUExecutionProvider`. **CoreML is rejected on correctness first and speed second.**

## Context

OCR became necessary when the only public NHAI contract-with-BOQ and the only interim-payment record
turned out to be image-only — 523 scanned pages with no text layer between them. The first
implementation transcribed a page in about 2.3 seconds, which makes the 361-page contract agreement
roughly 14 minutes and puts it past the 900-second deadline the module enforces. Before touching
accuracy or the engine, the question was whether the existing engine was simply being run badly.

It was. Two things were wrong and both were invisible without measuring.

**ONNX Runtime was oversubscribing the machine.** `rapidocr-onnxruntime` 1.2.3 builds its session
options without setting `intra_op_num_threads` or `inter_op_num_threads`, so each session sizes its
pool to the core count. On this M4 that is ten threads for one page at a time, and the same run with
the pool capped at four threads is **10% faster while using 0.8 fewer cores**. There is no
configuration knob for this in that release and no environment variable either, because the macOS
arm64 wheel is not an OpenMP build.

**Every page was being encoded to PNG and immediately decoded again.** A 1.1 MB page JPEG was
inflated into a 7.6 MB PNG so that RapidOCR's loader could turn it back into the identical array. The
round trip is provably a no-op on pixels — the loader does `np.array(Image.open(BytesIO(b)))` for
bytes and returns an ndarray untouched — and it cost **12.6%** of wall clock.

## Decision

Three page workers, three ONNX threads each, ndarray input, `CPUExecutionProvider`.

Pages are transcribed concurrently in a thread pool; rendering stays serial because pypdf's reader is
not safe to share, and persistence stays serial in the caller. Results are keyed by page number and
reassembled in page order, so completion order cannot reorder anything.

### Measurements

20 pages drawn from the real corpus — prose, dense clauses, rotated bill-of-quantities tables, and
1-bit `CCITTFaxDecode` fax scans. M4, 4 performance + 6 efficiency cores, 16 GB.

| Configuration | s/page | pages/s | CPU | Peak RSS | Errors | Output |
| --- | --- | --- | --- | --- | --- | --- |
| **serial, ORT default, PNG** *(baseline)* | 2.31 | 0.43 | 4.39× | 1,528 MB | 0 | reference |
| serial, 4 ORT threads, PNG | 2.09 | 0.48 | 3.57× | 1,539 MB | 0 | identical |
| serial, 4 ORT threads, ndarray | 1.99 | 0.50 | 3.78× | 1,586 MB | 0 | identical |
| 2 threads × 2 ORT | 1.92 | 0.52 | 3.06× | 1,778 MB | 0 | identical |
| 4 threads × 1 ORT | 1.73 | 0.58 | 3.36× | 2,789 MB | 0 | identical |
| 2 threads × 4 ORT | 1.65 | 0.61 | 5.25× | 1,935 MB | 0 | identical |
| process, 2 × 4 ORT | 1.57 | 0.64 | 6.84× | ≥1,538 MB/worker | 0 | identical |
| 6 threads × 1 ORT | 1.55 | 0.65 | 4.58× | 3,216 MB | 0 | identical |
| 2 threads × 5 ORT | 1.54 | 0.65 | 6.47× | 1,900 MB | 0 | identical |
| process, 4 × 2 ORT | 1.43 | 0.70 | 6.39× | ≥1,339 MB/worker | 0 | identical |
| 3 threads × 3 ORT, PNG | 1.26–1.42 | 0.71–0.80 | 5.2× | 2,326 MB | 0 | identical |
| 4 threads × 2 ORT, ndarray | 1.24 | 0.81 | 4.82× | 2,697 MB | 0 | identical |
| **3 threads × 3 ORT, ndarray** *(chosen)* | **1.21–1.24** | **0.81–0.83** | 5.3× | 2,464 MB | 0 | identical |
| CoreML, serial, ndarray | 6.84 | 0.15 | 1.00× | **10,472 MB** | 0 | **WRONG** |
| CoreML, 3 threads × 3, ndarray | 6.40 | 0.16 | 1.24× | **10,531 MB** | 0 | **WRONG** |

Every CPU configuration returned a **byte-identical transcription and a byte-identical digest of just
the numerals** against the serial baseline. That was checked rather than assumed: RapidOCR's wrapper
could have carried mutable state across pages, and if it had, threads would have been unusable.

On the two real documents, end to end: **2.15× and 2.19×, output identical.**

### Why three workers and not more

CPU utilisation plateaus near 5× on a ten-core machine because six of those cores are efficiency
cores. `4 × 2` and `6 × 1` both came out slower than `3 × 3` despite having more workers — starving
each worker's inference costs more than the extra concurrency returns. Run-to-run variance is around
10%, so `3 × 3` and `4 × 2` are within noise of each other on throughput; `3 × 3` wins on memory
(2,464 MB against 2,697 MB), which is the documented tie-break.

### Why threads and not processes

Process pools measured no faster — 4 workers at 1.43 s/page against 1.24 for 3 threads — while each
worker loads its own copy of the models. The RSS figures for process mode in the table are the
largest single child rather than the sum, so they understate it: four workers is several GB for no
throughput gain. Threads share one engine.

## Why CoreML is rejected

Injected as `CoreMLExecutionProvider` ahead of CPU on the **same model files and same pages**, so the
comparison isolates the provider. Upgrading to RapidOCR 3.x, which exposes
`EngineConfig.onnxruntime.use_coreml` as configuration, would also change the models and confound it.

It fails on all four selection criteria:

- **Output is wrong.** 1,333 characters against 34,761 — it lost 96% of the text. Eight of twenty
  pages produced nothing at all. The contract page that CPU reads correctly came back as
  `"ONEHUNDREORUPEES e e e t."`, and **every one of `2,279,024,320`, `12,226,525.32`, `46.60` and
  `TNHP/7` was lost.**
- **It is 3.4× slower**, 6.84 s/page against 1.99 for the equivalent CPU run.
- **Memory is 6.6× higher** — 10.5 GB peak on a 16 GB machine, which is a stability problem, not just
  a cost.
- **It does not parallelise.** CPU utilisation stayed at 1.0–1.24×, so more workers bought nothing.

This is consistent with RapidOCR's own published finding that `CPUProvider` was faster on an M2 for
these models, and goes further: here it is also incorrect. The PP-OCR detection and recognition
models use dynamic shapes that the CoreML EP evidently handles badly, falling back per node.

**Re-open only with a different model set**, and only against a real document, with digests compared
rather than speed alone.

## Consequences

**The 361-page contract agreement now transcribes within the deadline** instead of being truncated by
it — roughly 7 minutes against 14.

**One reach into a third-party module.** `rapidocr_onnxruntime.utils.SessionOptions` is replaced to cap
the thread pool, because that release exposes no other way. It is guarded: if the attribute ever
moves, `_bound_ort_threads` raises rather than silently reverting to an unbounded pool and quietly
costing throughput nobody would think to re-measure.

**The deadline became approximate.** With workers in flight it is checked while waiting for
completions, so pages already running are allowed to finish rather than being killed mid-inference —
a half-transcribed page is not evidence, and a thread cannot be interrupted safely. The bound
therefore overshoots by at most about one page. Page and character bounds are exact, and the
character budget is spent **in page order** after aggregation, which is what makes the parallel result
identical to the serial one rather than merely similar.

**None of this changes what OCR output may be used for.** It is faster, not more trustworthy. Digits
transcribed from a scan still require validation before becoming money facts — a vertical cell rule
still reads as a trailing `1`, turning `87704866` into `877048661` — and a transcribed table still has
no rows. Speed was the problem being solved here; accuracy was not.
