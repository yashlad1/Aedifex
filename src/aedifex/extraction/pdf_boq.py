"""Reading a priced bill of quantities out of a PDF's text layer.

Written against a real document, not a template: pages 164-171 of an NHAI bid document already in
this corpus, which holds a 31-row priced BOQ totalling ₹8.46 crore. Before this existed the pipeline
extracted four tender-notice fields from that document and nothing else — the entire bill was
invisible.

The layout is not a grid once a PDF has been flattened to text. Each row arrives as::

    3                                   <- item number, alone on a line
    Construction of un-reinforced M-40  <- description, over a dozen or more lines
    ...
    Cum                                 <- unit, alone on a line
    3,150.00                            <- quantity
    5,270.00                            <- rate
    1,66,00,500.00                      <- amount

so parsing is positional *within an item block*, anchored on lines holding nothing but an item
number. The header is no help: it arrives split across eight fragments — ``Sr``, ``No.``,
``Description Unit``, ``Quantity``, ``Rate per``, ``unit``, ``Amount (In``, ``Rs)`` — with two
column names merged onto one line, and it appears on the first page only. Continuation pages have no
header at all.

**Every row is checked arithmetically before it is emitted.** ``quantity x rate`` must reproduce the
stated amount, and a row that fails is reported rather than returned. That single rule is what makes
positional parsing of a flattened table safe: a misread row almost never satisfies it. On the real
document it rejected the grand-total row, which had been parsed as "item 34" with a quantity of
512,711.86 — a plausible-looking line item whose real identity is the ₹8.46 crore total.

Deliberately narrow. This reads the layout in front of it and refuses everything else; it is not a
general PDF table framework, and the next real document is expected to need changes here rather than
to fit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from aedifex.domain.evidence import FactKind
from aedifex.extraction.pdftext import DocumentText
from aedifex.extraction.spreadsheet import (
    CURRENCY_INR,
    FIELD_CONTRACT_RATE,
    FIELD_CONTRACTED_QUANTITY,
    FIELD_ITEM_DESCRIPTION,
    FIELD_ITEM_IDENTIFIER,
)

__all__ = [
    "FIELD_LINE_AMOUNT",
    "BoqRow",
    "PdfBoq",
    "read_pdf_boq",
]

FIELD_LINE_AMOUNT: Final[str] = "line_amount"

# Where a priced bill of quantities begins. Matched on a page of its own rather than anywhere the
# phrase appears: a bid document mentions "BOQ" on twenty pages and prices it on eight.
_BOQ_HEADING: Final[re.Pattern[str]] = re.compile(
    r"Bill\s+of\s+Quantities\s*\(BOQ\)|Priced\s+Bill\s+of\s+Quantit", re.IGNORECASE
)

# Units as this corpus spells them. Recorded exactly as written and never converted — Cum and m3 may
# mean the same thing to an engineer, and asserting that is a judgement this module has no business
# making.
_UNIT: Final[re.Pattern[str]] = re.compile(
    r"^(?:Cum|Sqm|Sqmt|Rmt?|Km|MT|Nos?|Each|Kg|Quintal|Tonne|Ltr|Litre|Set|Job|LS)$",
    re.IGNORECASE,
)

# An item row starts either with the number alone on a line, or -- when the description is short
# enough to fit on one line -- with the number, the description and even the unit run together:
#
#     12 RCC Drain 1.0 metre x 1.0 metre on both sides Rm
#
# Reading only lone numbers missed three rows on the real document *and*, worse, gave item 11 item
# 12's quantity and rate: the block for 11 ran to the next lone number and the last three figures in
# it were 12's. The arithmetic check could not catch that, because 12's figures are internally
# consistent -- they simply belong to another item.
_ITEM_NUMBER: Final[re.Pattern[str]] = re.compile(r"^(\d{1,3})(?:\s+(\S.*))?$")

# Column headers, which the flattened text splits into fragments: "Rate per" / "unit" and "Quantity"
# on separate lines. Used to tell the priced table from a mention of it.
_RATE_HEADER: Final[re.Pattern[str]] = re.compile(r"^\s*Rate(\s+per)?\s*$", re.MULTILINE)
_QUANTITY_HEADER: Final[re.Pattern[str]] = re.compile(r"^\s*Quantity\s*$", re.MULTILINE)
_MONEY_LINE: Final[re.Pattern[str]] = re.compile(r"^[\d,]+\.\d{2}$")

# A page marker such as "VII-5" sits at the top of every page in this volume.
_PAGE_MARKER: Final[re.Pattern[str]] = re.compile(r"^[IVXL]+-\d+$")

# Rows whose stated amount disagrees with quantity x rate by more than this are refused. Relative,
# with an absolute floor, because the real document rounds: two of its rows are out by ₹10-13 on
# figures near ₹9,000,000, which is a rounding artefact rather than a parse error. The grand-total
# row it needs to reject is out by a factor of four.
_RELATIVE_TOLERANCE: Final[Decimal] = Decimal("0.0005")
_ABSOLUTE_TOLERANCE: Final[Decimal] = Decimal("100")

# Description lines longer than this are almost certainly prose that has run past the table.
_MAX_DESCRIPTION_LINES: Final[int] = 40


@dataclass(frozen=True, slots=True)
class BoqRow:
    """One priced line item, and the page it was read from."""

    item_identifier: str
    description: str
    unit: str | None
    quantity: Decimal
    rate: Decimal
    amount: Decimal
    page: int
    order: int
    """Position within the bill, used as the row locator in place of a spreadsheet cell."""


@dataclass(frozen=True, slots=True)
class PdfBoq:
    """What one document's priced bill of quantities yielded."""

    rows: tuple[BoqRow, ...]
    first_page: int | None
    rejected: tuple[str, ...]
    """Rows that failed the arithmetic check, with the numbers, so nothing is silently dropped."""

    @property
    def total_amount(self) -> Decimal:
        return sum((row.amount for row in self.rows), Decimal(0))


