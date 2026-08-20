"""Grouping documents into projects, from evidence rather than inference.

Two documents belong to one project when both state the same identifier — a tender number for
procurement records, a project or contract reference for post-award ones. That is exact string
equality on a fact extracted with a page or a cell reference, so every membership can be defended
by pointing at the words in both documents. No model is consulted, nothing is guessed from a
filename or a page count, and running this twice changes nothing.

An identifier is the project key because it is the only thing these documents agree on that is
*meant* to identify the work. Grouping on a shared amount would be coincidence — two unrelated
tenders can be worth the same — and grouping on similar titles would be inference.

Scope is deliberate: a project is an aggregation boundary, and rules compare facts only within one.
Two projects that happen to quote identical figures have nothing to say about each other.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select, union_all
from sqlalchemy.orm import Session

from aedifex.domain.evidence import RelationshipType
from aedifex.extraction.spreadsheet import FIELD_PROJECT_REFERENCE
from aedifex.extraction.tender_notice import FIELD_NIT_NUMBER
from aedifex.infrastructure.database.models import (
    Document,
    DocumentRelationship,
    DocumentRetrieval,
    DocumentUpload,
    ExtractedFact,
    Project,
    ProjectDocument,
)
from aedifex.infrastructure.observability.logging import get_logger

__all__ = ["ReconcileOutcome", "established_by", "reconcile_projects"]

_log = get_logger(__name__)


# What established a membership or a relationship. Stored on every row, because a relationship is a
# claim about the world and a claim without provenance is an assertion.
def established_by(fact_type: str) -> str:
    """How a membership was justified. Names the fact, so the reason is readable in the row."""
    return f"shared_fact:{fact_type}"


# Which relationship two documents share, given what grouped them. A tender number means they
# concern one tender; a project or contract reference means they concern one contract, which is a
# different claim and the more accurate one for post-award records.
_RELATIONSHIP_FOR_KEY: dict[str, RelationshipType] = {
    FIELD_NIT_NUMBER: RelationshipType.SAME_TENDER,
    FIELD_PROJECT_REFERENCE: RelationshipType.SAME_CONTRACT,
}

# Identifier facts usable as a project key, strongest first. A document is placed by the first one
# it carries: a tender is identified by its NIT number, and post-award records by the project or
# contract reference they quote. Both are identifiers a document states about itself, which is what
# keeps membership evidence rather than inference.
_PROJECT_KEY_FACTS: tuple[str, ...] = (FIELD_NIT_NUMBER, FIELD_PROJECT_REFERENCE)


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
    ``NHAI/RO/MUM/A'Nagar/...`` in one document and ``NHAI/RO/MUM/A'NAGAR/...`` in another: the
    same tender, shouted. Nothing else is altered — punctuation and separators are part of the
    identifier, and normalising them away would merge references a registry treats as distinct.
    """
    return " ".join(literal.split()).upper()


def reconcile_projects(session: Session, *, source_id: str | None = None) -> ReconcileOutcome:
    """Create or extend projects from the identifier facts already extracted.

    Idempotent: memberships and relationships are keyed on their natural identity, so a second run
    over the same facts creates nothing. Never deletes — a document that stops yielding an
    identifier keeps its membership, because removing evidence of a past grouping would silently
    invalidate findings that cited it.

    Args:
        session: Open session. The caller commits.
        source_id: Restrict to one source. Projects never span sources: two authorities can issue
            the same reference number and they are not the same tender.
    """
    # A document's source comes from a retrieval or from an upload, and both are real provenance --
    # one for a document that was fetched, one for a document that was handed to us. Unioned rather
    # than joined to either, so neither path is privileged and neither is invisible.
    origins = union_all(
        select(
            DocumentRetrieval.document_id.label("document_id"),
            DocumentRetrieval.source_id.label("source_id"),
        ),
        select(
            DocumentUpload.document_id.label("document_id"),
            DocumentUpload.source_id.label("source_id"),
        ),
    ).subquery()

    query = (
        select(ExtractedFact, origins.c.source_id)
        .join(origins, origins.c.document_id == ExtractedFact.document_id)
        .where(ExtractedFact.fact_type.in_(_PROJECT_KEY_FACTS))
    )
    if source_id is not None:
        query = query.where(origins.c.source_id == source_id)

    # Grouped by (source, normalised identifier). A dict keeps one fact per document rather than one
    # row per provenance record, since a document can have several retrievals.
    grouped: dict[tuple[str, str], dict[uuid.UUID, ExtractedFact]] = defaultdict(dict)
    keyed_by: dict[tuple[str, str], str] = {}
    ranked = {fact_type: rank for rank, fact_type in enumerate(_PROJECT_KEY_FACTS)}
    best: dict[uuid.UUID, tuple[int, str, ExtractedFact]] = {}
    for fact, fact_source in session.execute(query).all():
        rank = ranked.get(fact.fact_type, len(ranked))
        current = best.get(fact.document_id)
        if current is None or rank < current[0]:
            best[fact.document_id] = (rank, fact_source, fact)
    for document_id, (_, fact_source, fact) in best.items():
        key = (fact_source, _normalise_key(fact.literal))
        grouped[key][document_id] = fact
        keyed_by.setdefault(key, fact.fact_type)

    projects_created = 0
    memberships_created = 0
    relationships_created = 0

    for group_key, facts_by_document in sorted(grouped.items()):
        project_source, external_ref = group_key
        project = session.execute(
            select(Project).where(
                Project.source_id == project_source, Project.external_ref == external_ref
            )
        ).scalar_one_or_none()
        reason = established_by(keyed_by.get(group_key, _PROJECT_KEY_FACTS[0]))
        if project is None:
            project = Project(
                source_id=project_source,
                external_ref=external_ref,
                established_by=reason,
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
                        established_by=reason,
                    )
                )
                memberships_created += 1

        key_fact = keyed_by.get(group_key, _PROJECT_KEY_FACTS[0])
        relationships_created += _link_documents(
            session,
            project.id,
            sorted(facts_by_document),
            reason=reason,
            relationship=_RELATIONSHIP_FOR_KEY.get(key_fact, RelationshipType.SAME_TENDER),
        )

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


def _link_documents(
    session: Session,
    project_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    *,
    reason: str,
    relationship: RelationshipType,
) -> int:
    """Record ``relationship`` between every pair of documents sharing the identifier.

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
                    DocumentRelationship.relationship_type == relationship,
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            session.add(
                DocumentRelationship(
                    project_id=project_id,
                    from_document_id=first,
                    to_document_id=second,
                    relationship_type=relationship,
                    established_by=reason,
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
