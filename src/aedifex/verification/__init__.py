"""Deterministic verification: rules, and the registry that names them.

The registry exists so a rule is looked up rather than called directly at one site. That is the only
generalisation made here: the persona-agnostic shape this project is building toward is
``Artifact -> Fact -> Evidence -> Rule -> Finding``, and the seam that keeps it open is a mapping
from rule id to a callable, not an engine or a DSL. A future quantity-surveying check registers here
and inherits persistence, evidence linking, and the CLI for free.

Rules are keyed by id and carry their own version, because a verdict is only reproducible if you
know which version of which rule produced it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Final

from aedifex.extraction.applicability import ApplicableProvision
from aedifex.extraction.tender_notice import TenderNotice
from aedifex.infrastructure.database.models import DerivedFact
from aedifex.verification.bill_estimate import (
    BILL_ESTIMATE_RULE_ID,
    BILL_ESTIMATE_RULE_VERSION,
    evaluate_bill_against_estimate,
)
from aedifex.verification.bill_total import (
    BILL_TOTAL_RULE_ID,
    BILL_TOTAL_RULE_VERSION,
    evaluate_bill_total,
)
from aedifex.verification.cross_document import (
    AGREEMENT_RULE_ID,
    SHARE_CONSISTENCY_RULE_ID,
    ProjectFacts,
    ProjectRuleResult,
    evaluate_derived_share_consistency,
    evaluate_fact_agreement,
)
from aedifex.verification.reference_policy import (
    REFERENCE_BID_SECURITY_RULE_ID,
    REFERENCE_BID_SECURITY_RULE_VERSION,
    evaluate_bid_security_against_policy,
)
from aedifex.verification.rules import (
    BID_SECURITY_RULE_ID,
    BID_SECURITY_RULE_VERSION,
    NOT_SOURCED,
    Outcome,
    RuleResult,
    evaluate_bid_security,
)

__all__ = [
    "AGREEMENT_RULE_ID",
    "BID_SECURITY_RULE_ID",
    "BID_SECURITY_RULE_VERSION",
    "BILL_ESTIMATE_RULE_ID",
    "BILL_ESTIMATE_RULE_VERSION",
    "BILL_TOTAL_RULE_ID",
    "BILL_TOTAL_RULE_VERSION",
    "NOT_SOURCED",
    "PROJECT_RULES",
    "REFERENCE_BID_SECURITY_RULE_ID",
    "REFERENCE_BID_SECURITY_RULE_VERSION",
    "RULES",
    "SHARE_CONSISTENCY_RULE_ID",
    "Outcome",
    "Rule",
    "RuleResult",
    "evaluate_all",
    "evaluate_bid_security",
    "evaluate_bid_security_against_policy",
    "evaluate_bill_against_estimate",
    "evaluate_bill_total",
    "evaluate_project",
]

# Rules take the notice plus keyword options. Every rule is handed every option and absorbs the ones
# it does not read, which is why each declares ``**_unused``. Kept this plain deliberately: a
# dispatch layer that worked out which rule wants which option would be more machinery than two
# rules and two options can justify.
Rule = Callable[..., RuleResult]
ProjectRule = Callable[[ProjectFacts], ProjectRuleResult]

RULES: Final[Mapping[str, Rule]] = {
    BID_SECURITY_RULE_ID: evaluate_bid_security,
    BILL_ESTIMATE_RULE_ID: evaluate_bill_against_estimate,
    BILL_TOTAL_RULE_ID: evaluate_bill_total,
    REFERENCE_BID_SECURITY_RULE_ID: evaluate_bid_security_against_policy,
}


def evaluate_all(
    notice: TenderNotice,
    *,
    prescribed_share: Decimal | None = None,
    share: DerivedFact | None = None,
    refused_rows: int = 0,
    bill_total: DerivedFact | None = None,
    applicable: ApplicableProvision | None = None,
    required: DerivedFact | None = None,
) -> tuple[RuleResult, ...]:
    """Run every registered rule over one document's facts, in a stable order.

    Sorted by rule id rather than dictionary order, so two runs over the same document produce
    findings in the same sequence and a diff of two runs shows only real changes.

    Args:
        notice: The extracted facts.
        prescribed_share: An externally sourced bid-security rate, forwarded to the rules. Left
            unset, each rule uses whatever the document states about itself.
        share: The derived bid-security share for this document, produced by the calculation layer.
            Rules consume it rather than dividing again.
        refused_rows: How many table rows the extractor declined to return. A rule that sums rows
            needs this to know its sum is incomplete; every rule receives it and most ignore it.
        bill_total: The summed line amounts of this document's bill of quantities, produced by the
            calculation layer with one input row per line item.
        applicable: The reference provision selected for this document, or the recorded reason none
            was. Applicability is decided before the rules run, so a rule never searches for its own
            threshold.
        required: The amount that provision requires, from the calculation layer.
    """
    return tuple(
        RULES[rule_id](
            notice,
            prescribed_share=prescribed_share,
            share=share,
            refused_rows=refused_rows,
            bill_total=bill_total,
            applicable=applicable,
            required=required,
        )
        for rule_id in sorted(RULES)
    )


PROJECT_RULES: Final[Mapping[str, ProjectRule]] = {
    AGREEMENT_RULE_ID: evaluate_fact_agreement,
    SHARE_CONSISTENCY_RULE_ID: evaluate_derived_share_consistency,
}


def evaluate_project(project_facts: ProjectFacts) -> tuple[ProjectRuleResult, ...]:
    """Run every registered project rule, in a stable order.

    Both rules read the same project. One compares what the documents *state*, the other what the
    calculation layer *derived* from those statements — and both cite the rows they used, so two
    findings about one project never rest on different readings of it.
    """
    return tuple(PROJECT_RULES[rule_id](project_facts) for rule_id in sorted(PROJECT_RULES))
