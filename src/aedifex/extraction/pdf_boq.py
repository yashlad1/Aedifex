"""Reading a priced bill of quantities out of a PDF's text layer.

Written against a real document, not a template: pages 164-171 of an NHAI bid document already in
this corpus, which holds a 35-item priced BOQ totalling ₹8,46,49,969.01. Before this existed the
pipeline extracted four tender-notice fields from that document and nothing else — the entire bill
was invisible.

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

**Arithmetic is no longer an admission criterion, and that is the most important thing about this
module.** It used to be: ``quantity x rate`` had to reproduce the stated amount within a tolerance,
or the row was refused. That invariant does not hold for commercial bills — the printed rate is
rounded for display while the printed amount was computed from the unrounded one — and it is why
three real IIT Bombay building bills, holding 2,309 priced rows between them, yielded **nothing at
all**. Worse, the rows it refused included the ones most worth having: a bill whose arithmetic
genuinely does not close is a finding, not a parse to discard.

So the responsibilities split. This module answers *can I reliably identify the row and its three
stated values?*, and :mod:`aedifex.calculation.row_arithmetic` answers *do those values agree, given
the precision they are printed at?* Every row is classified ``EXACT``,
``CONSISTENT_WITH_DISPLAY_ROUNDING`` or ``REVIEW``, and all three are returned.

Two layouts are read, both from real documents:

* **vertically exploded** — the NHAI bill above, one field per line, anchored on a heading plus the
  column headers and parsed positionally within an item block.
* **one row per line** — every IIT Bombay bill, ``3.6.1.1 M-25 Grade Cum 115 8,556.65  984,014.26``,
  anchored on the row's own shape because no page carries the words "Bill of Quantities" at all.

Row-level arithmetic is not sufficient on its own, and never was. A block can hold another item's
figures and close perfectly (see ``_sequential_item_starts``), and a row can be dropped entirely
without any surviving row noticing. The complement is the bill's own total, checked by
:mod:`aedifex.verification.bill_total` over what this module returns — arithmetic within a row
there, arithmetic across the bill there too.

Deliberately narrow. This reads the two layouts in front of it and nothing else; it is not a general
PDF table framework, and the next real document is expected to need changes here rather than to fit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from aedifex.calculation.row_arithmetic import (
    ArithmeticConsistency,
    RowArithmetic,
    classify_row_arithmetic,
)
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
    "FIELD_STATED_BILL_TOTAL",
    "BoqRow",
    "PdfBoq",
    "read_pdf_boq",
]

FIELD_LINE_AMOUNT: Final[str] = "line_amount"

# The total the bill states for itself. A document-scoped fact rather than a row-scoped one, and
# deliberately not the sum of anything: it is what the document says, and comparing it to what the
# rows add up to is a rule's job.
FIELD_STATED_BILL_TOTAL: Final[str] = "stated_bill_total"

# Where a priced bill of quantities begins. Matched on a page of its own rather than anywhere the
# phrase appears: a bid document mentions "BOQ" on twenty pages and prices it on eight.
_BOQ_HEADING: Final[re.Pattern[str]] = re.compile(
    r"Bill\s+of\s+Quantities\s*\(BOQ\)|Priced\s+Bill\s+of\s+Quantit", re.IGNORECASE
)

# Units as this corpus spells them. Recorded exactly as written and never converted — Cum and m3 may
# mean the same thing to an engineer, and asserting that is a judgement this module has no business
# making.
#
# The IIT Bombay bills needed three additions, every one of which had been a silent miss: a trailing
# period (``Cum.``, ``Sqm.``, ``Nos.``), the metric forms (``m2``, ``m3``, ``CUMT``, ``SQMT``), and
# the many spellings of a metre (``Rmtr``, ``Mtr``, ``Mtrs.``, ``Metre``, ``meter``). Measured: the
# metre spellings alone were 104 unparsed rows across two bills, and adding them moved the civil+MEP
# bill from 5.7% short of its own stated total to 0.47%.
# Longer spellings first: with IGNORECASE, "MT" would otherwise claim the first two characters of
# "Mtrs" and the match would depend on backtracking to recover.
_UNIT_NAMES: Final[str] = (
    r"Cumt|Cum|Sqmt|SQMT|Sqm|Rmtr|Rmt|Mtrs|Metre|Meter|Mtr|Litres|Litre|Ltr|"
    r"Quintal|Tonne|Km|MT|Nos|No|Each|Kg|Set|Job|LS|Pair|Point|Joint|Month|Day|CM|m2|m3"
)
# Bare "m" is deliberately absent. It would make any description line ending in the letter m look
# like a unit to _unit_in, and no observed priced row needs it.
_UNIT: Final[re.Pattern[str]] = re.compile(rf"^(?:{_UNIT_NAMES})\.?$", re.IGNORECASE)

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

# A figure in the table, which may be bracketed: a bill of quantities writes a credit in accounting
# parentheses, and the real document ends with one -- item 35, "Recovery of Milled Material", at
# 661.50 Cum x (1,785.60) = (11,81,174.40). Reading only unbracketed figures dropped that row
# entirely and overstated the bill by 11.8 lakh, which is the whole of the discrepancy this reader
# could not previously explain. A recovery, a deduction and a credit note are ordinary construction
# accounting, so the sign is part of the value and not a formatting quirk to be ignored.
_MONEY_LINE: Final[re.Pattern[str]] = re.compile(r"^\(?[\d,]+\.\d{2}\)?$")

# Where the bill stops. Anchored to a line that is *only* a total label: "total internal reflection"
# and "total mix" both appear inside item descriptions, and neither ends anything. Without this the
# final item's block ran on into the total and took it as one of its three figures.
_TOTAL_LABEL: Final[re.Pattern[str]] = re.compile(
    r"^(?:Grand\s+)?Total(?:\s+(?:Estimated\s+)?(?:Cost|Amount|Price))?$", re.IGNORECASE
)

# A priced sub-item under a parent heading: "(a)", "(b)". Items 21 and 22 of the real document are
# headings whose figures live entirely in their sub-items, which is normal practice rather than an
# oddity of this bill.
_SUB_ITEM: Final[re.Pattern[str]] = re.compile(r"^\(([a-z])\)$", re.IGNORECASE)

# A page marker such as "VII-5" sits at the top of every page in this volume.
_PAGE_MARKER: Final[re.Pattern[str]] = re.compile(r"^[IVXL]+-\d+$")

# Description lines longer than this are almost certainly prose that has run past the table.
_MAX_DESCRIPTION_LINES: Final[int] = 40


@dataclass(frozen=True, slots=True)
class BoqRow:
    """One priced line item, its three stated values, and where each was read from.

    The three values are kept as **independent evidence**: each carries the literal the document
    printed alongside the parsed ``Decimal``, because ``8,556.65`` and ``8556.65`` are the same
    number but only one of them is what the page says, and because the literal is what shows the
    precision the bill chose to print at.

    Whether the three agree is :attr:`arithmetic`, and it is a classification rather than a filter.
    A row that does not add up is kept.
    """

    item_identifier: str
    description: str
    unit: str | None
    quantity: Decimal
    rate: Decimal
    amount: Decimal
    page: int
    order: int
    """Position within the bill, used as the row locator in place of a spreadsheet cell."""

    quantity_literal: str = ""
    rate_literal: str = ""
    amount_literal: str = ""
    quantity_page: int = 0
    rate_page: int = 0
    amount_page: int = 0
    """Per-value provenance. Separate pages because a row can straddle a page break in the
    vertically-exploded layout, where the three figures are three lines rather than one."""

    arithmetic: RowArithmetic | None = None
    """How the stated amount relates to quantity x rate. ``None`` only for rows built by a caller
    that predates the classification."""


@dataclass(frozen=True, slots=True)
class PdfBoq:
    """What one document's priced bill of quantities yielded."""

    rows: tuple[BoqRow, ...]
    first_page: int | None
    rejected: tuple[str, ...]
    """Rows that failed the arithmetic check, with the numbers, so nothing is silently dropped."""

    stated_total: Decimal | None = None
    """The total the bill states for itself, read from its own total row.

    Kept separate from :attr:`total_amount`, which is what the rows add up to. Whether those two
    agree is a question for a rule, and answering it here would be this module deciding that its own
    parse is correct.
    """

    stated_total_page: int | None = None
    stated_total_literal: str | None = None

    @property
    def total_amount(self) -> Decimal:
        return sum((row.amount for row in self.rows), Decimal(0))


