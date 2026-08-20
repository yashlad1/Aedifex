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

from aedifex.calculation.engine import DERIVED_BID_SECURITY_SHARE
from aedifex.domain.evidence import FactKind, FactOrigin, RelationshipType
from aedifex.extraction.tender_notice import (
    FIELD_BID_SECURITY,
    FIELD_DOCUMENT_DATE,
    FIELD_ESTIMATED_COST,
    FIELD_NIT_NUMBER,
    FIELD_PRESCRIBED_BID_SECURITY_SHARE,
)
from aedifex.verification.cross_document import (
    AGREEMENT_RULE_ID,
    SHARE_CONSISTENCY_RULE_ID,
)
from aedifex.verification.rules import BID_SECURITY_RULE_ID, Outcome

__all__ = [
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
)

RELATIONSHIP_TYPES: Final[tuple[RelationshipTypeInfo, ...]] = (
    RelationshipTypeInfo(
        RelationshipType.SAME_TENDER,
        "Both documents state the same tender reference.",
        derivable=True,
    ),
    RelationshipTypeInfo(
        RelationshipType.SAME_CONTRACT,
        "Both documents concern one contract. Needs a contract identifier nothing yet extracts.",
        derivable=False,
    ),
    RelationshipTypeInfo(
        RelationshipType.AMENDMENT_OF, "This document amends the other.", derivable=False
    ),
    RelationshipTypeInfo(
        RelationshipType.SUPERSEDES, "This document replaces the other.", derivable=False
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
            "Compares a document's derived bid-security share against the rate it prescribes for "
            "itself, or against a rate supplied by the caller. Inconclusive when neither exists."
        ),
        consumes=(DERIVED_BID_SECURITY_SHARE, FIELD_PRESCRIBED_BID_SECURITY_SHARE),
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
)

FINDING_OUTCOMES: Final[tuple[FindingOutcomeInfo, ...]] = (
    FindingOutcomeInfo(Outcome.PASS, "The rule's condition held."),
    FindingOutcomeInfo(Outcome.FAIL, "The rule's condition did not hold."),
    FindingOutcomeInfo(
        Outcome.INCONCLUSIVE,
        "The rule could not be applied — a value or a threshold was missing. Not a failure of the "
        "document, and never to be displayed as one.",
    ),
)
