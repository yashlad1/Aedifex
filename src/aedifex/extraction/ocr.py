"""Transcribing a scanned document, when there is no text layer to read.

OCR was speculative in this project until 2026-08-21, when it stopped being. The public NHAI
contract agreement for Package V-A on NH-2 — the one that names its Priced Bill of Quantities as a
contract document — is 361 scanned pages with no text layer, and the monthly IPC payment register
for package ABP-III, the only interim-payment evidence in the corpus, is two pages of 1-bit fax
scan. Neither can be read at all without this module, and both are directly required by payment
verification.

So this exists, and it is deliberately small.

**What it is not.** Not a document-understanding pipeline, not layout analysis, not table
reconstruction, not a queue, not a service. It turns page images into page text and stops.
Everything downstream — the notice reader, the BOQ reader, the rules — is unchanged and does not
know OCR happened, because :class:`DocumentText` is the same shape either way.

**Raw evidence is never touched.** The stored artifact is read, never rewritten. A tool like
``ocrmypdf`` that injects a text layer back into the PDF was rejected for exactly that reason: the
output would be a different file from the one whose digest is the document's identity.

**Transcription is interpretation, and is marked as such.** A value OCR read is not a value the
document's own text layer states — it is this engine's opinion about some pixels, and on money that
distinction is the whole ballgame. Every fact derived from this path carries the engine and its
version in its ``method``, so a reader can see that ``2,279,024,320`` was transcribed rather than
extracted, and can go and look at the page.

**Rendering needs no rasteriser.** Every scanned page in the observed corpus carries exactly one
full-page image XObject — ``DCTDecode`` (JPEG) for the contract, ``CCITTFaxDecode`` for the IPC
register — and ``pypdf`` with Pillow hands both over directly. That avoids poppler, avoids
Ghostscript, and avoids PyMuPDF, which this project rejected for being AGPL.

**Bounds are hard, because this is the slowest thing the pipeline does.** Roughly 2 seconds a page
for a clean A4 scan and 5 for a dense one, so the 361-page contract is half an hour. Page, character
and wall-clock budgets are all enforced, and OCR never runs unless a caller asks for it.
"""

from __future__ import annotations

import importlib
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Final, Protocol

from aedifex.errors import ExtractionError
from aedifex.extraction.pdftext import MAX_CHARS, DocumentText, PageText
from aedifex.infrastructure.observability.logging import get_logger

__all__ = [
    "OCR_ENGINE",
    "OCR_MAX_PAGES",
    "OCR_MAX_SECONDS",
    "OCR_THREADS_PER_WORKER",
    "OCR_WORKERS",
    "OcrEngine",
    "OcrUnavailableError",
    "ocr_document",
    "ocr_method",
]

_log = get_logger(__name__)

# RapidOCR: Apache-2.0, pip-installable, no system binary, ONNX models bundled in the wheel.
#
# Chosen over Tesseract for one operational reason rather than an accuracy one — Tesseract needs a
# system package, which means every developer machine, every container and CI all have to grow one,
# and this milestone was scoped to "enough OCR to read one project". Measured on the two documents
# that forced the decision: every figure that matters on the Package V-A agreement page came out
# exactly right, including ``2,279,024,320.00``, ``12,226,525.32`` and the ``46.60`` exchange rate,
# and the rotated bitonal IPC register transcribed without needing to be straightened first.
#
# It is not perfect and the limits are recorded rather than found later: it drops the occasional
# line, mangles handwriting ("made the 27th" became "madu the27flday"), and its reading order across
# a wide table is approximate. None of that is a reason to prefer an engine nobody can install.
OCR_ENGINE: Final[str] = "rapidocr-onnxruntime"

# Far below pdftext's 500. A scan costs seconds a page rather than milliseconds, and a caller that
# genuinely wants 361 pages should have to say so.
OCR_MAX_PAGES: Final[int] = 40

# Wall clock. The bound that actually protects an operator: page count alone does not, because one
# pathological image can take far longer than the rest of the document.
OCR_MAX_SECONDS: Final[float] = 900.0

