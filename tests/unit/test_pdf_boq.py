"""Reading a priced bill of quantities, and checking that it adds up.

Every case here reproduces a defect found by running a real NHAI bill through the pipeline, and each
one is a money defect rather than a cosmetic one:

* a credit row written in accounting parentheses was invisible, so the bill was overstated by
  ₹11,81,174.40 — a sign error in a payment figure;
* an item priced through sub-items ``(a)``/``(b)`` was refused, dropping ₹65,951.50;
* the total was summed from one row instead of thirty-seven, because the persistence layer handed
  the calculation one fact per type.

Together they were the whole of a 1.3% discrepancy against the document's own stated total that had
previously been recorded as "cause not established". The layout in these fixtures is the real one:
figures on their own lines after a many-line description, the unit sometimes merged into the
description line, and a "Total Estimated Cost" row at the end.
"""

from __future__ import annotations

from decimal import Decimal

from aedifex.calculation.engine import DERIVED_BILL_ITEMS_TOTAL, compute_bill_items_total
from aedifex.domain.evidence import FactKind
from aedifex.extraction.pdf_boq import (
    FIELD_LINE_AMOUNT,
    FIELD_STATED_BILL_TOTAL,
    read_pdf_boq,
)
from aedifex.extraction.pdftext import DocumentText, PageText
from aedifex.extraction.tender_notice import Evidence, ExtractedField, TenderNotice
from aedifex.infrastructure.database.models import DerivedFact, ExtractedFact
from aedifex.verification.bill_total import BILL_TOTAL_RULE_ID, evaluate_bill_total
from aedifex.verification.rules import NOT_SOURCED, Outcome

# The header fragments a flattened PDF produces, which are what tells a priced bill from the twenty
# other pages that merely mention one.
_HEADER = """Bill of Quantities (BOQ)
Sr
No.
Description Unit
Quantity
Rate per
unit
Amount (In
Rs)
"""


def _document(*pages: str) -> DocumentText:
    return DocumentText(
        pages=tuple(PageText(number=index, text=text) for index, text in enumerate(pages, start=1)),
        page_count=len(pages),
        truncated=False,
    )


def test_a_credit_row_in_parentheses_is_read_as_negative() -> None:
    """``(11,81,174.40)`` is minus eleven lakh, and a bill says so with brackets.

    The real document's last item is a recovery of milled material. Reading only unbracketed figures
    dropped it and overstated the bill by its full value.
    """
    boq = read_pdf_boq(_document(_HEADER + """1
Milling on Bituminous Surface
Cum
945.00
679.00
6,41,655.00
2 Recovery of Milled Material Cum
661.50
(1,785.60)
(11,81,174.40)
Total Estimated Cost
(5,39,519.40)
"""))

    assert [row.item_identifier for row in boq.rows] == ["1", "2"]
    recovery = boq.rows[1]
    assert recovery.rate == Decimal("-1785.60")
    assert recovery.amount == Decimal("-1181174.40")
    # The sign survives into the total, which is the point: a credit reduces the bill.
    assert boq.total_amount == Decimal("-539519.40")
    assert boq.stated_total == Decimal("-539519.40")
    assert boq.rejected == ()


def test_sub_items_become_their_own_rows_rather_than_being_refused() -> None:
    """Items 21 and 22 of the real bill are headings priced entirely through ``(a)``/``(b)``.

    Previously refused, which lost four rows worth ₹65,951.50. Reporting either sub-item *as* the
    parent would have been worse — that is the misattribution the refusal was guarding against.
    """
    boq = read_pdf_boq(_document(_HEADER + """1
Kilometre Stone: - Reinforced cement concrete M25 grade
-
(a)
5th kilometre stone
Nos
5.00
3,550.00
17,750.00
(b)
Ordinary kilometre stone
Nos
20.00
2,078.00
41,560.00
Total Estimated Cost
59,310.00
"""))

    assert [row.item_identifier for row in boq.rows] == ["1(a)", "1(b)"]
    assert [row.amount for row in boq.rows] == [Decimal("17750.00"), Decimal("41560.00")]
    # The parent's heading is kept on each child: "5th kilometre stone" on its own is not an item.
    assert "Kilometre Stone" in boq.rows[0].description
    assert "5th kilometre stone" in boq.rows[0].description
    assert boq.rejected == ()


