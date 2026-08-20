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
from aedifex.extraction.spreadsheet import (
    FIELD_CLAIMED_RATE,
    FIELD_CONTRACT_RATE,
    FIELD_CONTRACTED_QUANTITY,
    FIELD_CUMULATIVE_CLAIM_QUANTITY,
    FIELD_MEASURED_QUANTITY,
)
from aedifex.infrastructure.database.models import ExtractedFact

__all__ = [
    "CALCULATIONS",
    "DERIVED_BID_SECURITY_SHARE",
    "DERIVED_QUANTITY_VARIANCE",
    "DERIVED_RATE_VARIANCE",
    "DERIVED_REMAINING_CONTRACT_QUANTITY",
    "DERIVED_UNSUPPORTED_AMOUNT",
    "Calculated",
    "compute_bid_security_share",
    "compute_for_document",
    "compute_for_work_item",
    "compute_quantity_variance",
    "compute_rate_variance",
    "compute_remaining_contract_quantity",
    "compute_unsupported_amount",
]

PRODUCED_BY: Final[str] = "aedifex.calculation.engine"

DERIVED_BID_SECURITY_SHARE: Final[str] = "bid_security_share"

# Payment reconciliation. Each answers "what can be calculated?" and none answers "is this
# acceptable?" -- a positive quantity_variance is a number, not an accusation.
DERIVED_QUANTITY_VARIANCE: Final[str] = "quantity_variance"
DERIVED_REMAINING_CONTRACT_QUANTITY: Final[str] = "remaining_contract_quantity"
DERIVED_RATE_VARIANCE: Final[str] = "rate_variance"
DERIVED_UNSUPPORTED_AMOUNT: Final[str] = "unsupported_amount"

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


def compute_quantity_variance(facts: dict[str, ExtractedFact]) -> Calculated | None:
    """How much more has been claimed than was measured.

    Positive means the claim runs ahead of measured work. Negative means the opposite, and is
    perfectly ordinary — measurement often leads certification. The sign is information, so it is
    kept rather than made absolute.

    Units must agree. Comparing 520 cubic metres with 470 tonnes is not a variance, it is a category
    error, and refusing is the only correct answer.
    """
    claimed = facts.get(FIELD_CUMULATIVE_CLAIM_QUANTITY)
    measured = facts.get(FIELD_MEASURED_QUANTITY)
    pair = _comparable_pair(claimed, measured)
    if pair is None:
        return None
    claimed_value, measured_value, unit = pair
    return Calculated(
        fact_type=DERIVED_QUANTITY_VARIANCE,
        kind=FactKind.QUANTITY,
        value=claimed_value - measured_value,
        expression=f"{claimed_value} - {measured_value}",
        calculation="difference",
        unit=unit,
        inputs={
            FIELD_CUMULATIVE_CLAIM_QUANTITY: facts[FIELD_CUMULATIVE_CLAIM_QUANTITY],
            FIELD_MEASURED_QUANTITY: facts[FIELD_MEASURED_QUANTITY],
        },
    )


def compute_remaining_contract_quantity(facts: dict[str, ExtractedFact]) -> Calculated | None:
    """How much of the contracted quantity has not yet been claimed."""
    contracted = facts.get(FIELD_CONTRACTED_QUANTITY)
    claimed = facts.get(FIELD_CUMULATIVE_CLAIM_QUANTITY)
    pair = _comparable_pair(contracted, claimed)
    if pair is None:
        return None
    contracted_value, claimed_value, unit = pair
    return Calculated(
        fact_type=DERIVED_REMAINING_CONTRACT_QUANTITY,
        kind=FactKind.QUANTITY,
        value=contracted_value - claimed_value,
        expression=f"{contracted_value} - {claimed_value}",
        calculation="difference",
        unit=unit,
        inputs={
            FIELD_CONTRACTED_QUANTITY: facts[FIELD_CONTRACTED_QUANTITY],
            FIELD_CUMULATIVE_CLAIM_QUANTITY: facts[FIELD_CUMULATIVE_CLAIM_QUANTITY],
        },
    )


def compute_rate_variance(facts: dict[str, ExtractedFact]) -> Calculated | None:
    """How far the claimed rate departs from the contracted one."""
    claimed = _numeric(facts.get(FIELD_CLAIMED_RATE))
    contracted = _numeric(facts.get(FIELD_CONTRACT_RATE))
    if claimed is None or contracted is None:
        return None
    return Calculated(
        fact_type=DERIVED_RATE_VARIANCE,
        kind=FactKind.MONEY,
        value=claimed - contracted,
        expression=f"{claimed} - {contracted}",
        calculation="difference",
        currency=facts[FIELD_CONTRACT_RATE].currency,
        inputs={
            FIELD_CLAIMED_RATE: facts[FIELD_CLAIMED_RATE],
            FIELD_CONTRACT_RATE: facts[FIELD_CONTRACT_RATE],
        },
    )