# Pages transcribed concurrently, and ONNX Runtime's intra-op threads per worker. Both measured on
# an M4 (4 performance + 6 efficiency cores, 16 GB) over a 20-page sample drawn from the real
# corpus — prose, dense clauses, rotated bill-of-quantities tables and 1-bit fax scans:
#
#   serial, ORT default threads   2.31 s/page   baseline, and already oversubscribed
#   serial, 4 ORT threads         2.09 s/page   bounding ORT alone is worth 10%
#   3 workers x 3 ORT threads     1.42 s/page   best of nine parallel shapes tried
#   3 workers x 3, ndarray input  1.24 s/page   dropping the PNG round trip, a further 12.6%
#
# Three, not more. CPU utilisation plateaus near 5x on this machine because six of the ten cores
# are efficiency cores, so 4x2 and 6x1 both came out slower than 3x3 despite more workers. Threads
# rather than processes: process pools measured no faster (4 workers, 1.43 s/page) while each worker
# loads its own ~1.4 GB of models, and threads share one engine.
#
# Every parallel configuration produced a byte-identical transcription and a byte-identical digest
# of just the numerals, against the serial baseline. That was checked rather than assumed, because
# RapidOCR's wrapper could have carried mutable state across pages, and it is the reason threads
# are acceptable here at all.
OCR_WORKERS: Final[int] = 3
OCR_THREADS_PER_WORKER: Final[int] = 3

# The bound that stops a *native crash*, which is a different problem from the three above.
#
# RapidOCR segfaulted the whole process on one real page — the 600 DPI Hostel 19 bid-opening notice,
# 4964 x 7020 — while the same page resized to 4959 x 7012 read fine. Same pixel count to within
# 0.2%, same dtype, both C-contiguous: the trigger is the exact dimensions, somewhere in native code
# below Python, and **no ``except`` can catch it**. The page, char and time budgets are all useless
# against it because the process dies mid-page and takes the run with it.
#
# So the dimensions handed to the engine are made predictable instead. 12 MP sits above 300 DPI A4
# (8.7 MP), which is the standard for document scanning, and is a no-op for the entire existing
# corpus: every page already stored is at most 3.8 MP with a longest side of 2336 px, so nothing
# previously transcribed changes and no stored fact stops being reproducible. That was checked
# rather than assumed, because silently re-scaling old evidence would break exactly the guarantee
# this project sells.
#
# It costs no accuracy on the page that forced it: transcribed at every scale from 2.2 MP to 28 MP,
# the text came back as the same 1030-1046 characters of identical content.
#
# Honest about what this is: it reduces an unpredictable native crash to a bounded input. It does
# not make the engine crash-proof. If one recurs below this bound, the escalation is to run the
# engine in a separate process — and that is a bigger change than it looks, because ADR 0015 chose
# threads over processes on measured throughput.
OCR_MAX_PIXELS: Final[int] = 12_000_000


class OcrUnavailableError(ExtractionError):
    """Raised when OCR was asked for and its dependencies are not installed.

    Its own type because the remedy is specific and worth saying out loud — ``pip install
    'aedifex[ocr]'`` — rather than being buried in a generic extraction failure.
    """


class OcrEngine(Protocol):
    """The one thing this module needs from an OCR engine: image bytes in, text out.

    A Protocol so a test can pass a stub and never load a 15 MB ONNX model, and so replacing the
    engine later is a new implementation rather than a change to this module.
    """

    @property
    def name(self) -> str:
        """Engine identifier, recorded on every fact derived from its output."""
        ...

    @property
    def version(self) -> str:
        """Engine version, recorded alongside the name. Reproducibility needs both."""
        ...

    def read(self, image: bytes) -> str:
        """Transcribe one page image. Returns the empty string for a page it cannot read."""
        ...


def ocr_method(engine: OcrEngine) -> str:
    """How an OCR-derived fact records where it came from, e.g. ``ocr:rapidocr-onnxruntime/1.4.4``.

    Prefixed ``ocr:`` on purpose. Anything reading a fact's ``method`` can tell at a glance that the
    value was transcribed from pixels rather than read from a text layer, without knowing the name
    of any particular engine.
    """
    return f"ocr:{engine.name}/{engine.version}"