def _to_decimal(text: str) -> Decimal | None:
    """Parse one table figure, honouring accounting parentheses as a negative.

    ``(11,81,174.40)`` is minus eleven lakh, and a bill of quantities says so with brackets rather
    than a minus sign. Dropping the bracket would turn a recovery into a charge, which is a sign
    error in a payment figure -- the most expensive kind of misreading this module can commit.
    """
    stripped = text.strip()
    negative = stripped.startswith("(") and stripped.endswith(")")
    if negative:
        stripped = stripped[1:-1]
    try:
        value = Decimal(stripped.replace(",", ""))
    except InvalidOperation:
        return None
    return -value if negative else value


def _closes(quantity: Decimal, rate: Decimal, amount: Decimal) -> bool:
    """Whether three figures plausibly form one priced row, for *structural* disambiguation only.

    Not an admission test. This module no longer decides whether a row is worth reporting on its
    arithmetic — see :mod:`aedifex.calculation.row_arithmetic` — and the one question left that
    arithmetic can answer is how many rows a block contains. A block holding two complete triples is
    a block this reader has misread, and telling that apart from a single row with figures in its
    description needs to know whether the earlier triple closes.
    """
    return (
        classify_row_arithmetic(quantity, rate, amount).consistency
        is not ArithmeticConsistency.REVIEW
    )


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