def _to_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "").strip())
    except InvalidOperation:
        return None


def _agrees(quantity: Decimal, rate: Decimal, amount: Decimal) -> bool:
    """Whether ``quantity x rate`` reproduces the stated amount within tolerance."""
    expected = quantity * rate
    difference = abs(expected - amount)
    allowed = max(_ABSOLUTE_TOLERANCE, abs(amount) * _RELATIVE_TOLERANCE)
    return difference <= allowed


def _find_table_page(document: DocumentText) -> int | None:
    """The page where the priced table actually starts, not where it is first mentioned.

    A bid document names its bill of quantities in the contents and cites it throughout — twenty
    pages on the observed document — and prices it on eight. Anchoring on the first mention started
    the scan 138 pages early, and that mattered: the item sequence was consumed by lines beginning
    "1" and "2" in unrelated prose, so the real items 1 and 2 no longer continued the run and were
    dropped.

    So the heading alone is not enough. The page must also carry the column headers, which arrive as
    separate fragments after the PDF is flattened.
    """
    for page in document.pages:
        if not _BOQ_HEADING.search(page.text):
            continue
        text = page.text
        if _RATE_HEADER.search(text) and _QUANTITY_HEADER.search(text):
            return page.number
    return None


def _sequential_item_starts(numbered: list[tuple[int, str]]) -> list[int]:
    """Line indexes where an item begins, accepted only in strict numeric sequence.

    Sequence is the discriminator, and it has to be: a description legitimately begins with a number
    -- "12 mm cement plaster finished with a floating coat" sits inside item 27 -- so any line
    starting with an integer is a candidate and most are not items. A bill of quantities numbers its
    items 1, 2, 3 without skipping, so a candidate is an item only if it continues the run.

    Deterministic, and it degrades honestly: a genuinely absent number stalls the sequence and the
    rows after it are left out rather than misattributed, which is the safer of the two failures.
    """
    starts: list[int] = []
    expected = 1
    for index, (_, line) in enumerate(numbered):
        match = _ITEM_NUMBER.match(line)
        if match is None:
            continue
        if int(match.group(1)) != expected:
            continue
        starts.append(index)
        expected += 1
    return starts


