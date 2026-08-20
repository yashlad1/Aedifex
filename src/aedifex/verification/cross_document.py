"""Rules that compare facts originating in different documents.

This is the module the milestone exists for. Everything before it reasoned inside one document,
which means every conclusion was already written down somewhere — extraction only found it. A
cross-document rule produces something no single document contains, and that is the first point at
which Aedifex is doing construction reasoning rather than document processing.

The first rule is agreement: when two documents of one project both state a value for the same fact,
those values must match. It is the simplest rule the available evidence supports, chosen for that
reason. It is not a toy — a bid document whose estimated cost no longer matches the notice inviting
bids for it is either mid-corrigendum or wrong, and both are worth a human's attention.

**A disagreement is reported, never resolved.** The rule has no basis for deciding which document
is right, so it states both values, cites both spans, and stops. Picking one would be the rule
inventing a fact.

Comparison is exact `Decimal` equality for money and quantities. No tolerance: these are figures a
document states about itself, and two documents describing one tender either agree or they do not.
A tolerance here would be a threshold nobody sourced, which is the mistake the single-document rule
already taught us to avoid.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.domain.evidence import FactKind
from aedifex.infrastructure.database.models import (
    Document,
    DocumentRelationship,
    ExtractedFact,
    Project,
    ProjectDocument,
)
from aedifex.verification.rules import NOT_SOURCED, Outcome

__all__ = [
    "AGREEMENT_RULE_ID",
    "AGREEMENT_RULE_VERSION",
    "ProjectRuleResult",
    "evaluate_fact_agreement",
    "load_project_facts",
]

AGREEMENT_RULE_ID: Final[str] = "cross_document_fact_agreement"
AGREEMENT_RULE_VERSION: Final[str] = "1"

# Only kinds with a magnitude are compared. Two identifiers being unequal is how projects are told
# apart in the first place, so comparing them here would report every project as self-inconsistent.
_COMPARED_KINDS: Final[frozenset[FactKind]] = frozenset(
    {FactKind.MONEY, FactKind.QUANTITY, FactKind.PERCENTAGE, FactKind.DURATION}
)


@dataclass(frozen=True, slots=True)
class ProjectRuleResult:
    """A verdict about a project, with the stored facts it compared.

    Separate from :class:`~aedifex.verification.rules.RuleResult` because the evidence is different
    in kind: a single-document rule cites fields it was just handed, while this cites rows that are
    already persisted and belong to different documents. Collapsing the two would mean one of them
    carrying a type it never uses.
    """

    rule_id: str
    rule_version: str
    outcome: Outcome
    summary: str
    expected: str
    observed: str
    detail: dict[str, str]
    evidence: dict[str, ExtractedFact]


@dataclass(frozen=True, slots=True)
class ProjectFacts:
    """One project's documents, facts, and relationships, loaded once."""

    project: Project
    documents: dict[uuid.UUID, Document]
    facts: tuple[ExtractedFact, ...]
    relationships: tuple[DocumentRelationship, ...]

    def latest_by_type(self) -> dict[str, list[ExtractedFact]]:
        """Facts grouped by type, keeping one row per document per type.

        When a document has facts from several extractor versions the newest wins — comparing an
        old extraction against a new one would report a disagreement between two of *our* runs
        rather than between two documents.
        """
        newest: dict[tuple[str, uuid.UUID], ExtractedFact] = {}
        for fact in self.facts:
            key = (fact.fact_type, fact.document_id)
            current = newest.get(key)
            if current is None or fact.extractor_version > current.extractor_version:
                newest[key] = fact
        grouped: dict[str, list[ExtractedFact]] = defaultdict(list)
        for (fact_type, _), fact in newest.items():
            grouped[fact_type].append(fact)
        return {
            fact_type: sorted(rows, key=lambda row: str(row.document_id))
            for fact_type, rows in grouped.items()
        }

    def filename(self, document_id: uuid.UUID) -> str:
        document = self.documents.get(document_id)
        return (document.original_filename if document else None) or str(document_id)