def _unit_in(block: list[tuple[int, str]]) -> str | None:
    """The unit for a block, whether it sits on its own line or ends the description line."""
    unit = next((line for _, line in block if _UNIT.match(line)), None)
    if unit is not None:
        return unit
    return next(
        (
            tail
            for _, line in block
            if (tail := line.rsplit(maxsplit=1)[-1] if line.split() else "") and _UNIT.match(tail)
        ),
        None,
    )


def _build_row(
    identifier: str, block: list[tuple[int, str]], page_number: int, order: int
) -> tuple[BoqRow | None, str | None]:
    """One priced row from one block, or a reason it was refused.

    The last three figures are quantity, rate and amount; anything earlier belongs to the
    description, which quotes figures constantly ("not exceeding 25 mm", "1:4", "clause 601").
    """
    figures = [
        (line, figure_page, parsed)
        for figure_page, line in block
        if _MONEY_LINE.match(line) and (parsed := _to_decimal(line)) is not None
    ]
    values = [parsed for _, _, parsed in figures]
    if len(values) < 3:
        return None, None

    # More than one complete triple means the block holds more than one priced row, and taking the
    # last would report one row under another's number -- silently, and with arithmetic that closes.
    # Sub-items are handled before this point by splitting on their own markers; anything still
    # holding two triples here is a block this reader has misread, and refusing is the honest
    # answer.
    if len(values) >= 6 and _closes(values[-6], values[-5], values[-4]):
        return None, (
            f"item {identifier} (page {page_number}): the block contains more than one priced "
            f"row — {values[-6]} x {values[-5]} = {values[-4]} and {values[-3]} x "
            f"{values[-2]} = {values[-1]}. Refused: reporting either one as the item would be "
            f"wrong, and this block is not the sub-item layout the reader knows"
        )

    quantity_cell, rate_cell, amount_cell = figures[-3], figures[-2], figures[-1]
    quantity, rate, amount = quantity_cell[2], rate_cell[2], amount_cell[2]
    description = " ".join(
        line for _, line in block if not _MONEY_LINE.match(line) and not _UNIT.match(line)
    ).strip()

    # No arithmetic gate. A row whose amount disagrees with quantity x rate is classified and
    # returned, because that disagreement is a finding rather than a parse to be thrown away -- and
    # because "refused because the arithmetic did not close" was the reason five real building bills
    # produced nothing at all.
    return (
        BoqRow(
            item_identifier=identifier,
            description=description[:2000],
            unit=_unit_in(block),
            quantity=quantity,
            rate=rate,
            amount=amount,
            page=page_number,
            order=order,
            quantity_literal=quantity_cell[0],
            rate_literal=rate_cell[0],
            amount_literal=amount_cell[0],
            quantity_page=quantity_cell[1],
            rate_page=rate_cell[1],
            amount_page=amount_cell[1],
            arithmetic=classify_row_arithmetic(quantity, rate, amount),
        ),
        None,
    )