def read_pdf_boq(document: DocumentText) -> PdfBoq:
    """Extract priced line items from a bill of quantities in ``document``.

    Returns empty rows when the document contains no priced BOQ, which is the common case — most
    documents are not bills of quantities, and saying so is cheaper than guessing.
    """
    start_page = _find_table_page(document)
    if start_page is None:
        return PdfBoq(rows=(), first_page=None, rejected=())

    # Lines from the heading onwards, remembering which page each came from so a fact can cite one.
    numbered: list[tuple[int, str]] = []
    for sheet in document.pages:
        if sheet.number < start_page:
            continue
        for raw in sheet.text.splitlines():
            line = raw.strip()
            if not line or _PAGE_MARKER.match(line):
                continue
            numbered.append((sheet.number, line))

    starts = _sequential_item_starts(numbered)
    rows: list[BoqRow] = []
    rejected: list[str] = []

    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(numbered)
        page_number, first_line = numbered[start]
        match = _ITEM_NUMBER.match(first_line)
        identifier = match.group(1) if match else first_line
        # Whatever followed the number on its own line is the start of the description, and may
        # carry the unit at the end of it.
        remainder = (match.group(2) if match else None) or ""
        block = ([(page_number, remainder)] if remainder else []) + numbered[start + 1 : end]
        if len(block) > _MAX_DESCRIPTION_LINES + 8:
            # Far past the end of the table; the bill has finished and this is prose.
            continue

        values = [
            parsed
            for _, line in block
            if _MONEY_LINE.match(line) and (parsed := _to_decimal(line)) is not None
        ]
        if len(values) < 3:
            continue

        # More than one complete triple means the block holds more than one priced row. On the real
        # document, items 21 and 22 each carry sub-items "(a)" and "(b)" with their own unit,
        # quantity, rate and amount, and the parent row is a heading with no figures of its own.
        #
        # Taking the last triple reported sub-item (b) as though it were the item, silently and with
        # internally consistent arithmetic — the same misattribution the sequence fix removed
        # elsewhere. Refusing is the only honest option: this reader has no representation for a
        # parent item with priced children, and inventing one from a positional guess would put a
        # wrong quantity into a payment reconciliation.
        if len(values) >= 6 and _agrees(values[-6], values[-5], values[-4]):
            rejected.append(
                f"item {identifier} (page {page_number}): the block contains more than one priced "
                f"row — {values[-6]} x {values[-5]} = {values[-4]} and {values[-3]} x "
                f"{values[-2]} = {values[-1]} — which is how this document writes sub-items "
                f"'(a)' and '(b)'. Refused: reporting either one as the item would be wrong, and "
                f"sub-items are not yet represented"
            )
            continue

        # The last three are quantity, rate and amount; anything earlier belongs to the description
        # (specifications quote figures constantly).
        quantity, rate, amount = values[-3], values[-2], values[-1]
        unit = next((line for _, line in block if _UNIT.match(line)), None)
        if unit is None:
            # On a merged row the unit is the last word of the description line.
            unit = next(
                (
                    tail
                    for _, line in block
                    if (tail := line.rsplit(maxsplit=1)[-1] if line.split() else "")
                    and _UNIT.match(tail)
                ),
                None,
            )
        description = " ".join(
            line for _, line in block if not _MONEY_LINE.match(line) and not _UNIT.match(line)
        ).strip()

        if not _agrees(quantity, rate, amount):
            rejected.append(
                f"item {identifier} (page {page_number}): {quantity} x {rate} = {quantity * rate} "
                f"but the amount is stated as {amount}; refused rather than reported, because a "
                f"row whose arithmetic does not close was probably not read correctly"
            )
            continue

        rows.append(
            BoqRow(
                item_identifier=identifier,
                description=description[:2000],
                unit=unit,
                quantity=quantity,
                rate=rate,
                amount=amount,
                page=page_number,
                order=len(rows) + 1,
            )
        )

    # The page of the first accepted row, not the page the heading appeared on. A bid document
    # references its bill of quantities in its contents long before it prices it — on the observed
    # document, page 26 versus page 164 — and the useful answer is where the rows actually are.
    return PdfBoq(
        rows=tuple(rows),
        first_page=rows[0].page if rows else None,
        rejected=tuple(rejected),
    )


def fact_kinds() -> dict[str, FactKind]:
    """The kind of each fact this reader produces, for the persistence layer."""
    return {
        FIELD_ITEM_IDENTIFIER: FactKind.IDENTIFIER,
        FIELD_ITEM_DESCRIPTION: FactKind.TEXT,
        FIELD_CONTRACTED_QUANTITY: FactKind.QUANTITY,
        FIELD_CONTRACT_RATE: FactKind.MONEY,
        FIELD_LINE_AMOUNT: FactKind.MONEY,
    }


def currency_for(fact_type: str) -> str | None:
    return CURRENCY_INR if fact_type in {FIELD_CONTRACT_RATE, FIELD_LINE_AMOUNT} else None


def boq_fields(boq: PdfBoq) -> list[tuple[str, BoqRow]]:
    """Flatten accepted rows into (fact type, row) pairs for the persistence layer.

    Deliberately reuses the fact vocabulary the spreadsheet reader established rather than inventing
    a PDF-specific one. A contracted quantity is the same fact whether it was read from a cell or
    from a flattened page, and a rule comparing it must not have to know which.
    """
    pairs: list[tuple[str, BoqRow]] = []
    for row in boq.rows:
        pairs.append((FIELD_ITEM_IDENTIFIER, row))
        if row.description:
            pairs.append((FIELD_ITEM_DESCRIPTION, row))
        pairs.append((FIELD_CONTRACTED_QUANTITY, row))
        pairs.append((FIELD_CONTRACT_RATE, row))
        pairs.append((FIELD_LINE_AMOUNT, row))
    return pairs


def value_of(fact_type: str, row: BoqRow) -> tuple[str, Decimal | None]:
    """The literal and numeric value for one fact of ``row``."""
    if fact_type == FIELD_ITEM_IDENTIFIER:
        return row.item_identifier, None
    if fact_type == FIELD_ITEM_DESCRIPTION:
        return row.description, None
    if fact_type == FIELD_CONTRACTED_QUANTITY:
        return f"{row.quantity}", row.quantity
    if fact_type == FIELD_CONTRACT_RATE:
        return f"{row.rate}", row.rate
    return f"{row.amount}", row.amount
