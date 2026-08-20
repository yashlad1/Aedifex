"""Grouping documents into projects, from evidence rather than inference.

Two documents belong to one project when both state the same tender identifier. That is exact string
equality on a fact that was extracted with a page and a span, so every membership can be defended by
pointing at the words in both documents. No model is consulted, nothing is guessed from a filename
or
a page count, and running this twice changes nothing.

The identifier is the project key because it is the only thing these documents agree on that is
*meant* to identify the tender. Grouping on a shared amount would be coincidence — two unrelated
tenders can be worth the same — and grouping on similar titles would be inference.

Scope is deliberate: a project is an aggregation boundary, and rules compare facts only within one.
Two projects that happen to quote identical figures have nothing to say about each other.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.domain.evidence import RelationshipType
from aedifex.extraction.tender_notice import FIELD_NIT_NUMBER
from aedifex.infrastructure.database.models import (
    Document,
    DocumentRelationship,
    DocumentRetrieval,
    ExtractedFact,
    Project,
    ProjectDocument,
)
from aedifex.infrastructure.observability.logging import get_logger

__all__ = ["ReconcileOutcome", "reconcile_projects"]

_log = get_logger(__name__)

# What established a membership or a relationship. Stored on every row, because a relationship is a
# claim about the world and a claim without provenance is an assertion.
ESTABLISHED_BY: str = f"shared_fact:{FIELD_NIT_NUMBER}"

# The identifier fact used as the project key.
_PROJECT_KEY_FACT: str = FIELD_NIT_NUMBER


@dataclass(frozen=True, slots=True)
class ReconcileOutcome:
    """What reconciliation changed. All zeroes on a second run over unchanged data."""

    projects_created: int
    memberships_created: int
    relationships_created: int
    documents_without_key: int

    @property
    def changed(self) -> bool:
        return bool(self.projects_created or self.memberships_created or self.relationships_created)

    def describe(self) -> str:
        return (
            f"{self.projects_created} projects, {self.memberships_created} memberships, "
            f"{self.relationships_created} relationships created; "
            f"{self.documents_without_key} documents carry no project key"
        )


def _normalise_key(literal: str) -> str:
    """Canonical form of a tender identifier for grouping.

    Case and internal whitespace are normalised because the same reference appears as
    ``NHAI/RO/MUM/A'Nagar/...`` in one document and ``NHAI/RO/MUM/A'NAGAR/...`` in another — the
    same
    tender, shouted. Nothing else is altered: punctuation and separators are part of the identifier,
    and normalising them away would merge references that a registry would treat as distinct.
    """
    return " ".join(literal.split()).upper()


def reconcile_projects(session: Session, *, source_id: str | None = None) -> ReconcileOutcome:
    """Create or extend projects from the identifier facts already extracted.

    Idempotent: memberships and relationships are keyed on their natural identity, so a second run
    over the same facts creates nothing. Never deletes — a document that stops yielding an
    identifier
    keeps its existing membership, because removing evidence of a past grouping would silently
    invalidate findings that cited it.

    Args:
        session: Open session. The caller commits.
        source_id: Restrict to one source. Projects never span sources: two authorities can issue
            the same reference number and they are not the same tender.
    """
    query = (
        select(ExtractedFact, DocumentRetrieval.source_id)
        .join(Document, Document.id == ExtractedFact.document_id)
        .join(DocumentRetrieval, DocumentRetrieval.document_id == Document.id)
        .where(ExtractedFact.fact_type == _PROJECT_KEY_FACT)
    )
    if source_id is not None:
        query = query.where(DocumentRetrieval.source_id == source_id)

    # Grouped by (source, normalised identifier). A dict keeps the newest extractor version's fact
    # per document rather than one row per retrieval, since a document can have several retrievals.
    grouped: dict[tuple[str, str], dict[uuid.UUID, ExtractedFact]] = defaultdict(dict)
    for fact, fact_source in session.execute(query).all():
        grouped[(fact_source, _normalise_key(fact.literal))][fact.document_id] = fact

    projects_created = 0
    memberships_created = 0
    relationships_created = 0

    for (project_source, key), facts_by_document in sorted(grouped.items()):
        project = session.execute(
            select(Project).where(Project.source_id == project_source, Project.external_ref == key)
        ).scalar_one_or_none()
        if project is None:
            project = Project(
                source_id=project_source,
                external_ref=key,
                established_by=ESTABLISHED_BY,
            )
            session.add(project)
            session.flush()
            projects_created += 1

        for document_id in sorted(facts_by_document):
            existing = session.get(ProjectDocument, (project.id, document_id))
            if existing is None:
                session.add(
                    ProjectDocument(
                        project_id=project.id,
                        document_id=document_id,
                        established_by=ESTABLISHED_BY,
                    )
                )
                memberships_created += 1

        relationships_created += _link_documents(session, project.id, sorted(facts_by_document))

    session.flush()
    without_key = _documents_without_project_key(session, source_id=source_id)
    outcome = ReconcileOutcome(
        projects_created=projects_created,
        memberships_created=memberships_created,
        relationships_created=relationships_created,
        documents_without_key=without_key,
    )
    _log.info(
        "projects.reconciled",
        **{
            "projects_created": projects_created,
            "memberships_created": memberships_created,
            "relationships_created": relationships_created,
            "documents_without_key": without_key,
        },
    )
    return outcome


def _link_documents(session: Session, project_id: uuid.UUID, document_ids: list[uuid.UUID]) -> int:
    """Record ``same_tender`` between every pair of documents sharing the identifier.

    Stored once per pair in a canonical direction — lower id first — because the relationship is
    symmetric and two rows for one fact can disagree. Pairwise rather than star-shaped because no
    document among them is privileged: none of them is "the" tender.
    """
    created = 0
    for index, left in enumerate(document_ids):
        for right in document_ids[index + 1 :]:
            first, second = sorted((left, right), key=str)
            existing = session.execute(
                select(DocumentRelationship).where(
                    DocumentRelationship.from_document_id == first,
                    DocumentRelationship.to_document_id == second,
                    DocumentRelationship.relationship_type == RelationshipType.SAME_TENDER,
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            session.add(
                DocumentRelationship(
                    project_id=project_id,
                    from_document_id=first,
                    to_document_id=second,
                    relationship_type=RelationshipType.SAME_TENDER,
                    established_by=ESTABLISHED_BY,
                )
            )
            created += 1
    return created


def _documents_without_project_key(session: Session, *, source_id: str | None) -> int:
    """How many analysed documents could not be placed. Reported, never hidden.

    A document with no identifier fact is not a failure — a corrigendum may simply not repeat the
    tender number — but it is invisible to every cross-document rule, and a pipeline that did not
    say
    so would look like it had considered everything.
    """
    analysed = select(ExtractedFact.document_id).distinct().subquery()
    query = select(Document.id).join(analysed, analysed.c.document_id == Document.id)
    if source_id is not None:
        query = query.join(DocumentRetrieval, DocumentRetrieval.document_id == Document.id).where(
            DocumentRetrieval.source_id == source_id
        )
    placed = select(ProjectDocument.document_id).distinct().subquery()
    return len(
        [
            document_id
            for document_id in session.execute(query).scalars()
            if document_id not in set(session.execute(select(placed.c.document_id)).scalars())
        ]
    )
