"""What Aedifex knows how to talk about: fact types, derived facts, relationships, rules, findings.

**Metadata only.** This describes the vocabulary; it does not interpret it. There is no DSL here,
no ontology engine and no dispatch — a rule is registered in :mod:`aedifex.verification`, a
calculation in :mod:`aedifex.calculation.engine`, and this module says what those things *are* so a
person or an API client can find out without reading the source.

The reason to have it at all is that the vocabulary has become large enough to be worth listing, and
scattered enough that listing it is the only way to see it whole. A fact type is a string in an
extractor, a column value in the database, and a key in an API response; nothing until now stated
which strings are legitimate or what they mean.

Kept honest by a test asserting every registered type is one the code can actually produce, so this
cannot drift into documenting features that do not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from aedifex.calculation.engine import (
    DERIVED_BID_SECURITY_SHARE,
    DERIVED_BILL_ITEMS_TOTAL,
    DERIVED_QUANTITY_VARIANCE,
    DERIVED_RATE_VARIANCE,
    DERIVED_REMAINING_CONTRACT_QUANTITY,
    DERIVED_REQUIRED_BID_SECURITY,
    DERIVED_UNSUPPORTED_AMOUNT,
)
from aedifex.domain.evidence import (
    DocumentVersionState,
    FactKind,
    FactOrigin,
    RelationshipType,
)
from aedifex.extraction.pdf_boq import FIELD_LINE_AMOUNT, FIELD_STATED_BILL_TOTAL
from aedifex.extraction.spreadsheet import (
    FIELD_CLAIMED_RATE,
    FIELD_CONTRACT_RATE,
    FIELD_CONTRACTED_QUANTITY,
    FIELD_CUMULATIVE_CLAIM_QUANTITY,
    FIELD_CURRENT_CLAIM_QUANTITY,
    FIELD_ITEM_DESCRIPTION,
    FIELD_ITEM_IDENTIFIER,
    FIELD_MEASURED_QUANTITY,
    FIELD_PREVIOUS_CERTIFIED_QUANTITY,
    FIELD_PROJECT_REFERENCE,
)
from aedifex.extraction.tender_notice import (
    FIELD_BID_SECURITY,
    FIELD_DOCUMENT_DATE,
    FIELD_ESTIMATED_COST,
    FIELD_NIT_NUMBER,
    FIELD_PRESCRIBED_BID_SECURITY_SHARE,
)
from aedifex.verification.bill_estimate import BILL_ESTIMATE_RULE_ID
from aedifex.verification.bill_total import BILL_TOTAL_RULE_ID
from aedifex.verification.cross_document import (
    AGREEMENT_RULE_ID,
    SHARE_CONSISTENCY_RULE_ID,
)
from aedifex.verification.reconciliation import (
    CLAIM_WITHIN_MEASURED_RULE_ID,
    CUMULATIVE_NOT_REGRESSED_RULE_ID,
    RATE_MATCHES_CONTRACT_RULE_ID,
    UNAMBIGUOUS_EVIDENCE_RULE_ID,
)
from aedifex.verification.reference_policy import REFERENCE_BID_SECURITY_RULE_ID
from aedifex.verification.rules import BID_SECURITY_RULE_ID, Outcome

__all__ = [
    "DOCUMENT_VERSION_STATES",
    "FACT_TYPES",
    "FINDING_OUTCOMES",
    "RELATIONSHIP_TYPES",
    "RULE_TYPES",
    "FactTypeInfo",
    "FindingOutcomeInfo",
    "RelationshipTypeInfo",
    "RuleTypeInfo",
]


@dataclass(frozen=True, slots=True)
class FactTypeInfo:
    """One kind of value the system can hold, extracted or derived."""

    fact_type: str
    kind: FactKind
    origin: FactOrigin
    description: str
    produced_by: str
    inputs: tuple[str, ...] = ()
    """For derived facts, the fact types the calculation consumes."""


@dataclass(frozen=True, slots=True)
class RelationshipTypeInfo:
    relationship_type: RelationshipType
    description: str
    derivable: bool
    """Whether anything currently establishes it, or whether it is declared vocabulary only."""


@dataclass(frozen=True, slots=True)
class RuleTypeInfo:
    rule_id: str
    scope: str
    """``document`` or ``project``."""

    description: str
    consumes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FindingOutcomeInfo:
    outcome: Outcome
    description: str


FACT_TYPES: Final[tuple[FactTypeInfo, ...]] = (
    FactTypeInfo(
        fact_type=FIELD_NIT_NUMBER,
        kind=FactKind.IDENTIFIER,
        origin=FactOrigin.EXTRACTED,
        description="The tender reference a document states. Also the project key.",
        produced_by="aedifex.extraction.tender_notice",
    ),
    FactTypeInfo(
        fact_type=FIELD_ESTIMATED_COST,
        kind=FactKind.MONEY,
        origin=FactOrigin.EXTRACTED,
        description="The employer's estimate of the contract value.",
        produced_by="aedifex.extraction.tender_notice",
    ),
    FactTypeInfo(
        fact_type=FIELD_BID_SECURITY,
        kind=FactKind.MONEY,
        origin=FactOrigin.EXTRACTED,
        description="The bid security or earnest money a bidder must furnish.",
        produced_by="aedifex.extraction.tender_notice",
    ),
    FactTypeInfo(
        fact_type=FIELD_PRESCRIBED_BID_SECURITY_SHARE,
        kind=FactKind.PERCENTAGE,
        origin=FactOrigin.EXTRACTED,
        description=(
            "The bid-security rate a document prescribes for itself, read from its Instructions "
            "to Bidders. A threshold that is evidence rather than configuration."
        ),
        produced_by="aedifex.extraction.tender_notice",
    ),
    FactTypeInfo(
        fact_type=FIELD_DOCUMENT_DATE,
        kind=FactKind.DATE,
        origin=FactOrigin.EXTRACTED,
        description="The date a document carries beside its own reference. Orders a project.",
        produced_by="aedifex.extraction.tender_notice",
    ),
    FactTypeInfo(
        fact_type=DERIVED_BID_SECURITY_SHARE,
        kind=FactKind.PERCENTAGE,
        origin=FactOrigin.DERIVED,
        description=(
            "Bid security divided by estimated cost. Consumed by two rules that reach different "
            "kinds of conclusion from it, which is the point of storing it once."
        ),
        produced_by="aedifex.calculation.engine",
        inputs=(FIELD_ESTIMATED_COST, FIELD_BID_SECURITY),
    ),
    # --- Post-award construction records: bill of quantities, measurement, running bill ---
    FactTypeInfo(
        fact_type=FIELD_PROJECT_REFERENCE,
        kind=FactKind.IDENTIFIER,
        origin=FactOrigin.EXTRACTED,
        description="The project or contract reference a record quotes. A project key.",
        produced_by="aedifex.extraction.spreadsheet",
    ),
    FactTypeInfo(
        fact_type=FIELD_ITEM_IDENTIFIER,
        kind=FactKind.IDENTIFIER,
        origin=FactOrigin.EXTRACTED,
        description=(
            "The item number of a work item, e.g. 4.7.2. What connects a bill of quantities, a "
            "measurement and a claim to the same piece of work."
        ),
        produced_by="aedifex.extraction.spreadsheet",
    ),
    FactTypeInfo(
        fact_type=FIELD_ITEM_DESCRIPTION,
        kind=FactKind.TEXT,
        origin=FactOrigin.EXTRACTED,
        description="What the work item is. Descriptive; never used for matching.",
        produced_by="aedifex.extraction.spreadsheet",
    ),
    FactTypeInfo(
        fact_type=FIELD_CONTRACTED_QUANTITY,
        kind=FactKind.QUANTITY,
        origin=FactOrigin.EXTRACTED,
        description="The quantity the contract provides for, from the bill of quantities.",
        produced_by="aedifex.extraction.spreadsheet",
    ),
    FactTypeInfo(
        fact_type=FIELD_CONTRACT_RATE,
        kind=FactKind.MONEY,
        origin=FactOrigin.EXTRACTED,
        description="The agreed unit rate, from the bill of quantities.",
        produced_by="aedifex.extraction.spreadsheet",
    ),
    FactTypeInfo(
        fact_type=FIELD_MEASURED_QUANTITY,
        kind=FactKind.QUANTITY,
        origin=FactOrigin.EXTRACTED,
        description="The quantity actually measured on site, from the measurement book.",
        produced_by="aedifex.extraction.spreadsheet",
    ),
    FactTypeInfo(
        fact_type=FIELD_PREVIOUS_CERTIFIED_QUANTITY,
        kind=FactKind.QUANTITY,
        origin=FactOrigin.EXTRACTED,
        description="What earlier bills already certified. Bounds a cumulative claim from below.",
        produced_by="aedifex.extraction.spreadsheet",
    ),
    FactTypeInfo(
        fact_type=FIELD_CURRENT_CLAIM_QUANTITY,
        kind=FactKind.QUANTITY,
        origin=FactOrigin.EXTRACTED,
        description="The quantity claimed in this bill alone.",
        produced_by="aedifex.extraction.spreadsheet",
    ),
    FactTypeInfo(
        fact_type=FIELD_CUMULATIVE_CLAIM_QUANTITY,
        kind=FactKind.QUANTITY,
        origin=FactOrigin.EXTRACTED,
        description="The total claimed to date. What measured work is compared against.",
        produced_by="aedifex.extraction.spreadsheet",
    ),
    FactTypeInfo(
        fact_type=FIELD_CLAIMED_RATE,
        kind=FactKind.MONEY,
        origin=FactOrigin.EXTRACTED,
        description=(
            "The unit rate being claimed. Labelled 'Rate' in a running bill exactly as the "
            "contracted rate is in a bill of quantities, so the document type disambiguates it."
        ),
        produced_by="aedifex.extraction.spreadsheet",
    ),
    FactTypeInfo(
        fact_type=FIELD_LINE_AMOUNT,
        kind=FactKind.MONEY,
        origin=FactOrigin.EXTRACTED,
        description=(
            "The amount a bill of quantities states for one line item. Negative for a recovery or "
            "credit, which a bill writes in accounting parentheses."
        ),
        produced_by="aedifex.extraction.pdf_boq",
    ),
    FactTypeInfo(
        fact_type=FIELD_STATED_BILL_TOTAL,
        kind=FactKind.MONEY,
        origin=FactOrigin.EXTRACTED,
        description=(
            "The total a bill of quantities states for itself. Never the sum of anything -- what "
            "the rows add up to is a derived fact, and whether the two agree is a rule."
        ),
        produced_by="aedifex.extraction.pdf_boq",
    ),
    FactTypeInfo(
        fact_type=DERIVED_BILL_ITEMS_TOTAL,
        kind=FactKind.MONEY,
        origin=FactOrigin.DERIVED,
        description=(
            "The sum of a bill's line amounts, with one recorded input per line item so the total "
            "unfolds into the pages it was added from."
        ),
        produced_by="aedifex.calculation.engine",
        inputs=(FIELD_LINE_AMOUNT,),
    ),
    FactTypeInfo(
        fact_type=DERIVED_REQUIRED_BID_SECURITY,
        kind=FactKind.MONEY,
        origin=FactOrigin.DERIVED,
        description=(
            "The bid security a reference provision requires: the clause's share applied to the "
            "project's stated estimated cost, then capped. Rests half on a tender and half on "
            "somebody else's rulebook, and cites both."
        ),
        produced_by="aedifex.calculation.engine",
        inputs=(FIELD_ESTIMATED_COST,),
    ),
    FactTypeInfo(
        fact_type=DERIVED_QUANTITY_VARIANCE,
        kind=FactKind.QUANTITY,
        origin=FactOrigin.DERIVED,
        description=(
            "Cumulative claim minus measured quantity. Positive means the claim runs ahead of "
            "measured work. Carries no judgement — a positive number is not an accusation."
        ),
        produced_by="aedifex.calculation.engine",
        inputs=(FIELD_CUMULATIVE_CLAIM_QUANTITY, FIELD_MEASURED_QUANTITY),
    ),
    FactTypeInfo(
        fact_type=DERIVED_REMAINING_CONTRACT_QUANTITY,
        kind=FactKind.QUANTITY,
        origin=FactOrigin.DERIVED,
        description="Contracted quantity minus cumulative claim. Negative means overrun.",
        produced_by="aedifex.calculation.engine",
        inputs=(FIELD_CONTRACTED_QUANTITY, FIELD_CUMULATIVE_CLAIM_QUANTITY),
    ),
    FactTypeInfo(
        fact_type=DERIVED_RATE_VARIANCE,
        kind=FactKind.MONEY,
        origin=FactOrigin.DERIVED,
        description="Claimed rate minus contracted rate.",
        produced_by="aedifex.calculation.engine",
        inputs=(FIELD_CLAIMED_RATE, FIELD_CONTRACT_RATE),
    ),
    FactTypeInfo(
        fact_type=DERIVED_UNSUPPORTED_AMOUNT,
        kind=FactKind.MONEY,
        origin=FactOrigin.DERIVED,
        description=(
            "The money value of a claim ahead of measured work: max(variance, 0) x contract rate. "
            "Valued at the contracted rate, so a rate dispute is not folded into a quantity one."
        ),
        produced_by="aedifex.calculation.engine",
        inputs=(DERIVED_QUANTITY_VARIANCE, FIELD_CONTRACT_RATE),
    ),
)

RELATIONSHIP_TYPES: Final[tuple[RelationshipTypeInfo, ...]] = (
    RelationshipTypeInfo(
        RelationshipType.SAME_TENDER,
        "Both documents state the same tender reference.",
        derivable=True,
    ),
    RelationshipTypeInfo(
        RelationshipType.SAME_CONTRACT,
        "Both documents quote the same project or contract reference.",
        derivable=True,
    ),
    RelationshipTypeInfo(
        RelationshipType.AMENDMENT_OF, "This document amends the other.", derivable=False
    ),
    RelationshipTypeInfo(
        RelationshipType.SUPERSEDES,
        "This document replaces the other, by explicit operator decision. Never inferred from a "
        "filename, a revision number, or upload order.",
        derivable=True,
    ),
    RelationshipTypeInfo(
        RelationshipType.PARENT_DOCUMENT,
        "The other document contains this one, e.g. a notice bound into a bid document.",
        derivable=False,
    ),
    RelationshipTypeInfo(
        RelationshipType.CHILD_DOCUMENT, "This document contains the other.", derivable=False
    ),
    RelationshipTypeInfo(
        RelationshipType.REFERENCES, "This document cites the other.", derivable=False
    ),
)

RULE_TYPES: Final[tuple[RuleTypeInfo, ...]] = (
    RuleTypeInfo(
        rule_id=BID_SECURITY_RULE_ID,
        scope="document",
        description=(
            "SUPERSEDED by bid_security_matches_reference_policy. Compares a document's derived "
            "bid-security share against the rate it prescribes for itself, or against a rate "
            "supplied by the caller; inconclusive when neither exists, which is the usual case "
            "because a tender notice does not quote its own rate. Kept registered rather than "
            "retired: stored findings cite it, and a rule that cannot be re-run cannot reproduce "
            "them. Still the only answer for an authority whose rulebook has not been acquired."
        ),
        consumes=(DERIVED_BID_SECURITY_SHARE, FIELD_PRESCRIBED_BID_SECURITY_SHARE),
    ),
    RuleTypeInfo(
        rule_id=BILL_TOTAL_RULE_ID,
        scope="document",
        description=(
            "Checks that a priced bill of quantities adds up to the total it states for itself. "
            "REVIEW rather than FAIL when it does not: the rule can establish that the two "
            "figures disagree but not which of them is wrong, and a bill that does not add up is "
            "as likely to mean the extraction is untrustworthy as that the document is."
        ),
        consumes=(DERIVED_BILL_ITEMS_TOTAL, FIELD_STATED_BILL_TOTAL),
    ),
    RuleTypeInfo(
        rule_id=BILL_ESTIMATE_RULE_ID,
        scope="document",
        description=(
            "Compares a priced bill of quantities' stated total against the estimated cost the "
            "tender advertises, reporting the absolute and percentage difference. Always "
            "INCONCLUSIVE: the difference is arithmetic, but no document in the corpus states how "
            "far a bid may sit from the estimate, so it is measured and not judged. Agreement is "
            "the informative case — it means the bill carries the authority's rates, not a "
            "bidder's."
        ),
        consumes=(FIELD_STATED_BILL_TOTAL, FIELD_ESTIMATED_COST),
    ),
    RuleTypeInfo(
        rule_id=REFERENCE_BID_SECURITY_RULE_ID,
        scope="document",
        description=(
            "Compares a tender's bid security against the amount an authority's own rate schedule "
            "requires for a contract of that size. The first rule whose threshold comes from a "
            "different document than the one being judged: applicability is decided from the "
            "authority the document was acquired from and the cost band the document states, so "
            "cross-project access is explicit and evidence-backed rather than global. A cost "
            "inside two bands at once resolves to INCONCLUSIVE, because the document does not say "
            "which governs and choosing would invent policy."
        ),
        consumes=(DERIVED_REQUIRED_BID_SECURITY, FIELD_ESTIMATED_COST, FIELD_BID_SECURITY),
    ),
    RuleTypeInfo(
        rule_id=AGREEMENT_RULE_ID,
        scope="project",
        description=(
            "Checks that documents of one project state identical values for every comparable "
            "fact they both state. Reports a disagreement without resolving it."
        ),
        consumes=(FIELD_ESTIMATED_COST, FIELD_BID_SECURITY),
    ),
    RuleTypeInfo(
        rule_id=SHARE_CONSISTENCY_RULE_ID,
        scope="project",
        description=(
            "Checks that every document of a project derives the same bid-security share. Performs "
            "no arithmetic of its own — the calculation layer already did it."
        ),
        consumes=(DERIVED_BID_SECURITY_SHARE,),
    ),
    RuleTypeInfo(
        rule_id=UNAMBIGUOUS_EVIDENCE_RULE_ID,
        scope="work_item",
        description=(
            "Reports any value the project's active documents disagree about. Runs before the "
            "other item rules, because evidence that contradicts itself must be resolved before "
            "any conclusion drawn from it means anything. REVIEW names every conflicting document, "
            "and PASS cites every fact it resolved -- a pass that named nothing could not be "
            "checked. Consumes no fixed type: it reads whatever the item has."
        ),
        consumes=(),
    ),
    RuleTypeInfo(
        rule_id=CLAIM_WITHIN_MEASURED_RULE_ID,
        scope="work_item",
        description=(
            "Checks that a cumulative claim does not exceed the measured quantity, and reports the "
            "money at risk when it does. REVIEW rather than FAIL: the discrepancy is established, "
            "its cause is not."
        ),
        consumes=(
            FIELD_CUMULATIVE_CLAIM_QUANTITY,
            FIELD_MEASURED_QUANTITY,
            DERIVED_QUANTITY_VARIANCE,
            DERIVED_UNSUPPORTED_AMOUNT,
        ),
    ),
    RuleTypeInfo(
        rule_id=RATE_MATCHES_CONTRACT_RULE_ID,
        scope="work_item",
        description=(
            "Checks the claimed unit rate against the contracted one. REVIEW on a difference, "
            "because an approved variation would make it correct and none can yet be read."
        ),
        consumes=(FIELD_CLAIMED_RATE, FIELD_CONTRACT_RATE, DERIVED_RATE_VARIANCE),
    ),
    RuleTypeInfo(
        rule_id=CUMULATIVE_NOT_REGRESSED_RULE_ID,
        scope="work_item",
        description=(
            "Checks that a cumulative claim is not below what earlier bills certified. A "
            "cumulative figure cannot decrease, so a regression means the bill contradicts itself."
        ),
        consumes=(FIELD_CUMULATIVE_CLAIM_QUANTITY, FIELD_PREVIOUS_CERTIFIED_QUANTITY),
    ),
)


@dataclass(frozen=True, slots=True)
class VersionStateInfo:
    state: DocumentVersionState
    description: str
    participates_in_reconciliation: bool


DOCUMENT_VERSION_STATES: Final[tuple[VersionStateInfo, ...]] = (
    VersionStateInfo(
        DocumentVersionState.ACTIVE,
        "Nothing is known to supersede it. The default, because absent evidence of supersession a "
        "document is current.",
        participates_in_reconciliation=True,
    ),
    VersionStateInfo(
        DocumentVersionState.SUPERSEDED,
        "Explicitly replaced by another document. Still stored and still queryable; excluded from "
        "current-state reconciliation only.",
        participates_in_reconciliation=False,
    ),
    VersionStateInfo(
        DocumentVersionState.RETIRED,
        "Withdrawn without a replacement, by explicit operator decision.",
        participates_in_reconciliation=False,
    ),
    VersionStateInfo(
        DocumentVersionState.UNKNOWN,
        "Something is known to be wrong — e.g. two documents supersede each other. Participates in "
        "nothing, and says so rather than guessing.",
        participates_in_reconciliation=False,
    ),
)

FINDING_OUTCOMES: Final[tuple[FindingOutcomeInfo, ...]] = (
    FindingOutcomeInfo(Outcome.PASS, "The rule's condition held."),
    FindingOutcomeInfo(Outcome.FAIL, "The rule's condition did not hold."),
    FindingOutcomeInfo(
        Outcome.REVIEW,
        "A discrepancy a person should look at. The rule established it but cannot establish its "
        "cause, so it is neither a pass nor a failure.",
    ),
    FindingOutcomeInfo(
        Outcome.INCONCLUSIVE,
        "The rule could not be applied — a value or a threshold was missing. Not a failure of the "
        "document, and never to be displayed as one.",
    ),
)
