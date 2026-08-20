"""Bounded PDF text extraction.

The one job here is to turn stored bytes into pages of text without letting a hostile or merely
broken PDF consume the process. A PDF is untrusted remote content in exactly the way a downloaded
body is, and it arrives having already passed the acquisition layer's size and type checks — which
say nothing about what happens when something tries to *parse* it.

So the limits are on this side of the parser:

* ``max_pages`` bounds the work. The largest document in the corpus is 247 pages; a PDF claiming
  five million is either broken or hostile, and either way we stop.
* ``max_chars`` bounds the output. Page count alone is not a bound, because one page can decompress
  to an unreasonable amount of text.
* every pypdf failure becomes :class:`~aedifex.errors.ExtractionError`. A parser that raises
  something the caller has never heard of is a parser that ends a batch run.

Deliberately *not* here, and recorded as known limitations rather than hidden: no OCR, so a scanned
PDF yields empty text and is reported as such rather than as a document with no fields; and no
process or memory isolation around the parser, which is the honest next hardening step for
untrusted-document handling but is not what this slice is proving.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from aedifex.errors import ExtractionError

__all__ = [
    "MAX_CHARS",
    "MAX_PAGES",
    "DocumentText",
    "PageText",
    "extract_text",
]

# Bounds chosen against the real corpus, not from theory: its largest document is 247 pages and its
# fullest page of text is a few thousand characters. These leave an order of magnitude of headroom
# and still refuse anything absurd.
MAX_PAGES: Final[int] = 500
MAX_CHARS: Final[int] = 4_000_000


@dataclass(frozen=True, slots=True)
class PageText:
    """The text of one page, numbered as a reader would number it (from 1)."""

    number: int
    text: str

    @property
    def is_empty(self) -> bool:
        """True when the page carries no text layer — typically a scan."""
        return not self.text.strip()


@dataclass(frozen=True, slots=True)
class DocumentText:
    """Text extracted from one document, with what was left out made explicit.

    ``truncated`` matters to anything reasoning over the result: a field that is absent from a
    truncated document is not a field the document lacks.
    """

    pages: tuple[PageText, ...]
    page_count: int
    truncated: bool

    @property
    def pages_read(self) -> int:
        return len(self.pages)

    @property
    def has_text_layer(self) -> bool:
        """Whether any page yielded text at all. False means a scan, and means OCR, not failure."""
        return any(not page.is_empty for page in self.pages)

    def page(self, number: int) -> PageText | None:
        for page in self.pages:
            if page.number == number:
                return page
        return None


def extract_text(
    data: bytes,
    *,
    max_pages: int = MAX_PAGES,
    max_chars: int = MAX_CHARS,
) -> DocumentText:
    """Extract text from ``data``, reading at most ``max_pages`` pages and ``max_chars`` characters.

    Args:
        data: The raw PDF bytes, as stored.
        max_pages: Stop after this many pages. A caller that only needs a notice's front matter
            should pass a small number rather than read a 247-page bid document.
        max_chars: Stop once this much text has accumulated.

    Raises:
        ExtractionError: if the PDF cannot be opened, or is encrypted and cannot be read.
    """
    if max_pages < 1 or max_chars < 1:
        raise ValueError(f"max_pages and max_chars must be positive, got {max_pages}, {max_chars}")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # An empty user password is common and readable; anything else is not ours to open.
            try:
                reader.decrypt("")
            except Exception as error:
                raise ExtractionError(f"PDF is encrypted and could not be read: {error}") from error
        page_count = len(reader.pages)
    except ExtractionError:
        raise
    except (PyPdfError, OSError, ValueError, RecursionError) as error:
        raise ExtractionError(
            f"PDF could not be opened: {type(error).__name__}: {error}"
        ) from error

    pages: list[PageText] = []
    budget = max_chars
    truncated = page_count > max_pages
    for index in range(min(page_count, max_pages)):
        if budget <= 0:
            truncated = True
            break
        try:
            text = reader.pages[index].extract_text() or ""
        except Exception:
            # A single malformed page is recorded as empty rather than fatal: the fields this
            # pipeline wants are usually on page 1, and losing a whole notice to a broken page 200
            # would be the wrong trade.
            text = ""
        if len(text) > budget:
            text = text[:budget]
            truncated = True
        budget -= len(text)
        pages.append(PageText(number=index + 1, text=text))

    return DocumentText(pages=tuple(pages), page_count=page_count, truncated=truncated)
