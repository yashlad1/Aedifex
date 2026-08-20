"""Payment reconciliation: comparing what was contracted, measured, and claimed.

Three rules over one work item, and each is almost trivial because the calculation layer has already
done the arithmetic. That is the point of the architecture rather than an accident of these rules
being simple: a rule's job is to say what a number *means*, and it can only stay small if computing
the number is somebody else's job.

**All three return REVIEW rather than FAIL.** A cumulative claim exceeding measured work may be an
error, a timing difference between measurement and certification, or a variation nobody has recorded
yet. The rule can establish the discrepancy but not its cause, and calling it a failure would assert
more than the evidence supports. REVIEW routes a real discrepancy to a person without pretending to
have judged it.

Every finding cites facts from all three documents plus the derived values, so a reviewer can redo
the comparison by hand from the citation alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from aedifex.calculation.engine import (
    DERIVED_QUANTITY_VARIANCE,
    DERIVED_RATE_VARIANCE,
    DERIVED_UNSUPPORTED_AMOUNT,
)
from aedifex.extraction.spreadsheet import (
    FIELD_CLAIMED_RATE,
    FIELD_CONTRACT_RATE,
    FIELD_CUMULATIVE_CLAIM_QUANTITY,
    FIELD_MEASURED_QUANTITY,
    FIELD_PREVIOUS_CERTIFIED_QUANTITY,
)
from aedifex.infrastructure.database.models import DerivedFact, ExtractedFact, WorkItem
from aedifex.verification.rules import NOT_SOURCED, Outcome

__all__ = [
    "CLAIM_WITHIN_MEASURED_RULE_ID",
    "CUMULATIVE_NOT_REGRESSED_RULE_ID",
    "RATE_MATCHES_CONTRACT_RULE_ID",
    "RECONCILIATION_RULES",
    "WorkItemFacts",
    "WorkItemRuleResult",
    "evaluate_claim_within_measured",
    "evaluate_cumulative_not_regressed",
    "evaluate_rate_matches_contract",
    "evaluate_work_item",
]

CLAIM_WITHIN_MEASURED_RULE_ID: Final[str] = "claim_within_measured_quantity"
RATE_MATCHES_CONTRACT_RULE_ID: Final[str] = "claimed_rate_matches_contract_rate"
CUMULATIVE_NOT_REGRESSED_RULE_ID: Final[str] = "cumulative_claim_not_below_previous_certified"
RULE_VERSION: Final[str] = "1"


@dataclass(frozen=True, slots=True)
class WorkItemFacts:
    """Everything known about one item of work, from every document that mentions it."""

    work_item: WorkItem
    facts: dict[str, ExtractedFact]
    derived: dict[str, DerivedFact]
    filenames: dict[str, str]
    """Document id (as string) to filename, so a summary can name where a value came from."""

    def where(self, fact: ExtractedFact | DerivedFact | None) -> str:
        if fact is None:
            return "unknown"
        document_id = getattr(fact, "document_id", None)
        name = self.filenames.get(str(document_id), "derived")
        cell = getattr(fact, "snippet", None)
        return f"{name} {cell}" if cell else name


@dataclass(frozen=True, slots=True)
class WorkItemRuleResult:
    """One rule's verdict about one work item, with the evidence it read."""

    rule_id: str
    rule_version: str
    work_item_id: str
    outcome: Outcome
    summary: str
    expected: str
    observed: str
    detail: dict[str, str]
    evidence: dict[str, ExtractedFact]
    derived_evidence: dict[str, DerivedFact]


def _plain(value: Decimal | None) -> str:
    """A decimal without exponent notation or trailing zeros, for a human-readable summary.

    The stored value keeps its full scale — a finding's ``detail`` and the derived fact both hold
    the exact number. This is presentation only, and it exists because "exceeds by 50.0000000000
    m3" reads like a measurement precision nobody claimed.
    """
    if value is None:
        return "-"
    return f"{value.normalize():f}"


def _inconclusive(
    rule_id: str,
    item: WorkItemFacts,
    missing: list[str],
) -> WorkItemRuleResult:
    return WorkItemRuleResult(
        rule_id=rule_id,
        rule_version=RULE_VERSION,
        work_item_id=str(item.work_item.id),
        outcome=Outcome.INCONCLUSIVE,
        summary=(
            f"Item {item.work_item.item_identifier}: cannot check — "
            f"{', '.join(missing)} not available."
        ),
        expected=NOT_SOURCED,
        observed="not computable",
        detail={"missing": ", ".join(missing)},
        evidence={},
        derived_evidence={},
    )