def compute_unsupported_amount(
    facts: dict[str, ExtractedFact], *, variance: Decimal | None = None
) -> Calculated | None:
    """The money value of a claim that runs ahead of measured work.

    ``max(variance, 0) x contract_rate``. Floored at zero because a claim *behind* measured work is
    not a negative exposure — under-claiming does not create money owed back — and a signed product
    here would net two unrelated situations against each other.

    Valued at the **contracted** rate, not the claimed one. The question this answers is what the
    unsupported quantity is worth under the contract; using the claimed rate would fold a rate
    dispute into a quantity one and produce a figure that is neither.
    """
    rate = _numeric(facts.get(FIELD_CONTRACT_RATE))
    if variance is None or rate is None:
        return None
    exposure = variance if variance > 0 else Decimal(0)
    return Calculated(
        fact_type=DERIVED_UNSUPPORTED_AMOUNT,
        kind=FactKind.MONEY,
        value=exposure * rate,
        expression=f"max({variance}, 0) * {rate}",
        calculation="exposure_at_contract_rate",
        currency=facts[FIELD_CONTRACT_RATE].currency,
        inputs={FIELD_CONTRACT_RATE: facts[FIELD_CONTRACT_RATE]},
    )


def _comparable_pair(
    left: ExtractedFact | None, right: ExtractedFact | None
) -> tuple[Decimal, Decimal, str | None] | None:
    """Two quantities and their shared unit, or ``None`` if they cannot be compared.

    Mismatched units are refused rather than coerced. There is no conversion table here and there
    should not be one until a real document needs it — a silent tonne-to-cubic-metre conversion is a
    fabricated density.
    """
    left_value = _numeric(left)
    right_value = _numeric(right)
    if left is None or right is None or left_value is None or right_value is None:
        return None
    if left.unit is not None and right.unit is not None and left.unit != right.unit:
        return None
    return left_value, right_value, left.unit or right.unit


# Calculations that need only facts from a single work item. Registered rather than called directly
# so adding one is a one-line change here and nothing else -- the same reason the rule registry
# exists.
CALCULATIONS: Final[dict[str, object]] = {
    DERIVED_BID_SECURITY_SHARE: compute_bid_security_share,
    DERIVED_QUANTITY_VARIANCE: compute_quantity_variance,
    DERIVED_REMAINING_CONTRACT_QUANTITY: compute_remaining_contract_quantity,
    DERIVED_RATE_VARIANCE: compute_rate_variance,
    DERIVED_UNSUPPORTED_AMOUNT: compute_unsupported_amount,
}


def compute_for_work_item(facts: list[ExtractedFact]) -> tuple[Calculated, ...]:
    """Run the payment-reconciliation calculations over one work item's facts.

    ``unsupported_amount`` runs last and consumes the variance the previous step produced, which is
    the point of the layer: a calculation may build on another calculation without either of them
    knowing what a rule will make of the result.
    """
    newest = _newest_by_type(facts)
    results: list[Calculated] = []
    for compute in (
        compute_quantity_variance,
        compute_remaining_contract_quantity,
        compute_rate_variance,
    ):
        calculated = compute(newest)
        if calculated is not None:
            results.append(calculated)

    variance = next(
        (item.value for item in results if item.fact_type == DERIVED_QUANTITY_VARIANCE), None
    )
    exposure = compute_unsupported_amount(newest, variance=variance)
    if exposure is not None:
        results.append(exposure)
    return tuple(results)


def _newest_by_type(facts: list[ExtractedFact]) -> dict[str, ExtractedFact]:
    newest: dict[str, ExtractedFact] = {}
    for fact in facts:
        current = newest.get(fact.fact_type)
        if current is None or fact.extractor_version > current.extractor_version:
            newest[fact.fact_type] = fact
    return newest


def compute_for_document(facts: list[ExtractedFact]) -> tuple[Calculated, ...]:
    """Run every single-document calculation over one document's facts.

    Facts are indexed by type, newest extractor version winning, so a calculation never mixes an old
    extraction with a new one.
    """
    newest = _newest_by_type(facts)
    results: list[Calculated] = []
    for compute in (compute_bid_security_share,):
        calculated = compute(newest)
        if calculated is not None:
            results.append(calculated)
    return tuple(results)