# --------------------------------------------------------------------------------------------
# The second observed layout: one priced row per line.
#
# The NHAI bill above explodes a row down the page -- item number, description, unit, quantity,
# rate, amount, each on its own line. Every IIT Bombay building bill puts the whole row on one
# line instead:
#
#     3.6.1.1 M-25 Grade Cum 115 8,556.65       984,014.26
#     4.2.1 Above Floor VI up to Floor IX Cum. 1900 139.92          265,849.40
#     Rmt 6500 56.00            364,000.00
#     Nos.30 498.00                  14,940.00
#
# Nothing about the vertical reader can be stretched to fit that, and three of its assumptions are
# actively wrong here: item numbers are hierarchical (``3.6.1.1``), so the strict 1,2,3 sequence
# never advances; quantities are printed as bare integers, so _MONEY_LINE's mandatory two decimals
# never match them; and no page carries the string "Bill of Quantities" at all.
#
# So the anchor is the row's own shape rather than a heading: a unit token followed by three
# numbers at the end of a line, where rate and amount both carry exactly two decimals. That is
# specific enough to need no heading -- section totals ("Total for RCC Work 392,522,415.84") carry
# one number, section headings carry none, and prose does not end in unit-then-three-figures.
_QUANTITY_FIGURE: Final[str] = r"\(?\d[\d,]*(?:\.\d+)?\)?"
_MONEY_FIGURE: Final[str] = r"\(?\d[\d,]*\.\d{2}\)?"

# ``Nos.30`` really occurs, so the gap between unit and quantity is optional.
_ROW_LINE: Final[re.Pattern[str]] = re.compile(
    rf"(?P<head>.*?)(?P<unit>{_UNIT_NAMES})\.?\s*"
    rf"(?P<quantity>{_QUANTITY_FIGURE})\s+"
    rf"(?P<rate>{_MONEY_FIGURE})\s+"
    rf"(?P<amount>{_MONEY_FIGURE})\s*$",
    re.IGNORECASE,
)

# One VMCC row prints its unit on its own line and its three figures on the next. Supported only in
# exactly that shape -- a bare triple with a unit immediately above it -- because three unanchored
# numbers at the end of a line are common in prose and a unit line above them is not.
_BARE_TRIPLE: Final[re.Pattern[str]] = re.compile(
    rf"^(?P<quantity>{_QUANTITY_FIGURE})\s+(?P<rate>{_MONEY_FIGURE})\s+"
    rf"(?P<amount>{_MONEY_FIGURE})\s*$"
)

# A hierarchical item number leading a line: 3.6.1.1, 4.2.1, 25.
#
# The space after the number is optional because the flattened text loses it: one page reads
# "4.26.1.1Exterior Grade - I MDF Board 6 mm thick". Requiring whitespace made that line match
# nothing, so the row silently inherited its parent's identifier 4.26 -- and three sibling rows then
# shared one identifier, which is a wrong work-item key rather than a missing one.
_HIERARCHICAL_ITEM: Final[re.Pattern[str]] = re.compile(r"^(\d+(?:\.\d+)*)(?=\s|[A-Za-z])\s*(.*)$")

# A section subtotal, which states an amount and is not a row. Excluded explicitly because it would
# otherwise be picked up by nothing -- it has one figure, not three.
#
# This comment used to end "and that these bills state no single total of their own". That was
# wrong, and the wrongness was load-bearing: page 1 of the IIT Bombay Hostel 19 bill states
# ``Total 854,391,859.40``, this pattern matched that line, and the reader skipped it as a section
# subtotal. Two rules then reported that the document states no total -- an assertion the document
# itself contradicts -- and the 1.25% by which the accepted rows fall short of it went unreported.
_SECTION_TOTAL: Final[re.Pattern[str]] = re.compile(
    r"^(?:Sub-?)?Total\b.*?[\d,]+\.\d{2}\s*$", re.IGNORECASE
)