def evaluate_claim_within_measured(item: WorkItemFacts) -> WorkItemRuleResult:
    """Rule 1: the cumulative claim must not exceed the measured quantity.

    The core payment check. Reads the variance the calculation layer produced rather than
    subtracting again, and reports the money at risk from ``unsupported_amount`` when available — a
    quantity discrepancy without its value is hard for a reviewer to prioritise.
    """
    claimed = item.facts.get(FIELD_CUMULATIVE_CLAIM_QUANTITY)
    measured = item.facts.get(FIELD_MEASURED_QUANTITY)
    variance = item.derived.get(DERIVED_QUANTITY_VARIANCE)

    missing = [
        name
        for name, value in (
            (FIELD_CUMULATIVE_CLAIM_QUANTITY, claimed),
            (FIELD_MEASURED_QUANTITY, measured),
            (DERIVED_QUANTITY_VARIANCE, variance),
        )
        if value is None
    ]
    if missing or claimed is None or measured is None or variance is None:
        return _inconclusive(CLAIM_WITHIN_MEASURED_RULE_ID, item, missing)

    exposure = item.derived.get(DERIVED_UNSUPPORTED_AMOUNT)
    unit = item.work_item.unit or ""
    over = Decimal(variance.numeric_value or 0)

    evidence = {
        FIELD_CUMULATIVE_CLAIM_QUANTITY: claimed,
        FIELD_MEASURED_QUANTITY: measured,
    }
    derived_evidence = {DERIVED_QUANTITY_VARIANCE: variance}
    if exposure is not None:
        derived_evidence[DERIVED_UNSUPPORTED_AMOUNT] = exposure
    detail = {
        "cumulative_claim_quantity": str(claimed.numeric_value),
        "measured_quantity": str(measured.numeric_value),
        "quantity_variance": str(over),
        "unit": unit,
        "variance_expression": variance.expression,
    }
    if exposure is not None:
        detail["unsupported_amount"] = str(exposure.numeric_value)
        detail["unsupported_amount_expression"] = exposure.expression

    if over <= 0:
        return WorkItemRuleResult(
            rule_id=CLAIM_WITHIN_MEASURED_RULE_ID,
            rule_version=RULE_VERSION,
            work_item_id=str(item.work_item.id),
            outcome=Outcome.PASS,
            summary=(
                f"Item {item.work_item.item_identifier}: cumulative claim "
                f"{_plain(claimed.numeric_value)} {unit} is within the measured "
                f"{_plain(measured.numeric_value)} {unit}."
            ),
            expected="cumulative claim at most the measured quantity",
            observed=f"{_plain(over)} {unit}".strip(),
            detail=detail,
            evidence=evidence,
            derived_evidence=derived_evidence,
        )

    money = (
        f" Potential unsupported amount {_plain(exposure.numeric_value)} "
        f"{exposure.currency or ''}".rstrip() + "."
        if exposure is not None and exposure.numeric_value
        else ""
    )
    return WorkItemRuleResult(
        rule_id=CLAIM_WITHIN_MEASURED_RULE_ID,
        rule_version=RULE_VERSION,
        work_item_id=str(item.work_item.id),
        outcome=Outcome.REVIEW,
        summary=(
            f"Item {item.work_item.item_identifier}: cumulative claim "
            f"{_plain(claimed.numeric_value)} {unit} exceeds the measured "
            f"{_plain(measured.numeric_value)} {unit} by {_plain(over)} {unit}.{money} "
            f"This may be a measurement not yet taken up, an unrecorded variation, or an "
            f"overclaim; the documents do not say which."
        ),
        expected="cumulative claim at most the measured quantity",
        observed=f"+{_plain(over)} {unit}".strip(),
        detail=detail,
        evidence=evidence,
        derived_evidence=derived_evidence,
    )


def evaluate_rate_matches_contract(item: WorkItemFacts) -> WorkItemRuleResult:
    """Rule 2: the claimed rate must equal the contracted rate.

    No variation support in this milestone, which is why a difference is REVIEW and not FAIL: an
    approved variation is exactly the thing that would make a differing rate correct, and we cannot
    yet see one.
    """
    claimed = item.facts.get(FIELD_CLAIMED_RATE)
    contracted = item.facts.get(FIELD_CONTRACT_RATE)
    variance = item.derived.get(DERIVED_RATE_VARIANCE)

    missing = [
        name
        for name, value in (
            (FIELD_CLAIMED_RATE, claimed),
            (FIELD_CONTRACT_RATE, contracted),
            (DERIVED_RATE_VARIANCE, variance),
        )
        if value is None
    ]
    if missing or claimed is None or contracted is None or variance is None:
        return _inconclusive(RATE_MATCHES_CONTRACT_RULE_ID, item, missing)

    difference = Decimal(variance.numeric_value or 0)
    currency = contracted.currency or ""
    detail = {
        "claimed_rate": str(claimed.numeric_value),
        "contract_rate": str(contracted.numeric_value),
        "rate_variance": str(difference),
        "variance_expression": variance.expression,
    }
    evidence = {FIELD_CLAIMED_RATE: claimed, FIELD_CONTRACT_RATE: contracted}
    derived_evidence = {DERIVED_RATE_VARIANCE: variance}

    if difference == 0:
        return WorkItemRuleResult(
            rule_id=RATE_MATCHES_CONTRACT_RULE_ID,
            rule_version=RULE_VERSION,
            work_item_id=str(item.work_item.id),
            outcome=Outcome.PASS,
            summary=(
                f"Item {item.work_item.item_identifier}: claimed rate "
                f"{_plain(claimed.numeric_value)} {currency} matches the contracted rate."
            ),
            expected="claimed rate equal to contracted rate",
            observed=f"0 {currency}".strip(),
            detail=detail,
            evidence=evidence,
            derived_evidence=derived_evidence,
        )

    direction = "above" if difference > 0 else "below"
    return WorkItemRuleResult(
        rule_id=RATE_MATCHES_CONTRACT_RULE_ID,
        rule_version=RULE_VERSION,
        work_item_id=str(item.work_item.id),
        outcome=Outcome.REVIEW,
        summary=(
            f"Item {item.work_item.item_identifier}: claimed rate {_plain(claimed.numeric_value)} "
            f"{currency} is {_plain(abs(difference))} {currency} {direction} the contracted "
            f"{_plain(contracted.numeric_value)} {currency}. No approved variation is visible "
            f"to this pipeline, which does not yet read variation orders."
        ),
        expected="claimed rate equal to contracted rate",
        observed=f"{'+' if difference > 0 else ''}{_plain(difference)} {currency}".strip(),
        detail=detail,
        evidence=evidence,
        derived_evidence=derived_evidence,
    )