def load_project_facts(session: Session, project_id: uuid.UUID) -> ProjectFacts | None:
    """Load everything one project's rules need, or ``None`` if the project does not exist."""
    project = session.get(Project, project_id)
    if project is None:
        return None

    document_ids = list(
        session.execute(
            select(ProjectDocument.document_id).where(ProjectDocument.project_id == project_id)
        ).scalars()
    )
    documents = {
        document.id: document
        for document in session.execute(
            select(Document).where(Document.id.in_(document_ids))
        ).scalars()
    }
    facts = tuple(
        session.execute(
            select(ExtractedFact)
            .where(ExtractedFact.document_id.in_(document_ids))
            .order_by(ExtractedFact.fact_type, ExtractedFact.document_id)
        ).scalars()
    )
    relationships = tuple(
        session.execute(
            select(DocumentRelationship).where(DocumentRelationship.project_id == project_id)
        ).scalars()
    )
    return ProjectFacts(
        project=project, documents=documents, facts=facts, relationships=relationships
    )


def evaluate_fact_agreement(project_facts: ProjectFacts) -> ProjectRuleResult:
    """Check that documents of one project agree on every comparable value they both state.

    Returns ``INCONCLUSIVE`` when no fact is stated by two or more documents — which is the honest
    answer for a project holding a single document, and must not be reported as agreement. A project
    with nothing to compare has not been checked.
    """
    grouped = project_facts.latest_by_type()
    comparable = {
        fact_type: rows
        for fact_type, rows in grouped.items()
        if len(rows) > 1
        and all(row.kind in _COMPARED_KINDS and row.numeric_value is not None for row in rows)
    }

    if not comparable:
        stated_by_one = sorted(fact_type for fact_type, rows in grouped.items() if len(rows) == 1)
        return ProjectRuleResult(
            rule_id=AGREEMENT_RULE_ID,
            rule_version=AGREEMENT_RULE_VERSION,
            outcome=Outcome.INCONCLUSIVE,
            summary=(
                "No comparable value is stated by more than one document in this "
                "project, so there is nothing to reconcile. "
                + (
                    f"{len(stated_by_one)} fact type(s) appear in exactly one document: "
                    f"{', '.join(stated_by_one)}."
                    if stated_by_one
                    else "No numeric facts have been extracted."
                )
            ),
            expected=NOT_SOURCED,
            observed="nothing compared",
            detail={
                "documents": str(len(project_facts.documents)),
                "comparable_fact_types": "0",
            },
            evidence={},
        )

    evidence: dict[str, ExtractedFact] = {}
    disagreements: list[str] = []
    agreements: list[str] = []
    detail: dict[str, str] = {"documents": str(len(project_facts.documents))}

    for fact_type, rows in sorted(comparable.items()):
        values = {row.numeric_value for row in rows}
        for index, row in enumerate(rows, start=1):
            evidence[f"{fact_type}#{index}"] = row
            detail[f"{fact_type}#{index}"] = (
                f"{row.numeric_value} from {project_facts.filename(row.document_id)} p{row.page}"
            )
        if len(values) == 1:
            only = next(iter(values))
            agreements.append(
                f"{fact_type} = {_format(only)} in all {len(rows)} documents stating it"
            )
        else:
            spread = ", ".join(
                f"{_format(row.numeric_value)} in {project_facts.filename(row.document_id)} "
                f"(p{row.page})"
                for row in rows
            )
            disagreements.append(f"{fact_type}: {spread}")

    detail["compared_fact_types"] = str(len(comparable))
    detail["disagreements"] = str(len(disagreements))

    if disagreements:
        return ProjectRuleResult(
            rule_id=AGREEMENT_RULE_ID,
            rule_version=AGREEMENT_RULE_VERSION,
            outcome=Outcome.FAIL,
            summary=(
                f"Documents of this project state different values for "
                f"{len(disagreements)} of {len(comparable)} comparable fact(s): "
                + "; ".join(disagreements)
                + ". Which document is correct is not something this rule can determine."
            ),
            expected="identical values across documents of one project",
            observed=f"{len(disagreements)} disagreement(s)",
            detail=detail,
            evidence=evidence,
        )

    return ProjectRuleResult(
        rule_id=AGREEMENT_RULE_ID,
        rule_version=AGREEMENT_RULE_VERSION,
        outcome=Outcome.PASS,
        summary=(
            f"All {len(comparable)} comparable fact(s) agree across the "
            f"{len(project_facts.documents)} documents of this project: " + "; ".join(agreements)
        ),
        expected="identical values across documents of one project",
        observed="0 disagreements",
        detail=detail,
        evidence=evidence,
    )


def _format(value: Decimal | None) -> str:
    return "—" if value is None else f"{value:,}"
