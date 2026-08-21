"""Comparing a priced bill against the estimate the tender advertised.

Money arithmetic and a percentage, on two figures that in the real corpus agree to one paisa. Exact
``Decimal`` throughout: a difference of ₹0.01 on ₹8.46 crore is the case that distinguishes a
correct implementation from one that has silently gone through a float.

The rule reports and does not judge, and the tests assert that too — no document in the corpus
states how far a bid may sit from the estimate, so a PASS or a FAIL here would be a verdict with no
threshold behind it.
"""

from __future__ import annotations

from decimal import Decimal

from aedifex.domain.evidence import FactKind
from aedifex.extraction.pdf_boq import FIELD_STATED_BILL_TOTAL
from aedifex.extraction.tender_notice import (
    FIELD_ESTIMATED_COST,
    Evidence,
    ExtractedField,
    TenderNotice,
)
from aedifex.verification.bill_estimate import (
    BILL_ESTIMATE_RULE_ID,
    evaluate_bill_against_estimate,
)
from aedifex.verification.rules import NOT_SOURCED, Outcome, RuleResult


def _field(name: str, value: str | None) -> ExtractedField:
    return ExtractedField(
        name=name,
        kind=FactKind.MONEY,
        literal=value or "unreadable",
        value=Decimal(value) if value is not None else None,
        currency="INR",
        evidence=Evidence(page=6, start=0, end=1, snippet=value or ""),
        method="test",
    )


def _evaluate(total: str | None, cost: str | None) -> RuleResult:
    fields = tuple(
        _field(name, value)
        for name, value in ((FIELD_STATED_BILL_TOTAL, total), (FIELD_ESTIMATED_COST, cost))
        if value is not None
    )
    return evaluate_bill_against_estimate(TenderNotice(fields=fields, unsupported=()))


def test_the_real_tender_agrees_to_one_paisa_and_says_so() -> None:
    """The corpus case: a bill of ₹8,46,49,969.01 against an estimate of ₹8,46,49,969.

    One paisa apart on ₹8.46 crore. The rule must recognise that as the same figure *and* explain
    what agreement means — a bill identical to the advertised estimate carries the authority's own
    rates rather than a bidder's.
    """
    result = _evaluate("84649969.01", "84649969.00")

    assert result.rule_id == BILL_ESTIMATE_RULE_ID
    assert result.outcome is Outcome.INCONCLUSIVE
    assert result.expected == NOT_SOURCED
    assert result.detail["absolute_difference"] == "0.01"
    assert result.detail["within_tolerance"] == "true"
    assert "authority's own rates" in result.summary
    # Both facts cited, so the comparison can be redone from the finding alone.
    assert set(result.evidence) == {FIELD_STATED_BILL_TOTAL, FIELD_ESTIMATED_COST}


def test_a_real_difference_is_reported_with_its_percentage_and_direction() -> None:
    """A bill 10% above the estimate is stated as such, and still not judged."""
    result = _evaluate("110000000.00", "100000000.00")

    assert result.outcome is Outcome.INCONCLUSIVE
    assert result.detail["difference"] == "10000000.00"
    assert result.detail["percentage_difference"] == "10.0000"
    assert result.detail["within_tolerance"] == "false"
    assert "above" in result.summary


def test_a_bill_below_the_estimate_carries_a_negative_difference() -> None:
    """Sign convention: bill minus estimate, so below the estimate is negative."""
    result = _evaluate("90000000.00", "100000000.00")

    assert result.detail["difference"] == "-10000000.00"
    assert result.detail["absolute_difference"] == "10000000.00"
    assert result.detail["percentage_difference"] == "-10.0000"
    assert "below" in result.summary


def test_the_outcome_is_never_a_verdict() -> None:
    """No document in this corpus states a permitted range, so nothing here may pass or fail."""
    for total, cost in (
        ("84649969.01", "84649969.00"),
        ("200000000.00", "100000000.00"),
        ("1.00", "100000000.00"),
    ):
        assert _evaluate(total, cost).outcome is Outcome.INCONCLUSIVE


def test_a_percentage_of_a_non_positive_base_is_undefined_not_zero() -> None:
    """A share of nothing is undefined. Reporting 0% would look like an answer."""
    result = _evaluate("5000.00", "0.00")
    assert result.detail["percentage_difference"] == NOT_SOURCED
    assert result.detail["absolute_difference"] == "5000.00"


def test_a_missing_figure_names_which_one_is_missing() -> None:
    """Half a comparison is not a comparison, and the finding says which half is absent."""
    without_bill = _evaluate(None, "84649969.00")
    assert without_bill.outcome is Outcome.INCONCLUSIVE
    assert without_bill.detail["missing"] == FIELD_STATED_BILL_TOTAL

    without_either = _evaluate(None, None)
    assert without_either.detail["missing"] == f"{FIELD_STATED_BILL_TOTAL}, {FIELD_ESTIMATED_COST}"
    assert without_either.evidence == {}