@dataclass(frozen=True, slots=True)
class _RapidOcr:
    """The default engine, loaded lazily so importing this module costs nothing."""

    _engine: Any
    version: str

    @property
    def name(self) -> str:
        return OCR_ENGINE

    def read(self, image: bytes) -> str:
        # RapidOCR returns (boxes, elapsed); each box is (quad, text, confidence). Joined in the
        # order returned, which is the engine's reading order and is approximate on a wide table.
        # Deliberately not re-sorted here: inventing a reading order would be layout analysis, and
        # a wrong one is harder to argue with than an admitted approximation.
        try:
            boxes, _ = self._engine(_as_rgb_array(image))
        except Exception as error:
            _log.warning("ocr.page_failed", error=str(error), engine=self.name)
            return ""
        if not boxes:
            return ""
        return " ".join(str(box[1]) for box in boxes if len(box) > 1 and box[1])


def _bound_ort_threads(threads: int) -> None:
    """Cap ONNX Runtime's intra-op thread pool before any session is built.

    rapidocr-onnxruntime 1.2.3 sets neither ``intra_op_num_threads`` nor ``inter_op_num_threads``,
    so each session sizes its pool to the machine's core count. That is already 10% slower than a
    bounded pool even on a single-threaded run, and with several page workers it becomes N x 10
    threads competing for 10 cores.

    There is no configuration knob for this in that release and no environment variable either — ORT
    on macOS arm64 is not an OpenMP build, so ``OMP_NUM_THREADS`` does nothing. So the one name the
    library calls is replaced. That is a reach into somebody else's module and it is deliberately
    loud about it: if the attribute ever moves, this raises instead of silently reverting to an
    unbounded pool and quietly costing throughput nobody would think to re-measure.
    """
    import rapidocr_onnxruntime.utils as internals

    original = getattr(internals, "SessionOptions", None)
    if original is None:  # pragma: no cover - guards a dependency upgrade
        raise OcrUnavailableError(
            "rapidocr_onnxruntime.utils.SessionOptions is gone, so ONNX Runtime's thread pool can "
            "no longer be bounded here. Check whether the installed release exposes a thread "
            "setting of its own before removing this."
        )
    if getattr(original, "_aedifex_bounded", False):
        return

    def bounded():  # type: ignore[no-untyped-def]
        options = original()
        options.log_severity_level = 4
        options.intra_op_num_threads = threads
        return options

    bounded._aedifex_bounded = True  # type: ignore[attr-defined]
    internals.SessionOptions = bounded


def _as_rgb_array(image: bytes, *, max_pixels: int = OCR_MAX_PIXELS) -> Any:
    """Decode a page image to the 8-bit RGB array the engine wants, with no PNG in between.

    The earlier implementation encoded a PNG and handed over the bytes, which RapidOCR then decoded
    with ``np.array(Image.open(BytesIO(...)))``. Handing it the array directly is **provably** the
    same pixels rather than merely measured to be — its loader returns an ndarray untouched — and it
    is worth 12.6% of wall clock, measured with the call order alternated. A 1.1 MB page JPEG was
    being inflated into a 7.6 MB PNG only to be thrown away.

    The conversion to RGB is the part that matters and is not optional: ``CCITTFaxDecode`` fax scans
    arrive as 1-bit TIFFs and OpenCV inside RapidOCR rejects them outright — "Unsupported depth of
    input image ... 'depth' is 9 (CV_Bool)". Every page of the IPC payment register failed silently
    to the empty string before this existed.

    Oversized pages are downscaled to ``max_pixels``, keeping the aspect ratio. See
    ``OCR_MAX_PIXELS`` for why: one real page crashed the process outright, and the trigger was its
    exact dimensions rather than anything a caller could inspect beforehand.
    """
    import numpy
    from PIL import Image

    try:
        with Image.open(io.BytesIO(image)) as opened:
            converted = opened.convert("RGB")
            pixels = converted.width * converted.height
            if pixels > max_pixels:
                # sqrt because the budget is on area and the scale applies to both sides.
                scale = (max_pixels / pixels) ** 0.5
                width = max(1, int(converted.width * scale))
                height = max(1, int(converted.height * scale))
                _log.info(
                    "ocr.page_downscaled",
                    reason="page exceeds the pixel budget",
                    original=f"{converted.width}x{converted.height}",
                    scaled=f"{width}x{height}",
                    max_pixels=max_pixels,
                )
                converted = converted.resize((width, height), Image.Resampling.LANCZOS)
            return numpy.array(converted)
    except Exception as error:
        _log.warning("ocr.image_decode_failed", error=str(error))
        return numpy.zeros((1, 1, 3), dtype=numpy.uint8)


