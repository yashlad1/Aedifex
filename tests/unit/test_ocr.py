"""The bounds on OCR, which is the slowest thing the pipeline does.

Tested here and not elsewhere because resource limits are the one thing about this module that a
reader cannot verify by reading it: whether the page, character and wall-clock budgets *actually*
stop the loop is a question about behaviour. A 361-page scan is roughly half an hour of CPU, so a
budget that silently fails to bind is not a cosmetic defect.

Every test drives a stub engine through the :class:`OcrEngine` protocol, which is why none of them
loads an ONNX model or needs the optional extra installed. That is what the protocol is for.
"""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass, field
from typing import Any, Final

import pypdf
import pytest
from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject

from aedifex.errors import ExtractionError
from aedifex.extraction.ocr import (
    OCR_MAX_PIXELS,
    _as_rgb_array,
    ocr_document,
    ocr_method,
)


@dataclass
class StubEngine:
    """An engine that returns fixed text and counts how often it was asked."""

    text: str = "TRANSCRIBED"
    delay: float = 0.0
    calls: list[bytes] = field(default_factory=list)
    name: str = "stub-ocr"
    version: str = "9.9.9"

    def read(self, image: bytes) -> str:
        self.calls.append(image)
        if self.delay:
            time.sleep(self.delay)
        return self.text


class TestBounds:
    def test_page_budget_stops_the_loop(self) -> None:
        """``max_pages`` must bind before the document ends, and say so."""
        engine = StubEngine()
        data = _real_scan_bytes(6)
        result = ocr_document(data, engine=engine, max_pages=2)

        assert len(engine.calls) == 2, "the engine was asked to read more pages than allowed"
        assert result.pages_read == 2
        assert result.truncated is True, "a bounded read that stopped early must say it stopped"

    def test_character_budget_truncates_and_is_reported(self) -> None:
        """A page is cut mid-text rather than dropped, and ``truncated`` is set."""
        engine = StubEngine(text="X" * 100)
        result = ocr_document(_real_scan_bytes(3), engine=engine, max_chars=150)

        transcribed = sum(len(page.text) for page in result.pages)
        assert transcribed == 150
        assert result.truncated is True

    def test_time_budget_stops_between_pages(self) -> None:
        """Wall clock binds even when the page count would allow more.

        The bound that actually protects an operator: one pathological image can cost more than the
        rest of a document put together, so a page count alone is not a time limit.
        """
        engine = StubEngine(delay=0.05)
        result = ocr_document(_real_scan_bytes(20), engine=engine, max_seconds=0.12)

        assert len(engine.calls) < 20, "the time budget did not stop the loop"
        assert result.truncated is True

    def test_no_pages_is_not_an_error(self) -> None:
        """A PDF with no images transcribes to nothing, which is a result and not a failure."""
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)

        result = ocr_document(buffer.getvalue(), engine=StubEngine())
        assert result.pages == ()
        assert result.truncated is False

    def test_unopenable_pdf_raises(self) -> None:
        with pytest.raises(ExtractionError, match="could not be opened"):
            ocr_document(b"this is not a PDF", engine=StubEngine())


class TestPixelBudget:
    """Regression guard for a crash, not a wrong answer.

    A real 600 DPI page (4964 x 7020) segfaulted the process inside the engine's native code, where
    no ``except`` reaches and the page, char and time budgets are all irrelevant because the process
    dies mid-page. Resized to 4959 x 7012 the same page read fine, so the trigger was the exact
    dimensions. These pin the bound that makes the dimensions predictable.
    """

    def test_an_oversized_page_is_downscaled_within_the_budget(self) -> None:
        image_module = pytest.importorskip("PIL.Image", reason="Pillow ships with the ocr extra")
        oversized = _jpeg_bytes(image_module, 4964, 7020)

        array = _as_rgb_array(oversized)

        height, width, channels = array.shape
        assert width * height <= OCR_MAX_PIXELS
        assert channels == 3
        # Aspect ratio survives, so nothing is stretched into unreadability.
        assert abs((width / height) - (4964 / 7020)) < 0.01

    def test_a_page_within_the_budget_is_untouched(self) -> None:
        """The whole existing corpus is well under the bound; none of it may be re-scaled.

        Every page already stored is at most 3.8 MP. If the bound moved them, every transcription
        taken before it existed would stop being reproducible.
        """
        image_module = pytest.importorskip("PIL.Image", reason="Pillow ships with the ocr extra")

        array = _as_rgb_array(_jpeg_bytes(image_module, 1646, 2331))

        assert array.shape == (2331, 1646, 3)


