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

from aedifex.extraction.tender_notice import TenderNotice
from aedifex.infrastructure.database.models import DerivedFact
from aedifex.verification.cross_document import (
    AGREEMENT_RULE_ID,
    SHARE_CONSISTENCY_RULE_ID,
    ProjectFacts,
    ProjectRuleResult,
    evaluate_derived_share_consistency,
    evaluate_fact_agreement,
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
    "NOT_SOURCED",
    "PROJECT_RULES",
    "RULES",
    "SHARE_CONSISTENCY_RULE_ID",
    "Outcome",
    "Rule",
    "RuleResult",
    "evaluate_all",
    "evaluate_bid_security",
    "evaluate_project",
]

# Rules take the notice plus keyword options. Only one option exists so far and only one rule reads
# it; a rule that does not care simply does not declare it. This is kept this plain deliberately --
# a dispatch layer for options nobody has asked for yet would be the premature generality this
# milestone is meant to avoid.
Rule = Callable[..., RuleResult]
ProjectRule = Callable[[ProjectFacts], ProjectRuleResult]

RULES: Final[Mapping[str, Rule]] = {
    BID_SECURITY_RULE_ID: evaluate_bid_security,
}


def evaluate_all(
    notice: TenderNotice,
    *,
    prescribed_share: Decimal | None = None,
    share: DerivedFact | None = None,
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
    """
    return tuple(
        RULES[rule_id](notice, prescribed_share=prescribed_share, share=share)
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
