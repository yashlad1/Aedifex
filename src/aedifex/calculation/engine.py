"""The calculation layer: facts in, derived facts out. No verdicts.

This module has exactly one responsibility and a hard boundary around it. It computes values from
extracted facts and returns them. It does not decide whether a value is acceptable, does not know
what a threshold is, and cannot produce ``PASS``, ``FAIL`` or ``INCONCLUSIVE`` — those words do not
appear here and the return type has nowhere to put them.

That separation is what makes a derived fact reusable. ``bid_security_share = 0.02`` is true whether
the prescribed rate is 1%, 2%, or unknown; the moment a calculation also decided what the number
*meant*, it would only serve the one rule that agreed with it. Two rules already consume this
module's output and reach different kinds of conclusion from it.

Every calculation is a pure function of its inputs, uses :class:`~decimal.Decimal`, and records the
arithmetic it performed as a string so the result can be redone by hand. One that cannot be
performed returns ``None`` rather than a zero or a guess — the same rule the extractors follow, for
the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Final

from aedifex.domain.evidence import FactKind
from aedifex.infrastructure.database.models import ExtractedFact

__all__ = [
    "CALCULATIONS",
    "DERIVED_BID_SECURITY_SHARE",
    "Calculated",
    "compute_bid_security_share",
    "compute_for_document",
]

PRODUCED_BY: Final[str] = "aedifex.calculation.engine"

DERIVED_BID_SECURITY_SHARE: Final[str] = "bid_security_share"

# Bumped when a calculation changes in a way that could alter a value. The unique constraint on
# (subject, fact_type, calculation_version) then makes the new value a new row rather than an
# overwrite, so a finding recorded against the old arithmetic stays explicable.
CALCULATION_VERSION: Final[str] = "1"


@dataclass(frozen=True, slots=True)
class Calculated:
    """One computed value, with everything needed to re-derive and to store it.

    ``expression`` is the arithmetic as text — ``1693000 / 84649969`` — and it is not decoration. It
    is the difference between a number a reader can check and a number they have to accept.
    """

    fact_type: str
    kind: FactKind
    value: Decimal
    expression: str
    calculation: str
    calculation_version: str = CALCULATION_VERSION
    produced_by: str = PRODUCED_BY
    unit: str | None = None
    currency: str | None = None
    inputs: dict[str, ExtractedFact] = field(default_factory=dict)


def _numeric(fact: ExtractedFact | None) -> Decimal | None:
    if fact is None or fact.numeric_value is None:
        return None
    return Decimal(fact.numeric_value)


def compute_bid_security_share(
    facts: dict[str, ExtractedFact],
) -> Calculated | None:
    """Bid security as a fraction of estimated cost.

    Returns ``None`` when either amount is missing or the cost is not positive. A share of nothing
    is not zero — it is undefined, and returning zero would hand a rule a number that looks like an
    answer.

    The division is deliberately not rounded. Rounding belongs where a value is *displayed* or
    *compared*, and a stored derived fact that has already been rounded cannot be compared against a
    tolerance finer than the rounding.
    """
    cost = _numeric(facts.get("estimated_cost"))
    security = _numeric(facts.get("bid_security"))
    if cost is None or security is None or cost <= 0:
        return None
    try:
        share = security / cost
    except (InvalidOperation, DivisionByZero):  # pragma: no cover - guarded above
        return None

    return Calculated(
        fact_type=DERIVED_BID_SECURITY_SHARE,
        kind=FactKind.PERCENTAGE,
        value=share,
        expression=f"{security} / {cost}",
        calculation="share_of",
        inputs={
            "estimated_cost": facts["estimated_cost"],
            "bid_security": facts["bid_security"],
        },
    )


# Calculations that need only facts from a single document. Registered rather than called directly
# so adding one is a one-line change here and nothing else -- the same reason the rule registry
# exists.
CALCULATIONS: Final[dict[str, object]] = {
    DERIVED_BID_SECURITY_SHARE: compute_bid_security_share,
}


def compute_for_document(facts: list[ExtractedFact]) -> tuple[Calculated, ...]:
    """Run every single-document calculation over one document's facts.

    Facts are indexed by type, newest extractor version winning, so a calculation never mixes an old
    extraction with a new one.
    """
    newest: dict[str, ExtractedFact] = {}
    for fact in facts:
        current = newest.get(fact.fact_type)
        if current is None or fact.extractor_version > current.extractor_version:
            newest[fact.fact_type] = fact

    results: list[Calculated] = []
    for compute in (compute_bid_security_share,):
        calculated = compute(newest)
        if calculated is not None:
            results.append(calculated)
    return tuple(results)