# The bill's own total where the label and the figure share one line: ``Total 854,391,859.40``.
#
# Separate from :data:`_TOTAL_LABEL`, which the heading-anchored reader uses and which requires the
# label to stand alone on its line. Both spellings occur; this reader meets the second.
#
# A *section* total names what it sums -- "TOTAL OF SECTION A", "TOTAL OF (I+II+III+IV)",
# "TOTAL OF SUPER STRUCTURE WORKS", "Total with GST" -- so requiring a bare label excludes all of
# them, and excludes the GST-inclusive figure in particular: comparing rows quoted without tax
# against a total quoted with it would report an 18% discrepancy that does not exist.
#
# Necessary but not sufficient. A sub-bill states a bare "GRAND TOTAL" too, which is why
# :func:`_bill_total` still has to choose.
_INLINE_TOTAL: Final[re.Pattern[str]] = re.compile(
    r"^(?:Grand\s+)?Total\s+(\(?[\d,]+\.\d{2}\)?)$", re.IGNORECASE
)


def _bill_total(
    candidates: list[tuple[int, str, Decimal]], row_sum: Decimal
) -> tuple[int, str, Decimal] | None:
    """Choose the bill's own total from every bare total line the bill states.

    Takes the first candidate in document order that is not smaller than what the accepted rows add
    up to. The guard is what separates the bill's total from a sub-bill's: this reader can miss a
    priced row but never invents one, so the rows it accepted are a subset of the work any total of
    the *whole* bill covers. A candidate below their sum therefore totals a part, and adopting it
    would report a discrepancy of the entire remainder of the bill -- a false finding about money,
    which is worse than the ``INCONCLUSIVE`` that not choosing produces.

    Hostel 19 needs exactly this. Page 1 states ``Total 854,391,859.40``; page 35 states
    ``GRAND TOTAL 108,244,551.90`` for the electrical sub-bill and page 74 ``GRAND TOTAL 799014.47``
    for the fire pumps. All three are bare labels, so only the sum can tell them apart — and the
    ₹10.8 crore one shows why magnitude rather than page order has to do it.

    Its page 3 is the counter-case the *label* handles: ``GRAND TOTAL (I TO IV) 854,391,859`` is the
    same total rounded to the rupee, and adopting it over page 1's would report a ₹0.40 discrepancy
    that exists only in the rounding.

    Returns the page, the literal as written, and the value -- or ``None`` when no candidate
    qualifies, which leaves the two rules that read this fact ``INCONCLUSIVE`` as before.
    """
    for page_number, literal, value in candidates:
        if value >= row_sum:
            return page_number, literal, value
    return None


