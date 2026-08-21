"""Deterministic verification rules.

This module is why the project's rule reads "LLMs interpret evidence. Deterministic code verifies
evidence." Everything here is arithmetic on :class:`~decimal.Decimal` values that came from a named
span of a real document. No model is consulted and the same facts always produce the same verdict,
because a finding that cannot be reproduced cannot be defended.

**Where the threshold comes from matters as much as the arithmetic.** The obvious way to write the
first rule was to hardcode 2%, which is the share the first NHAI notice we read happened to state.
Reading further disproved it: a 145-page bid document in the same corpus prescribes 1% in its
Instructions to Bidders, clause 13.2. There is no single national rate to configure, and asserting
one from two documents would have been inventing policy — the same class of mistake as fabricating
source approval.

So the prescribed share is an **input**, and normally an extracted fact: a rate the document states
about itself, with a page and a span, which can be cited. When a document states none, the rule
measures the ratio and returns ``INCONCLUSIVE`` with ``expected = NOT SOURCED``. That is not a
failure of the document and must never be displayed as one — it is us declining to judge against a
threshold nobody sourced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Final

from aedifex.calculation.engine import DERIVED_BID_SECURITY_SHARE
from aedifex.extraction.tender_notice import (
    FIELD_BID_SECURITY,
    FIELD_ESTIMATED_COST,
    FIELD_PRESCRIBED_BID_SECURITY_SHARE,
    ExtractedField,
    TenderNotice,
)
from aedifex.infrastructure.database.models import DerivedFact, PolicyProvision

__all__ = [
    "BID_SECURITY_RULE_ID",
    "BID_SECURITY_RULE_VERSION",
    "BID_SECURITY_TOLERANCE",
    "NOT_SOURCED",
    "Outcome",
    "RuleResult",
    "evaluate_bid_security",
]

BID_SECURITY_RULE_ID: Final[str] = "bid_security_share_of_estimated_cost"
BID_SECURITY_RULE_VERSION: Final[str] = "1"

# Rendered as the expected value whenever no prescribed rate could be sourced. A sentinel rather
# than an empty string, so an interface cannot accidentally present "no threshold" as "threshold 0".
NOT_SOURCED: Final[str] = "NOT SOURCED"

# How far from the prescribed share still counts as agreement. Wide enough to absorb a notice that
# rounded its bid security to the nearest lakh: against an estimated cost of 8,46,49,969, a stated
# 16.93 Lacs is exact but 17 Lacs would be 2.008% and is plainly the same intent.
BID_SECURITY_TOLERANCE: Final[Decimal] = Decimal("0.001")

_PERCENT_PLACES: Final[Decimal] = Decimal("0.0001")


class Outcome(StrEnum):
    """What a rule can conclude. Stored as the ``outcome`` column verbatim."""

    # The suppression below is for ruff's S105 hardcoded-password heuristic, which fires on any
    # name containing "PASS". This is a verdict, not a credential.
    PASS = "pass"  # noqa: S105
    FAIL = "fail"
    REVIEW = "review"
    """Something a person should look at. Not a failure, and not a pass.

    Distinct from FAIL on purpose. A claim exceeding measured work may be an error, a timing
    difference, or a variation nobody has recorded yet — the rule can establish the discrepancy but
    not its cause, and calling that a failure asserts more than the evidence supports.
    """

    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class RuleResult:
    """One rule's verdict, the numbers that produced it, and the facts it read.

    ``detail`` holds every value as a string so the arithmetic can be redone by hand from the stored
    record alone. ``evidence`` maps a role name to the field that filled it, which is what lets a
    persisted finding point back at a page span.
    """

    rule_id: str
    rule_version: str
    outcome: Outcome
    summary: str
    expected: str
    observed: str
    detail: dict[str, str]
    evidence: dict[str, ExtractedField]
    derived_evidence: dict[str, DerivedFact] = field(default_factory=dict)
    """Computed values the rule relied on. Cited alongside the facts, never instead of them."""

    provision_evidence: dict[str, PolicyProvision] = field(default_factory=dict)
    """Reference provisions the rule applied — the clause a threshold came from.

    A third kind of citation because a threshold is a third kind of evidence. "The bid security is
    2% of the estimated cost" is not a measurement and not a calculation; it is a rule somebody
    else wrote down, and a finding that compares against it has to say where it read it.
    """


def _percent(value: Decimal) -> Decimal:
    return (value * 100).quantize(_PERCENT_PLACES, rounding=ROUND_HALF_UP)


def _inconclusive(
    summary: str,
    *,
    expected: str,
    observed: str,
    detail: dict[str, str],
    evidence: dict[str, ExtractedField],
    derived_evidence: dict[str, DerivedFact] | None = None,
) -> RuleResult:
    return RuleResult(
        derived_evidence=derived_evidence or {},
        rule_id=BID_SECURITY_RULE_ID,
        rule_version=BID_SECURITY_RULE_VERSION,
        outcome=Outcome.INCONCLUSIVE,
        summary=summary,
        expected=expected,
        observed=observed,
        detail=detail,
        evidence=evidence,
    )


def evaluate_bid_security(
    notice: TenderNotice,
    *,
    prescribed_share: Decimal | None = None,
    share: DerivedFact | None = None,
    **_unused: object,
) -> RuleResult:
    """Check a notice's bid security against the share it is required to be.

    **SUPERSEDED by** ``bid_security_matches_reference_policy`` (2026-08-20), which answers the
    same question against a threshold cited from an authority's own rulebook rather than one the
    document must state about itself. On the real corpus this rule returns INCONCLUSIVE where that
    one returns PASS, because a tender notice does not quote its own bid-security rate.

    **Deliberately still registered, not retired.** Six stored findings cite it, and a rule removed
    from the registry cannot re-derive the findings that reference it — which would break the
    reproducibility the whole pipeline exists to provide (FR-087). It also remains the only answer
    available for an authority whose rulebook has not been acquired: a document that states its own
    rate can still be judged here. Retire it when every authority in the corpus has a rulebook, and
    not before.

    Args:
        notice: The extracted facts.
        prescribed_share: The required share as a fraction, e.g. ``Decimal("0.01")`` for 1%.
            Overrides the rate extracted from the document. This parameter is the whole
            configuration seam — a caller who has sourced a rate elsewhere can supply it — and
            deliberately not a global setting, because the rate varies by tender.
        share: The derived bid-security share, produced by the calculation layer. Consumed rather
            than recomputed here.
        **_unused: Options other rules declare. Accepted and ignored, because the registry hands
            every rule the same keywords.

    Returns:
        ``PASS``/``FAIL`` when a rate was available, otherwise ``INCONCLUSIVE``. The observed share
        is reported in every case where it could be computed, so an unjudged document still yields a
        usable measurement.
    """
    cost = notice.field(FIELD_ESTIMATED_COST)
    security = notice.field(FIELD_BID_SECURITY)
    stated = notice.field(FIELD_PRESCRIBED_BID_SECURITY_SHARE)

    evidence: dict[str, ExtractedField] = {
        role: field
        for role, field in (
            (FIELD_ESTIMATED_COST, cost),
            (FIELD_BID_SECURITY, security),
            (FIELD_PRESCRIBED_BID_SECURITY_SHARE, stated),
        )
        if field is not None
    }

    missing = [
        name
        for name, field in ((FIELD_ESTIMATED_COST, cost), (FIELD_BID_SECURITY, security))
        if field is None or field.value is None
    ]
    if missing or cost is None or security is None or cost.value is None or security.value is None:
        return _inconclusive(
            f"Cannot compute the bid-security share: {', '.join(missing)} "
            f"{'was' if len(missing) == 1 else 'were'} not extracted from this document.",
            expected=NOT_SOURCED,
            observed="not computable",
            detail={"missing": ", ".join(missing)},
            evidence=evidence,
        )

    if cost.value <= 0:
        return _inconclusive(
            f"Estimated cost is {cost.value}, so a share of it is not a meaningful number.",
            expected=NOT_SOURCED,
            observed="not computable",
            detail={"estimated_cost": str(cost.value)},
            evidence=evidence,
        )

    # The division used to happen here. It now belongs to the calculation layer, so that the same
    # share can be consumed by the cross-document rule instead of being computed twice from the same
    # two numbers -- and so that the arithmetic is stored once, with its inputs, rather than living
    # only inside whichever rule needed it.
    if share is None or share.numeric_value is None:
        return _inconclusive(
            "The bid-security share has not been calculated for this document, so there is nothing "
            "to compare. Run the analysis so the calculation layer produces it.",
            expected=NOT_SOURCED,
            observed="not computable",
            detail={"estimated_cost": str(cost.value), "bid_security": str(security.value)},
            evidence=evidence,
        )

    observed_share = Decimal(share.numeric_value)
    observed_percent = _percent(observed_share)
    detail = {
        "estimated_cost": str(cost.value),
        "bid_security": str(security.value),
        "observed_share": str(observed_share),
        "observed_percent": str(observed_percent),
        "estimated_cost_literal": cost.literal,
        "bid_security_literal": security.literal,
        # The arithmetic, so the ratio can be redone by hand from the stored record alone.
        "share_expression": share.expression,
        "share_calculation": f"{share.calculation} v{share.calculation_version}",
    }

    required = (
        prescribed_share if prescribed_share is not None else (stated.value if stated else None)
    )
    if required is None:
        return _inconclusive(
            f"Bid security of {security.literal} is {observed_percent}% of the estimated cost "
            f"{cost.literal}. This document states no required share, and none was supplied, so "
            f"the ratio is measured but not judged.",
            expected=NOT_SOURCED,
            observed=f"{observed_percent}%",
            detail=detail,
            evidence=evidence,
            derived_evidence={DERIVED_BID_SECURITY_SHARE: share},
        )

    source = (
        "supplied by the caller"
        if prescribed_share is not None
        else (
            f"stated by the document itself on page {stated.evidence.page}"
            if stated is not None
            else "unknown"
        )
    )
    deviation = abs(observed_share - required)
    agrees = deviation <= BID_SECURITY_TOLERANCE
    detail |= {
        "required_share": str(required),
        "required_percent": str(_percent(required)),
        "deviation_percentage_points": str(_percent(deviation)),
        "tolerance": str(BID_SECURITY_TOLERANCE),
        "required_share_source": source,
    }

    summary = (
        f"Bid security of {security.literal} is {observed_percent}% of the estimated cost "
        f"{cost.literal}, against a required {_percent(required)}% ({source}) — "
        + (
            "which agrees."
            if agrees
            else f"a difference of {_percent(deviation)} percentage points."
        )
    )

    return RuleResult(
        rule_id=BID_SECURITY_RULE_ID,
        rule_version=BID_SECURITY_RULE_VERSION,
        outcome=Outcome.PASS if agrees else Outcome.FAIL,
        summary=summary,
        expected=f"{_percent(required)}% of estimated cost",
        observed=f"{observed_percent}%",
        detail=detail,
        evidence=evidence,
        derived_evidence={DERIVED_BID_SECURITY_SHARE: share},
    )