def test_the_total_row_ends_the_bill_instead_of_becoming_a_line_item() -> None:
    """The last item's block used to run on and take the grand total as one of its three figures."""
    boq = read_pdf_boq(_document(_HEADER + """1
Providing and installing solar high-mast lights
Nos.
2.00
2,56,355.93
5,12,711.86
Total Estimated Cost
5,12,711.86
Bidder to quote single rate as tender premium % above the total estimated cost.
"""))

    assert len(boq.rows) == 1
    assert boq.rows[0].quantity == Decimal("2.00")
    assert boq.rows[0].amount == Decimal("512711.86")
    assert boq.stated_total == Decimal("512711.86")
    assert boq.stated_total_literal == "5,12,711.86"


def _fact(amount: str, *, row: int | None, fact_type: str = FIELD_LINE_AMOUNT) -> ExtractedFact:
    return ExtractedFact(
        document_id=None,
        fact_type=fact_type,
        literal=amount,
        numeric_value=Decimal(amount),
        currency="INR",
        page=1,
        span_start=0,
        span_end=0,
        snippet=f"row {row}",
        method=f"pdf_boq:item {row}",
        kind=FactKind.MONEY,
        sheet_row=row,
        extractor="tender_notice",
        extractor_version="1",
    )


def test_the_bill_total_sums_every_row_not_just_the_last() -> None:
    """A bill of quantities states the same kind of fact once per line.

    Indexing facts by type before summing them produced the value of whichever row was written last
    and called it the bill total — the same defect as arbitrary fact selection, in the calculation
    layer instead of the rules.
    """
    calculated = compute_bill_items_total(
        [
            _fact("641655.00", row=1),
            _fact("3239775.00", row=2),
            _fact("-1181174.40", row=3),
            _fact("84649969.01", row=None, fact_type=FIELD_STATED_BILL_TOTAL),
        ]
    )

    assert calculated is not None
    assert calculated.fact_type == DERIVED_BILL_ITEMS_TOTAL
    assert calculated.value == Decimal("2700255.60")
    # One recorded input per line item, so the total unfolds into the rows it came from.
    assert len(calculated.inputs) == 3
    assert calculated.expression == "641655.00 + 3239775.00 + -1181174.40"


def _field(name: str, value: str, *, row: int | None = None) -> ExtractedField:
    return ExtractedField(
        name=name,
        kind=FactKind.MONEY,
        literal=value,
        value=Decimal(value),
        currency="INR",
        sheet_row=row,
        evidence=Evidence(page=1, start=0, end=0, snippet=value),
        method="test",
    )


def _derived(value: str) -> DerivedFact:
    return DerivedFact(fact_type=DERIVED_BILL_ITEMS_TOTAL, numeric_value=Decimal(value))


def test_a_bill_that_adds_up_passes_and_one_that_does_not_goes_to_review() -> None:
    """The verdict a quantity surveyor asks for, and the one this project may not overstate."""
    notice = TenderNotice(
        fields=(
            _field(FIELD_LINE_AMOUNT, "641655.00", row=1),
            _field(FIELD_LINE_AMOUNT, "3239775.00", row=2),
            _field(FIELD_STATED_BILL_TOTAL, "3881430.00"),
        ),
        unsupported=(),
    )

    agreeing = evaluate_bill_total(notice, bill_total=_derived("3881430.00"))
    assert agreeing.rule_id == BILL_TOTAL_RULE_ID
    assert agreeing.outcome is Outcome.PASS

    # A bill that does not reconcile is never a FAIL: the rule establishes that two figures disagree
    # and cannot establish which of them is wrong.
    disagreeing = evaluate_bill_total(notice, bill_total=_derived("3891430.00"))
    assert disagreeing.outcome is Outcome.REVIEW
    assert disagreeing.detail["difference"] == "10000.00"


def test_an_incompletely_read_bill_is_not_compared_at_all() -> None:
    """A refused row makes the sum incomplete, and an incomplete sum against a complete total would
    report our own gap as the document's discrepancy."""
    notice = TenderNotice(
        fields=(
            _field(FIELD_LINE_AMOUNT, "641655.00", row=1),
            _field(FIELD_STATED_BILL_TOTAL, "3881430.00"),
        ),
        unsupported=(),
    )

    result = evaluate_bill_total(notice, bill_total=_derived("641655.00"), refused_rows=1)
    assert result.outcome is Outcome.INCONCLUSIVE
    assert result.detail["refused_rows"] == "1"


def test_a_document_with_no_bill_is_inconclusive_rather_than_zero() -> None:
    """Most documents are not bills of quantities, and a sum of nothing is not zero."""
    result = evaluate_bill_total(TenderNotice(fields=(), unsupported=()))
    assert result.outcome is Outcome.INCONCLUSIVE
    assert result.expected == NOT_SOURCED