def evaluate_cumulative_not_regressed(item: WorkItemFacts) -> WorkItemRuleResult:
    """Rule 3: the cumulative claim must not fall below what was already certified.

    A consistency check on cumulative state rather than on the work itself. A running bill is
    cumulative by construction, so a cumulative figure below the previously certified one means the
    bill contradicts its own history — which is a arithmetic or transcription problem, not a
    site one.
    """
    cumulative = item.facts.get(FIELD_CUMULATIVE_CLAIM_QUANTITY)
    previous = item.facts.get(FIELD_PREVIOUS_CERTIFIED_QUANTITY)

    missing = [
        name
        for name, value in (
            (FIELD_CUMULATIVE_CLAIM_QUANTITY, cumulative),
            (FIELD_PREVIOUS_CERTIFIED_QUANTITY, previous),
        )
        if value is None
    ]
    if missing or cumulative is None or previous is None:
        return _inconclusive(CUMULATIVE_NOT_REGRESSED_RULE_ID, item, missing)

    cumulative_value = Decimal(cumulative.numeric_value or 0)
    previous_value = Decimal(previous.numeric_value or 0)
    unit = item.work_item.unit or ""
    detail = {
        "cumulative_claim_quantity": str(cumulative_value),
        "previous_certified_quantity": str(previous_value),
    }
    evidence = {
        FIELD_CUMULATIVE_CLAIM_QUANTITY: cumulative,
        FIELD_PREVIOUS_CERTIFIED_QUANTITY: previous,
    }

    if cumulative_value >= previous_value:
        return WorkItemRuleResult(
            rule_id=CUMULATIVE_NOT_REGRESSED_RULE_ID,
            rule_version=RULE_VERSION,
            work_item_id=str(item.work_item.id),
            outcome=Outcome.PASS,
            summary=(
                f"Item {item.work_item.item_identifier}: cumulative claim "
                f"{_plain(cumulative_value)} {unit} is at or above the "
                f"{_plain(previous_value)} {unit} previously certified."
            ),
            expected="cumulative claim at least the previously certified quantity",
            observed=f"{_plain(cumulative_value - previous_value)} {unit}".strip(),
            detail=detail,
            evidence=evidence,
            derived_evidence={},
        )

    return WorkItemRuleResult(
        rule_id=CUMULATIVE_NOT_REGRESSED_RULE_ID,
        rule_version=RULE_VERSION,
        work_item_id=str(item.work_item.id),
        outcome=Outcome.REVIEW,
        summary=(
            f"Item {item.work_item.item_identifier}: cumulative claim "
            f"{_plain(cumulative_value)} {unit} is below the {_plain(previous_value)} {unit} "
            f"already certified. A cumulative figure cannot decrease, so this bill contradicts "
            f"its own history."
        ),
        expected="cumulative claim at least the previously certified quantity",
        observed=f"{_plain(cumulative_value - previous_value)} {unit}".strip(),
        detail=detail,
        evidence=evidence,
        derived_evidence={},
    )


RECONCILIATION_RULES: Final[dict[str, object]] = {
    CLAIM_WITHIN_MEASURED_RULE_ID: evaluate_claim_within_measured,
    RATE_MATCHES_CONTRACT_RULE_ID: evaluate_rate_matches_contract,
    CUMULATIVE_NOT_REGRESSED_RULE_ID: evaluate_cumulative_not_regressed,
}


def evaluate_work_item(item: WorkItemFacts) -> tuple[WorkItemRuleResult, ...]:
    """Run every reconciliation rule over one work item, in a stable order."""
    return (
        evaluate_claim_within_measured(item),
        evaluate_cumulative_not_regressed(item),
        evaluate_rate_matches_contract(item),
    )
