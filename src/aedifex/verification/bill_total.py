"""Does a bill of quantities add up to the total it states for itself?

The first question a quantity surveyor asks of a priced bill, and the one that found the only real
defect this corpus has produced so far. Reading the NHAI bill left 32 rows summing to
₹8,57,65,191.91 against a stated ₹8,46,49,969.01 — 1.3% over, cause unknown. The document was
right and the reader was wrong, twice over: it could not see the negative recovery row written in
accounting parentheses, and it refused the two items priced through sub-items. With both fixed the
bill reconciles to ₹0.00.

That is why this rule exists rather than being an obvious afterthought. **It is a check on the
evidence chain as much as on the document.** A bill that does not add up is either a document worth
questioning or an extraction worth distrusting, and the one thing certain is that nothing downstream
of it should be relied on until somebody has looked.

So the outcome is REVIEW, never FAIL. The rule can establish that two numbers disagree; it cannot
establish which of them is wrong, and asserting that a real tender contains an arithmetic error is a
claim this project has no basis for making.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from aedifex.calculation.engine import DERIVED_BILL_ITEMS_TOTAL
from aedifex.extraction.pdf_boq import FIELD_LINE_AMOUNT, FIELD_STATED_BILL_TOTAL
from aedifex.extraction.tender_notice import ExtractedField, TenderNotice
from aedifex.infrastructure.database.models import DerivedFact
from aedifex.verification.rules import NOT_SOURCED, Outcome, RuleResult

__all__ = [
    "BILL_TOTAL_RULE_ID",
    "BILL_TOTAL_RULE_VERSION",
    "BILL_TOTAL_TOLERANCE",
    "evaluate_bill_total",
]

BILL_TOTAL_RULE_ID: Final[str] = "bill_items_reconcile_to_stated_total"
BILL_TOTAL_RULE_VERSION: Final[str] = "1"

# One rupee. Deliberately tight, and it can be: the sum adds the amounts the document *states* for
# each row, so the per-row rounding between quantity x rate and the stated amount -- ₹10 to ₹13 on
# the largest rows of the real bill -- never enters it. What the rupee absorbs is a total rounded to
# the rupee against rows carried to the paisa, which the observed document does exactly: its bill
# totals ₹8,46,49,969.01 and its bid price is stated as ₹8,46,49,969.00.
BILL_TOTAL_TOLERANCE: Final[Decimal] = Decimal("1.00")

# Money is reported to the paisa. Only for display: the comparison uses the unrounded values, so a
# rounded "0.00" can never stand in for a difference that actually breached the tolerance. Without
# this, a derived total carried to ten decimal places reports a difference of "0E-10" in a finding
# somebody is meant to read.
_PAISE: Final[Decimal] = Decimal("0.01")


def _money(value: Decimal) -> str:
    return str(value.quantize(_PAISE))


def _result(
    outcome: Outcome,
    summary: str,
    *,
    expected: str,
    observed: str,
    detail: dict[str, str],
    evidence: dict[str, ExtractedField],
    derived_evidence: dict[str, DerivedFact] | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=BILL_TOTAL_RULE_ID,
        rule_version=BILL_TOTAL_RULE_VERSION,
        outcome=outcome,
        summary=summary,
        expected=expected,
        observed=observed,
        detail=detail,
        evidence=evidence,
        derived_evidence=derived_evidence or {},
    )


def evaluate_bill_total(
    notice: TenderNotice,
    *,
    refused_rows: int = 0,
    bill_total: DerivedFact | None = None,
    **_unused: object,
) -> RuleResult:
    """Check that a bill's priced rows add up to the total the bill states.

    Args:
        notice: The extracted facts. Read here is the ``stated_bill_total``, plus the line amounts
            to know how many rows there were.
        refused_rows: How many rows the reader declined to return. Any at all makes the sum an
            incomplete one, and comparing an incomplete sum to a complete total would manufacture a
            discrepancy out of our own gap — so the rule declines instead.
        bill_total: The summed line amounts, from the calculation layer. Consumed rather than
            re-added here: the derived fact carries one input row per line item, so citing it makes
            the finding unfold into every page the total came from. Adding the facts up in this
            function would reach the same number and prove nothing about it.
        **_unused: Options other rules declare. Accepted and ignored, because the registry hands
            every rule the same keywords.

    Returns:
        ``PASS`` when the rows reconcile, ``REVIEW`` when they do not, and ``INCONCLUSIVE`` when
        there is nothing to compare or the bill was not read completely.
    """
    rows = tuple(field for field in notice.fields if field.name == FIELD_LINE_AMOUNT)
    stated = next((field for field in notice.fields if field.name == FIELD_STATED_BILL_TOTAL), None)

    evidence: dict[str, ExtractedField] = {}
    if stated is not None:
        evidence[FIELD_STATED_BILL_TOTAL] = stated
    derived = {DERIVED_BILL_ITEMS_TOTAL: bill_total} if bill_total is not None else {}

    if not rows:
        return _result(
            Outcome.INCONCLUSIVE,
            "This document contains no priced bill of quantities, so there is nothing to add up.",
            expected=NOT_SOURCED,
            observed="no priced rows",
            detail={"rows": "0"},
            evidence=evidence,
        )

    priced = len(rows)
    if bill_total is None or bill_total.numeric_value is None:
        return _result(
            Outcome.INCONCLUSIVE,
            f"This document states {priced} priced row(s), but no total was calculated from them, "
            f"so there is nothing to compare against what the bill states.",
            expected=NOT_SOURCED,
            observed="not calculated",
            detail={"rows": str(priced)},
            evidence=evidence,
            derived_evidence=derived,
        )

    total = Decimal(bill_total.numeric_value)
    shown = _money(total)

    if stated is None or stated.value is None:
        return _result(
            Outcome.INCONCLUSIVE,
            f"The bill's {priced} priced rows add up to {shown}, but the document states no "
            f"total of its own to compare that against.",
            expected=NOT_SOURCED,
            observed=shown,
            detail={"rows": str(priced), "sum_of_rows": shown},
            evidence=evidence,
            derived_evidence=derived,
        )

    if refused_rows:
        return _result(
            Outcome.INCONCLUSIVE,
            f"{refused_rows} row(s) of this bill could not be read, so its {priced} readable rows "
            f"are not the whole bill. Declining to compare an incomplete sum against a complete "
            f"total, which would report our own gap as the document's discrepancy.",
            expected=f"{stated.value}",
            observed=f"{shown} from {priced} of {priced + refused_rows} rows",
            detail={
                "rows": str(priced),
                "refused_rows": str(refused_rows),
                "sum_of_rows": shown,
                "stated_total": _money(stated.value),
            },
            evidence=evidence,
            derived_evidence=derived,
        )

    difference = total - stated.value
    detail = {
        "rows": str(priced),
        "refused_rows": "0",
        "sum_of_rows": shown,
        "stated_total": _money(stated.value),
        "difference": _money(difference),
        "tolerance": str(BILL_TOTAL_TOLERANCE),
    }

    if abs(difference) <= BILL_TOTAL_TOLERANCE:
        return _result(
            Outcome.PASS,
            f"The bill's {priced} priced rows add up to {shown}, which is the total the document "
            f"states for itself ({_money(stated.value)}) within {BILL_TOTAL_TOLERANCE}.",
            expected=_money(stated.value),
            observed=shown,
            detail=detail,
            evidence=evidence,
            derived_evidence=derived,
        )

    direction = "over" if difference > 0 else "under"
    return _result(
        Outcome.REVIEW,
        f"The bill's {priced} priced rows add up to {total}, which is {abs(difference)} "
        f"{direction} the total of {stated.value} the document states for itself. Either the "
        f"document does not add up or it was not read correctly, and this rule cannot tell which — "
        f"the summed total cites every row it used, so the addition can be redone by hand.",
        expected=f"{stated.value}",
        observed=f"{total}",
        detail=detail,
        evidence=evidence,
        derived_evidence=derived,
    )