def default_engine(threads_per_worker: int = OCR_THREADS_PER_WORKER) -> OcrEngine:
    """Load the default OCR engine, or explain precisely what is missing.

    Args:
        threads_per_worker: ONNX Runtime intra-op threads. Bounded before the first session is
            built, because the library leaves it at the core count and that costs throughput as soon
            as more than one page is in flight.

    Raises:
        OcrUnavailableError: when the optional dependencies are not installed.
    """
    try:
        module = importlib.import_module("rapidocr_onnxruntime")
    except ImportError as error:
        raise OcrUnavailableError(
            "OCR was requested but rapidocr-onnxruntime is not installed. "
            "Install the optional extra: pip install 'aedifex[ocr]'"
        ) from error
    try:
        importlib.import_module("PIL")
    except ImportError as error:
        raise OcrUnavailableError(
            "OCR was requested but Pillow is not installed, so page images cannot be decoded. "
            "Install the optional extra: pip install 'aedifex[ocr]'"
        ) from error
    # From package metadata, not from a module attribute: rapidocr_onnxruntime exposes no
    # __version__, so getattr returned the string "unknown" and every OCR-derived fact recorded
    # "ocr:rapidocr-onnxruntime/unknown" as its provenance. A version nobody can pin is not a
    # reproducibility record.
    try:
        version = metadata.version("rapidocr-onnxruntime")
    except metadata.PackageNotFoundError:  # pragma: no cover - installed by definition here
        version = "unknown"
    _bound_ort_threads(threads_per_worker)
    return _RapidOcr(_engine=module.RapidOCR(), version=version)


def _page_images(data: bytes, max_pages: int) -> tuple[list[tuple[int, bytes]], int]:
    """The largest embedded image on each of the first ``max_pages`` pages, and the page count.

    Returns the document's *full* page count alongside the images, not the number of images found.
    Without it the caller cannot tell a complete read from one the page budget stopped, because the
    list it gets back is already truncated — which is exactly the bug the bounds test caught.

    "Largest" rather than "only", because a scanned page occasionally carries a logo or a scanner
    artifact alongside the page itself, and the page is always the big one. Pages with no image at
    all are skipped rather than called failures — a scanned document commonly ends with a blank.
    """
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - pypdf is a hard dependency
        raise OcrUnavailableError(f"pypdf is required to read page images: {error}") from error

    try:
        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
    except Exception as error:
        raise ExtractionError(f"PDF could not be opened for OCR: {error}") from error

    found: list[tuple[int, bytes]] = []
    for index in range(min(page_count, max_pages)):
        try:
            images = list(reader.pages[index].images)
        except Exception as error:
            _log.warning("ocr.page_images_failed", page=index + 1, error=str(error))
            continue
        if not images:
            continue
        largest = max(images, key=lambda image: len(image.data))
        found.append((index + 1, largest.data))
    return found, page_count


