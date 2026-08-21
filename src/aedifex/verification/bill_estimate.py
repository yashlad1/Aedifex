"""Does the priced bill come to what the tender said the work would cost?

Two figures a tender states in different places and for different purposes: the **estimated cost**
the authority advertised, and the **total the priced bill of quantities states for itself**.
Comparing them is the one rule the coverage inventory found executable with facts already in the
corpus, needing no provision, no new fact type and no extractor.

**It reports and does not judge.** No authority in the corpus publishes a norm for how far a priced
bill may sit from the advertised estimate — a bid may legitimately be above or below it, and page
171 of the observed document asks the bidder to quote exactly that premium or discount. So the
outcome is ``INCONCLUSIVE`` with ``expected = NOT SOURCED`` and the difference reported: measured,
not judged. The same shape the bid-security rule used before a rulebook existed to judge against,
and for the same reason.

Agreement is the interesting case, not a boring one. When the two figures match, the priced bill is
carrying the *employer's* rates rather than a bidder's — which tells a reader what the document
actually is. The summary says so explicitly rather than leaving a difference of zero to be inferred.

Generic by construction: it compares two fact types and knows nothing about who issued the document.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from aedifex.extraction.pdf_boq import FIELD_STATED_BILL_TOTAL
from aedifex.extraction.tender_notice import (
    FIELD_ESTIMATED_COST,
    ExtractedField,
    TenderNotice,
)
from aedifex.verification.rules import NOT_SOURCED, Outcome, RuleResult

__all__ = [
    "BILL_ESTIMATE_RULE_ID",
    "BILL_ESTIMATE_RULE_VERSION",
    "BILL_ESTIMATE_TOLERANCE",
    "evaluate_bill_against_estimate",
]

BILL_ESTIMATE_RULE_ID: Final[str] = "priced_bill_matches_advertised_estimate"
BILL_ESTIMATE_RULE_VERSION: Final[str] = "1"

# One rupee, for the same documented reason as the other two money rules: an estimated cost is
# stated to the rupee (Rs. 8,46,49,969) while a bill total is carried to the paisa
# (8,46,49,969.01), so the two can differ by less than a rupee while being the same figure. Anything
# larger is a real difference and is reported as one, never absorbed.
BILL_ESTIMATE_TOLERANCE: Final[Decimal] = Decimal("1.00")

_PAISE: Final[Decimal] = Decimal("0.01")
_PERCENT_PLACES: Final[Decimal] = Decimal("0.0001")


def _money(value: Decimal) -> str:
    return str(value.quantize(_PAISE, rounding=ROUND_HALF_UP))


def _percent(part: Decimal, whole: Decimal) -> str | None:
    """``part`` as a percentage of ``whole``, or ``None`` when the base is not positive.

    A percentage of nothing is undefined rather than zero, which is the rule the calculation layer
    already follows: returning zero would hand a reader a number that looks like an answer.
    """
    if whole <= 0:
        return None
    return str((part / whole * 100).quantize(_PERCENT_PLACES, rounding=ROUND_HALF_UP))


def evaluate_bill_against_estimate(
    notice: TenderNotice,
    **_unused: object,
) -> RuleResult:
    """Compare a document's priced bill total against the estimated cost it advertises.

    Args:
        notice: The extracted facts. Read here are ``stated_bill_total`` and ``estimated_cost``,
            both document-scoped.
        **_unused: Options other rules declare. Accepted and ignored, because the registry hands
            every rule the same keywords.

    Returns:
        Always ``INCONCLUSIVE``. The difference is arithmetic and is reported exactly; whether it is
        acceptable is a question no document in the corpus answers.
    """
    total = notice.field(FIELD_STATED_BILL_TOTAL)
    cost = notice.field(FIELD_ESTIMATED_COST)
    evidence: dict[str, ExtractedField] = {
        role: field
        for role, field in ((FIELD_STATED_BILL_TOTAL, total), (FIELD_ESTIMATED_COST, cost))
        if field is not None
    }

    def result(summary: str, *, observed: str, detail: dict[str, str]) -> RuleResult:
        return RuleResult(
            rule_id=BILL_ESTIMATE_RULE_ID,
            rule_version=BILL_ESTIMATE_RULE_VERSION,
            outcome=Outcome.INCONCLUSIVE,
            summary=summary,
            expected=NOT_SOURCED,
            observed=observed,
            detail=detail,
            evidence=evidence,
        )

    if total is None or total.value is None or cost is None or cost.value is None:
        missing = ", ".join(
            name
            for name, field in (
                (FIELD_STATED_BILL_TOTAL, total),
                (FIELD_ESTIMATED_COST, cost),
            )
            if field is None or field.value is None
        )
        return result(
            f"Cannot compare the priced bill against the advertised estimate: {missing} "
            f"{'was' if ',' not in missing else 'were'} not extracted from this document.",
            observed="not comparable",
            detail={"missing": missing},
        )

    # Exact Decimal throughout. The difference is the bill minus the estimate, so a positive number
    # means the bill is above what was advertised -- the direction a reader expects from the words.
    difference = total.value - cost.value
    share = _percent(difference, cost.value)
    detail = {
        "stated_bill_total": _money(total.value),
        "estimated_cost": _money(cost.value),
        "difference": _money(difference),
        "absolute_difference": _money(abs(difference)),
        "percentage_difference": share if share is not None else NOT_SOURCED,
        "tolerance": str(BILL_ESTIMATE_TOLERANCE),
        "within_tolerance": str(abs(difference) <= BILL_ESTIMATE_TOLERANCE).lower(),
    }
    percent_text = f"{share}%" if share is not None else "an undefined share of a non-positive base"

    if abs(difference) <= BILL_ESTIMATE_TOLERANCE:
        return result(
            f"The priced bill totals {_money(total.value)} and the advertised estimated cost is "
            f"{_money(cost.value)} — the same figure within {BILL_ESTIMATE_TOLERANCE}, differing "
            f"by {_money(abs(difference))}. Effectively identical, which means the bill carries "
            f"the authority's own rates rather than a bidder's quoted rates. Reported, not judged: "
            f"no "
            f"document in this corpus states how far a priced bill may sit from the estimate.",
            observed=_money(total.value),
            detail=detail,
        )

    direction = "above" if difference > 0 else "below"
    return result(
        f"The priced bill totals {_money(total.value)} against an advertised estimated cost of "
        f"{_money(cost.value)} — {_money(abs(difference))} {direction} it, or {percent_text}. "
        f"Reported, not judged: a bid may legitimately sit above or below the estimate, and no "
        f"document in this corpus states a permitted range.",
        observed=_money(total.value),
        detail=detail,
    )