def _jpeg_bytes(image_module: Any, width: int, height: int) -> bytes:
    """A plain grey JPEG of exactly the requested dimensions.

    Grey rather than white so the encoder cannot collapse it to something degenerate, and JPEG
    rather than PNG because that is what the scanners in the corpus actually embed.
    """
    buffer = io.BytesIO()
    image_module.new("RGB", (width, height), (128, 128, 128)).save(buffer, format="JPEG")
    return buffer.getvalue()


class TestParallelism:
    """The property that makes bounded page-level threading acceptable at all."""

    def test_parallel_output_is_identical_to_serial(self) -> None:
        """Same pages, same order, same text — whatever order the workers finish in.

        Measured on the real corpus too, where every parallel shape returned a byte-identical
        transcription and a byte-identical digest of just the numerals. This pins it.
        """
        data = _real_scan_bytes(9)
        serial = ocr_document(data, engine=StubEngine(), workers=1, max_pages=9)
        parallel = ocr_document(data, engine=StubEngine(), workers=3, max_pages=9)

        assert [(p.number, p.text) for p in parallel.pages] == [
            (p.number, p.text) for p in serial.pages
        ]

    def test_completion_order_does_not_reorder_pages(self) -> None:
        """A slow early page must not end up after a fast later one."""

        @dataclass
        class Uneven:
            calls: list[bytes] = field(default_factory=list)
            name: str = "uneven"
            version: str = "1"

            def read(self, image: bytes) -> str:
                # First page submitted sleeps longest, so completion order is reversed.
                index = len(self.calls)
                self.calls.append(image)
                time.sleep(max(0.05 - index * 0.01, 0.0))
                return f"page-{index}"

        result = ocr_document(_real_scan_bytes(4), engine=Uneven(), workers=4, max_pages=4)
        assert [p.number for p in result.pages] == [1, 2, 3, 4]

    def test_one_failing_page_does_not_affect_the_others(self) -> None:
        """A page the engine cannot read is empty; its neighbours are untouched."""

        @dataclass
        class SometimesBroken:
            seen: int = 0
            name: str = "flaky"
            version: str = "1"

            def read(self, image: bytes) -> str:
                self.seen += 1
                if self.seen == 2:
                    return ""
                return "OK"

        result = ocr_document(_real_scan_bytes(4), engine=SometimesBroken(), workers=2, max_pages=4)
        assert len(result.pages) == 4
        assert sum(1 for p in result.pages if p.text == "OK") == 3
        assert [p.number for p in result.pages] == [1, 2, 3, 4]


class TestProvenance:
    def test_pages_are_numbered_as_a_reader_would(self) -> None:
        """Page numbers are the PDF's, from 1 — a fact's citation is only as good as this."""
        result = ocr_document(_real_scan_bytes(3), engine=StubEngine(), max_pages=3)
        assert [page.number for page in result.pages] == [1, 2, 3]

    def test_method_records_engine_and_version(self) -> None:
        """Both, and prefixed, so a transcribed value is distinguishable from an extracted one."""
        assert ocr_method(StubEngine()) == "ocr:stub-ocr/9.9.9"

    def test_a_page_the_engine_cannot_read_is_empty_not_fatal(self) -> None:
        """One unreadable page must not cost the whole document."""
        result = ocr_document(_real_scan_bytes(3), engine=StubEngine(text=""), max_pages=3)
        assert result.pages_read == 3
        assert all(page.is_empty for page in result.pages)


# A minimal valid 8x8 grayscale JPEG, inline rather than generated with Pillow. The tests must run
# under `pip install -e '.[dev]'`, and Pillow lives in the optional `ocr` extra — a bounds test that
# only runs when OCR is installed would not be a guardrail.
_TINY_JPEG: Final[bytes] = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwcJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPDs0NDP/wAALCAAIAAgBAREA/8QAFQABAQAAAAAA"
    "AAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/"
    "xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX/9k="
)


def _real_scan_bytes(pages: int) -> bytes:
    """A PDF whose pages each carry one image XObject, which is the shape every real scan here has.

    Built through pypdf rather than hand-rolled, because what is under test is "how many pages did
    we hand to the engine", and that depends on pypdf discovering the images the same way it does on
    the 361-page contract scan.
    """
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=72, height=72)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/XObject"): DictionaryObject(
                    {NameObject("/Im0"): writer._add_object(_image_xobject(_TINY_JPEG))}
                )
            }
        )
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _image_xobject(jpeg: bytes) -> StreamObject:
    stream = StreamObject()
    stream.set_data(jpeg)
    stream[NameObject("/Type")] = NameObject("/XObject")
    stream[NameObject("/Subtype")] = NameObject("/Image")
    stream[NameObject("/Width")] = NumberObject(8)
    stream[NameObject("/Height")] = NumberObject(8)
    stream[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
    stream[NameObject("/BitsPerComponent")] = NumberObject(8)
    stream[NameObject("/Filter")] = NameObject("/DCTDecode")
    return stream