def ocr_document(
    data: bytes,
    *,
    engine: OcrEngine | None = None,
    max_pages: int = OCR_MAX_PAGES,
    max_chars: int = MAX_CHARS,
    max_seconds: float = OCR_MAX_SECONDS,
    workers: int = OCR_WORKERS,
) -> DocumentText:
    """Transcribe a scanned PDF into the same shape :func:`extract_text` returns.

    Args:
        data: The raw PDF bytes, exactly as stored. Never modified.
        engine: The OCR engine. Defaults to loading :data:`OCR_ENGINE`, which is where the optional
            dependency is actually required — passing a stub needs nothing installed.
        max_pages: Stop after this many pages.
        max_chars: Stop once this much text has been transcribed.
        max_seconds: Stop once this much wall clock has been spent. With several workers the
            deadline is checked while waiting for completions, so pages already in flight finish and
            the bound is approximate to the length of one page rather than exact.
        workers: Pages transcribed concurrently. 1 runs the serial path.

    Returns:
        A :class:`DocumentText` whose ``truncated`` flag is set if *any* bound stopped it early. A
        caller must read that flag: a value absent from a truncated transcription is not a value the
        document lacks.

    Raises:
        OcrUnavailableError: if OCR dependencies are missing and no engine was supplied.
        ExtractionError: if the PDF cannot be opened at all.
    """
    reader = engine if engine is not None else default_engine()
    images, page_count = _page_images(data, max_pages)
    if not images:
        return DocumentText(pages=(), page_count=0, truncated=False)

    started = time.monotonic()
    deadline = started + max_seconds
    transcribed: dict[int, str] = {}
    abandoned = 0
    deadline_hit = False

    # Pages are independent, so they are transcribed concurrently — but *only* the transcription is.
    # Rendering already happened serially above (pypdf's reader is not safe to share), and
    # persistence happens serially in the caller. Results are keyed by page number and reassembled
    # in page order below, so completion order cannot reorder anything and one page's failure cannot
    # touch another's text.
    if workers > 1 and len(images) > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ocr") as pool:
            futures = {pool.submit(reader.read, image): number for number, image in images}
            try:
                for future in as_completed(futures, timeout=max(deadline - time.monotonic(), 0.0)):
                    transcribed[futures[future]] = future.result()
            except FuturesTimeout:
                deadline_hit = True
                # Cancel what has not started. Pages already running are left to finish rather than
                # killed mid-inference: a half-transcribed page is not evidence, and a thread cannot
                # be interrupted safely anyway.
                for future, number in futures.items():
                    if future.cancel():
                        abandoned += 1
                    elif future.done():
                        transcribed.setdefault(number, future.result())
                _log.warning(
                    "ocr.time_budget_exhausted",
                    pages_done=len(transcribed),
                    pages_available=len(images),
                    pages_abandoned=abandoned,
                    seconds=round(time.monotonic() - started, 1),
                )
    else:
        for number, image in images:
            if time.monotonic() >= deadline:
                deadline_hit = True
                abandoned = len(images) - len(transcribed)
                _log.warning(
                    "ocr.time_budget_exhausted",
                    pages_done=len(transcribed),
                    pages_available=len(images),
                    pages_abandoned=abandoned,
                    seconds=round(time.monotonic() - started, 1),
                )
                break
            transcribed[number] = reader.read(image)

    # Ordered aggregation, and the character budget applied in page order — which is what makes the
    # parallel result identical to the serial one rather than merely similar. Spending the budget in
    # completion order would keep a different set of pages on every run.
    pages: list[PageText] = []
    budget = max_chars
    # Recorded from the deadline actually firing, not inferred from a page count. If the clock ran
    # out and every page happened to be collected anyway, nothing was lost and the result is whole;
    # if it ran out and pages were dropped, a caller must not read their absence as the document
    # lacking those values.
    truncated = deadline_hit and abandoned > 0
    for number, _ in images:
        if number not in transcribed:
            continue
        if budget <= 0:
            truncated = True
            break
        text = transcribed[number]
        if len(text) > budget:
            text = text[:budget]
            truncated = True
        budget -= len(text)
        pages.append(PageText(number=number, text=text))

    _log.info(
        "ocr.completed",
        engine=reader.name,
        engine_version=reader.version,
        pages_read=len(pages),
        characters=max_chars - budget,
        seconds=round(time.monotonic() - started, 1),
        truncated=truncated,
    )
    # page_count is what the transcription covers, not the document's length: OCR was bounded, and
    # reporting the full page count here would make a partial read look complete. `truncated`
    # compares against the *document*, not against the already-truncated image list — getting that
    # wrong meant a page-budget stop was reported as a complete read.
    return DocumentText(
        pages=tuple(pages),
        page_count=len(pages),
        truncated=truncated or page_count > len(pages),
    )