def _read_line_layout(document: DocumentText) -> PdfBoq:
    """Read a bill whose every priced row occupies one line.

    Rows carry the nearest preceding item number when they do not state one themselves, which is how
    these bills are written: item 3.9 describes the work over six lines and then prices it on a
    seventh that begins with the unit.
    """
    rows: list[BoqRow] = []
    context: list[str] = []
    identifier = ""
    previous_unit: str | None = None
    # Every bare total line the bill states, in document order. Collected rather than decided here
    # because the choice needs the row sum, and a bill states its total on page 1 -- before the rows
    # this reader is about to accept.
    totals: list[tuple[int, str, Decimal]] = []

    for page in document.pages:
        for raw in page.text.splitlines():
            line = raw.strip()
            if not line or _PAGE_MARKER.match(line) or _SECTION_TOTAL.match(line):
                if (inline_total := _INLINE_TOTAL.match(line)) is not None:
                    value = _to_decimal(inline_total.group(1))
                    if value is not None and value > 0:
                        totals.append((page.number, line, value))
                previous_unit = None
                continue

            numbered = _HIERARCHICAL_ITEM.match(line)
            match = _ROW_LINE.match(line)
            bare = _BARE_TRIPLE.match(line) if previous_unit else None

            if match is None and bare is None:
                # Not a priced row. Remember it as description context, and remember it as a unit
                # if that is all it is, so the next line can be a bare triple.
                if numbered is not None:
                    identifier = numbered.group(1)
                    context = [numbered.group(2).strip()] if numbered.group(2).strip() else []
                elif len(context) <= _MAX_DESCRIPTION_LINES:
                    context.append(line)
                previous_unit = line if _UNIT.match(line) else None
                continue

            if match is not None:
                head = match.group("head").strip()
                unit = match.group("unit")
                inline = _HIERARCHICAL_ITEM.match(head)
                if inline is not None:
                    identifier = inline.group(1)
                    description = inline.group(2).strip()
                else:
                    description = " ".join([*context, head]).strip() if head else " ".join(context)
            else:
                assert bare is not None  # noqa: S101 - narrowing for the type checker
                match = bare
                unit = previous_unit or ""
                description = " ".join(context).strip()

            quantity = _to_decimal(match.group("quantity"))
            rate = _to_decimal(match.group("rate"))
            amount = _to_decimal(match.group("amount"))
            previous_unit = None
            if quantity is None or rate is None or amount is None:
                continue

            rows.append(
                BoqRow(
                    item_identifier=identifier or f"row {len(rows) + 1}",
                    description=description[:2000],
                    unit=unit.rstrip(".") or None,
                    quantity=quantity,
                    rate=rate,
                    amount=amount,
                    page=page.number,
                    order=len(rows) + 1,
                    quantity_literal=match.group("quantity"),
                    rate_literal=match.group("rate"),
                    amount_literal=match.group("amount"),
                    quantity_page=page.number,
                    rate_page=page.number,
                    amount_page=page.number,
                    arithmetic=classify_row_arithmetic(quantity, rate, amount),
                )
            )
            context = []

    chosen = _bill_total(totals, sum((row.amount for row in rows), Decimal(0)))
    return PdfBoq(
        rows=tuple(rows),
        first_page=rows[0].page if rows else None,
        rejected=(),
        stated_total=chosen[2] if chosen else None,
        stated_total_page=chosen[0] if chosen else None,
        stated_total_literal=chosen[1] if chosen else None,
    )


def _stated_total(
    numbered: list[tuple[int, str]], label_at: int
) -> tuple[int, str, Decimal] | None:
    """The figure the bill states as its own total: the first money line after the total label."""
    for page_number, line in numbered[label_at + 1 :]:
        if _MONEY_LINE.match(line) and (value := _to_decimal(line)) is not None:
            return page_number, line, value
    return None


def read_pdf_boq(document: DocumentText) -> PdfBoq:
    """Extract priced line items from a bill of quantities in ``document``.

    Returns empty rows when the document contains no priced BOQ, which is the common case — most
    documents are not bills of quantities, and saying so is cheaper than guessing.
    """
    start_page = _find_table_page(document)
    if start_page is None:
        # No heading-anchored table. Try the one-row-per-line layout, which needs no heading because
        # the row shape is its own anchor. Ordered this way rather than by document inspection so
        # that the vertical reader's behaviour on the bill it was written against cannot change.
        return _read_line_layout(document)

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

    # The bill ends at its own total row, and the scan has to end there too: without this the last
    # item's block ran on and took the grand total as one of its three figures.
    #
    # Looked for *after* the first item rather than anywhere, because a "Total" in a preamble or a
    # page footer would otherwise truncate the bill before it started -- and this failure is silent,
    # producing an empty bill rather than a wrong one.
    all_starts = _sequential_item_starts(numbered)
    first_item = all_starts[0] if all_starts else 0
    total_at = next(
        (
            index
            for index, (_, line) in enumerate(numbered)
            if index > first_item and _TOTAL_LABEL.match(line)
        ),
        None,
    )
    stated = _stated_total(numbered, total_at) if total_at is not None else None
    items = numbered[:total_at] if total_at is not None else numbered

    # A prefix of the lines yields a prefix of the item starts, so the sequence does not need
    # recomputing -- filtering keeps the two views of the bill from being able to disagree.
    starts = [index for index in all_starts if index < len(items)]
    rows: list[BoqRow] = []
    rejected: list[str] = []

    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(items)
        page_number, first_line = items[start]
        match = _ITEM_NUMBER.match(first_line)
        identifier = match.group(1) if match else first_line
        # Whatever followed the number on its own line is the start of the description, and may
        # carry the unit at the end of it.
        remainder = (match.group(2) if match else None) or ""
        block = ([(page_number, remainder)] if remainder else []) + items[start + 1 : end]
        if len(block) > _MAX_DESCRIPTION_LINES + 8:
            # Far past the end of the table; the bill has finished and this is prose.
            continue

        for sub_identifier, sub_block in _split_sub_items(identifier, block):
            row, refusal = _build_row(sub_identifier, sub_block, page_number, len(rows) + 1)
            if refusal is not None:
                rejected.append(refusal)
            elif row is not None:
                rows.append(row)

    # The page of the first accepted row, not the page the heading appeared on. A bid document
    # references its bill of quantities in its contents long before it prices it — on the observed
    # document, page 26 versus page 164 — and the useful answer is where the rows actually are.
    return PdfBoq(
        rows=tuple(rows),
        first_page=rows[0].page if rows else None,
        rejected=tuple(rejected),
        stated_total=stated[2] if stated else None,
        stated_total_page=stated[0] if stated else None,
        stated_total_literal=stated[1] if stated else None,
    )


