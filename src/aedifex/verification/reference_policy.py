"""Judging a tender against a rate schedule somebody else published.

The first rule whose threshold comes from a **different document than the one being judged**, and
the reason the applicability machinery exists. The path is:

.. code-block:: text

    project estimated cost                    (tender, page 6)
      + clause 4.14.1 of the NHAI Works Manual (reference, page 79)
      -> select the applicable cost band
      -> derive the required bid security
      -> compare against what the tender states
      -> PASS / FAIL / INCONCLUSIVE

Every existing rule reads facts from one document, or compares documents of one project. This one
reaches across an authority's rulebook into a tender, which is exactly the access
``docs/adr/0014-reference-data-by-explicit-applicability.md`` said must be explicit and
evidence-backed rather than global. It is, on both sides: the authority is read from the manual's
own text, and the band is matched against the tender's own stated cost.

**INCONCLUSIVE is the common answer and is not a failure.** No provision extracted, a cost outside
every band, or a cost inside two bands at once all mean the same thing — nobody has established a
threshold, so nothing is judged. Only a sourced threshold produces a verdict, which is the rule this
project already settled when the bid-security rate turned out to differ between two real tenders.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from aedifex.calculation.engine import DERIVED_REQUIRED_BID_SECURITY
from aedifex.extraction.applicability import ApplicableProvision
from aedifex.extraction.tender_notice import (
    FIELD_BID_SECURITY,
    FIELD_ESTIMATED_COST,
    ExtractedField,
    TenderNotice,
)
from aedifex.infrastructure.database.models import DerivedFact, PolicyProvision
from aedifex.verification.rules import NOT_SOURCED, Outcome, RuleResult

__all__ = [
    "REFERENCE_BID_SECURITY_RULE_ID",
    "REFERENCE_BID_SECURITY_RULE_VERSION",
    "REFERENCE_BID_SECURITY_TOLERANCE",
    "evaluate_bid_security_against_policy",
]

REFERENCE_BID_SECURITY_RULE_ID: Final[str] = "bid_security_matches_reference_policy"
REFERENCE_BID_SECURITY_RULE_VERSION: Final[str] = "1"

# One rupee, and the rounding it absorbs is documented rather than assumed. Clause 4.14.1 applied to
# the real tender gives 2% of Rs 84,649,969 = Rs 1,692,999.38, and the tender states Rs 16.93 Lacs =
# Rs 1,693,000 — the same figure rounded up to the whole rupee. A tolerance of a rupee accepts that
# and nothing larger: the next-coarsest plausible rounding, to the nearest thousand, would be Rs 620
# away and must not pass silently.
REFERENCE_BID_SECURITY_TOLERANCE: Final[Decimal] = Decimal("1.00")

_PAISE: Final[Decimal] = Decimal("0.01")


def _money(value: Decimal) -> str:
    return str(value.quantize(_PAISE, rounding=ROUND_HALF_UP))


def _result(
    outcome: Outcome,
    summary: str,
    *,
    expected: str,
    observed: str,
    detail: dict[str, str],
    evidence: dict[str, ExtractedField],
    derived_evidence: dict[str, DerivedFact] | None = None,
    provision_evidence: dict[str, PolicyProvision] | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=REFERENCE_BID_SECURITY_RULE_ID,
        rule_version=REFERENCE_BID_SECURITY_RULE_VERSION,
        outcome=outcome,
        summary=summary,
        expected=expected,
        observed=observed,
        detail=detail,
        evidence=evidence,
        derived_evidence=derived_evidence or {},
        provision_evidence=provision_evidence or {},
    )


def evaluate_bid_security_against_policy(
    notice: TenderNotice,
    *,
    applicable: ApplicableProvision | None = None,
    required: DerivedFact | None = None,
    **_unused: object,
) -> RuleResult:
    """Compare a tender's bid security against the amount a reference provision requires.

    Args:
        notice: The tender's extracted facts.
        applicable: The provision selected for this document, or the recorded reason none was.
            Carries its own explanation so an INCONCLUSIVE can say *why* rather than just that.
        required: The amount the provision requires, from the calculation layer. Consumed rather
            than recomputed: it cites both the cost fact and the clause, so citing it makes the
            finding unfold into two documents.
        **_unused: Options other rules declare.
    """
    cost = notice.field(FIELD_ESTIMATED_COST)
    security = notice.field(FIELD_BID_SECURITY)
    evidence: dict[str, ExtractedField] = {
        role: field
        for role, field in ((FIELD_ESTIMATED_COST, cost), (FIELD_BID_SECURITY, security))
        if field is not None
    }

    if cost is None or cost.value is None:
        return _result(
            Outcome.INCONCLUSIVE,
            "This document states no estimated cost, so no cost band can be selected and no "
            "required bid security can be derived.",
            expected=NOT_SOURCED,
            observed="no estimated cost",
            detail={},
            evidence=evidence,
        )

    if applicable is None or not applicable.resolved or applicable.provision is None:
        reason = applicable.reason if applicable is not None else "no provision was looked up"
        considered = applicable.considered if applicable is not None else ()
        return _result(
            Outcome.INCONCLUSIVE,
            f"No reference provision could be applied to this document: {reason}. The estimated "
            f"cost is measured but not judged.",
            expected=NOT_SOURCED,
            observed=_money(cost.value),
            detail={
                "estimated_cost": _money(cost.value),
                "reason": reason,
                "provisions_considered": str(len(considered)),
            },
            evidence=evidence,
            provision_evidence={
                f"{provision.provision_type}:{provision.clause}": provision
                for provision in considered
            },
        )

    provision = applicable.provision
    cited = {f"{provision.provision_type}:{provision.clause}": provision}

    if required is None or required.numeric_value is None:
        return _result(
            Outcome.INCONCLUSIVE,
            f"Clause {provision.clause} applies, but the required amount was not calculated, so "
            f"there is nothing to compare against.",
            expected=NOT_SOURCED,
            observed=_money(cost.value),
            detail={"clause": provision.clause, "estimated_cost": _money(cost.value)},
            evidence=evidence,
            provision_evidence=cited,
        )

    need = Decimal(required.numeric_value)
    derived = {DERIVED_REQUIRED_BID_SECURITY: required}
    share_text = f"{Decimal(provision.share) * 100}%" if provision.share is not None else "unstated"
    detail = {
        "clause": provision.clause,
        "authority": provision.authority,
        "prescribed_share": share_text,
        "band_from": _money(Decimal(provision.applies_from)) if provision.applies_from else "0.00",
        "band_to": (
            _money(Decimal(provision.applies_to_max)) if provision.applies_to_max else "unbounded"
        ),
        "cap": _money(Decimal(provision.cap_amount)) if provision.cap_amount else "none",
        "estimated_cost": _money(cost.value),
        "required_bid_security": _money(need),
        "tolerance": str(REFERENCE_BID_SECURITY_TOLERANCE),
        "applicability": applicable.reason,
    }

    if security is None or security.value is None:
        return _result(
            Outcome.INCONCLUSIVE,
            f"Clause {provision.clause} requires bid security of {_money(need)} "
            f"({share_text} of {_money(cost.value)}), but this document states no bid security to "
            f"compare against it.",
            expected=_money(need),
            observed="not stated",
            detail=detail,
            evidence=evidence,
            derived_evidence=derived,
            provision_evidence=cited,
        )

    difference = Decimal(security.value) - need
    detail["stated_bid_security"] = _money(Decimal(security.value))
    detail["difference"] = _money(difference)

    if abs(difference) <= REFERENCE_BID_SECURITY_TOLERANCE:
        return _result(
            Outcome.PASS,
            f"Bid security of {security.literal} ({_money(Decimal(security.value))}) matches the "
            f"{share_text} required by clause {provision.clause} of the "
            f"{provision.authority.upper()} rulebook for a contract of {_money(cost.value)}, "
            f"which is {_money(need)} — within {REFERENCE_BID_SECURITY_TOLERANCE}.",
            expected=_money(need),
            observed=_money(Decimal(security.value)),
            detail=detail,
            evidence=evidence,
            derived_evidence=derived,
            provision_evidence=cited,
        )

    direction = "above" if difference > 0 else "below"
    return _result(
        Outcome.FAIL,
        f"Bid security of {security.literal} ({_money(Decimal(security.value))}) is "
        f"{_money(abs(difference))} {direction} the {_money(need)} that clause {provision.clause} "
        f"requires — {share_text} of the stated estimated cost {_money(cost.value)}. The threshold "
        f"is cited, not configured: it comes from page {provision.page} of the reference document.",
        expected=_money(need),
        observed=_money(Decimal(security.value)),
        detail=detail,
        evidence=evidence,
        derived_evidence=derived,
        provision_evidence=cited,
    )