def _split_sub_items(
    identifier: str, block: list[tuple[int, str]]
) -> list[tuple[str, list[tuple[int, str]]]]:
    """One item block, split into the priced rows it actually contains.

    Items 21 and 22 of the real document are headings — a description, no figures — whose prices
    live in sub-items ``(a)`` and ``(b)``, each with its own unit, quantity, rate and amount. That
    is normal practice in a bill of quantities, not a quirk of this one.

    The parent's description is kept on each sub-item, because on its own ``5th kilometre stone``
    is not an item of work; the sentence a surveyor needs is the heading plus the qualifier.
    Identifiers become ``21(a)`` and ``21(b)``, which are what the document calls them, and which
    stay distinct from ``21`` under the existing identifier normalisation without any change to it.

    A block with no markers is returned unchanged, so the ordinary case pays nothing for this.
    """
    marks = [index for index, (_, line) in enumerate(block) if _SUB_ITEM.match(line)]
    if not marks:
        return [(identifier, block)]

    heading = block[: marks[0]]
    split: list[tuple[str, list[tuple[int, str]]]] = []
    for position, mark in enumerate(marks):
        end = marks[position + 1] if position + 1 < len(marks) else len(block)
        match = _SUB_ITEM.match(block[mark][1])
        letter = match.group(1).lower() if match else str(position)
        split.append((f"{identifier}({letter})", heading + block[mark + 1 : end]))
    return split


def fact_kinds() -> dict[str, FactKind]:
    """The kind of each fact this reader produces, for the persistence layer."""
    return {
        FIELD_ITEM_IDENTIFIER: FactKind.IDENTIFIER,
        FIELD_ITEM_DESCRIPTION: FactKind.TEXT,
        FIELD_CONTRACTED_QUANTITY: FactKind.QUANTITY,
        FIELD_CONTRACT_RATE: FactKind.MONEY,
        FIELD_LINE_AMOUNT: FactKind.MONEY,
        FIELD_STATED_BILL_TOTAL: FactKind.MONEY,
    }


def currency_for(fact_type: str) -> str | None:
    return (
        CURRENCY_INR
        if fact_type in {FIELD_CONTRACT_RATE, FIELD_LINE_AMOUNT, FIELD_STATED_BILL_TOTAL}
        else None
    )


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
    """The literal and numeric value for one fact of ``row``.

    The literal is what the bill *printed* where the reader captured it — ``8,556.65``, thousands
    separators and all — falling back to the parsed form only for rows built before literals were
    recorded. Storing the printed form matters twice over: it is the evidence a reviewer checks
    against the page, and its decimal places are what the arithmetic classification is derived from.
    """
    if fact_type == FIELD_ITEM_IDENTIFIER:
        return row.item_identifier, None
    if fact_type == FIELD_ITEM_DESCRIPTION:
        return row.description, None
    if fact_type == FIELD_CONTRACTED_QUANTITY:
        return row.quantity_literal or f"{row.quantity}", row.quantity
    if fact_type == FIELD_CONTRACT_RATE:
        return row.rate_literal or f"{row.rate}", row.rate
    return row.amount_literal or f"{row.amount}", row.amount
