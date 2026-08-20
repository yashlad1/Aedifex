"""Recording that one document supersedes another.

The operator's decision, written down. Nothing here infers supersession — not from a filename
containing "Rev2", not from a revision number in the text, not from which file was uploaded later.
Those are all guesses, and a guess at the root of a supersession would silently exclude real
evidence from every reconciliation built on top of it.

What this does is small and deliberate:

* store the relationship, so the reason a document is excluded is queryable;
* mark the superseded document, so selection can skip it without re-deriving the graph each time;
* leave both raw objects and both sets of facts exactly where they are.

The last point is the important one. A superseded revision is still evidence: a finding recorded
against it must remain explicable after it is replaced, and an auditor asking "what did the original
bill of quantities say?" is asking a legitimate question. Supersession changes which document is
*current*, not which documents exist.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.domain.evidence import DocumentVersionState, RelationshipType
from aedifex.errors import ExtractionError
from aedifex.infrastructure.database.models import (
    Document,
    DocumentRelationship,
    Project,
    ProjectDocument,
)
from aedifex.infrastructure.observability.logging import get_logger

__all__ = ["SupersedeOutcome", "record_supersession"]

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SupersedeOutcome:
    """What was recorded."""

    project: Project
    superseding: Document
    superseded: Document
    created: bool

    def describe(self) -> str:
        verb = "recorded" if self.created else "already recorded"
        return (
            f"{verb}: {self.superseding.original_filename} supersedes "
            f"{self.superseded.original_filename} "
            f"(now {self.superseded.version_state.value})"
        )


def record_supersession(
    session: Session,
    *,
    superseding_id: uuid.UUID,
    superseded_id: uuid.UUID,
    decided_by: str,
) -> SupersedeOutcome:
    """Record that one document replaces another, and exclude the older one from current state.

    Args:
        superseding_id: The document that is now current.
        superseded_id: The document it replaces.
        decided_by: Who decided. Stored, because a state with no recorded author cannot be told
            apart from a bug.

    Raises:
        ExtractionError: if either document is unknown, if they are the same document, or if they do
            not share a project. Supersession is scoped to a project because item numbering and
            document identity only mean anything inside one — and because a document superseding
            something in an unrelated project is far more likely to be a mistyped id than an
            intention.
    """
    if superseding_id == superseded_id:
        raise ExtractionError("a document cannot supersede itself")

    superseding = session.get(Document, superseding_id)
    superseded = session.get(Document, superseded_id)
    if superseding is None:
        raise ExtractionError(f"unknown document {superseding_id}")
    if superseded is None:
        raise ExtractionError(f"unknown document {superseded_id}")

    shared = (
        session.execute(
            select(ProjectDocument.project_id)
            .where(ProjectDocument.document_id == superseding_id)
            .intersect(
                select(ProjectDocument.project_id).where(
                    ProjectDocument.document_id == superseded_id
                )
            )
        )
        .scalars()
        .all()
    )
    if not shared:
        raise ExtractionError(
            f"{superseding_id} and {superseded_id} share no project, so one cannot supersede the "
            f"other; run the project reconciliation first, or check the ids"
        )
    project_id = shared[0]
    project = session.get(Project, project_id)
    if project is None:  # pragma: no cover - the membership row guarantees it
        raise ExtractionError(f"unknown project {project_id}")

    existing = session.execute(
        select(DocumentRelationship).where(
            DocumentRelationship.from_document_id == superseding_id,
            DocumentRelationship.to_document_id == superseded_id,
            DocumentRelationship.relationship_type == RelationshipType.SUPERSEDES,
        )
    ).scalar_one_or_none()

    created = existing is None
    if created:
        session.add(
            DocumentRelationship(
                project_id=project_id,
                from_document_id=superseding_id,
                to_document_id=superseded_id,
                relationship_type=RelationshipType.SUPERSEDES,
                established_by=f"operator:{decided_by}",
            )
        )

    # Mutual supersession is a contradiction, not a chain. Both documents become UNKNOWN and take
    # part in nothing, because the alternative is picking one — which is the behaviour this whole
    # milestone exists to remove.
    reverse = session.execute(
        select(DocumentRelationship).where(
            DocumentRelationship.from_document_id == superseded_id,
            DocumentRelationship.to_document_id == superseding_id,
            DocumentRelationship.relationship_type == RelationshipType.SUPERSEDES,
        )
    ).scalar_one_or_none()
    if reverse is not None:
        contradiction = (
            f"contradictory supersession with {superseding_id} and {superseded_id}; "
            f"neither can be treated as current"
        )
        for document in (superseding, superseded):
            document.version_state = DocumentVersionState.UNKNOWN
            document.version_state_reason = contradiction
    else:
        superseded.version_state = DocumentVersionState.SUPERSEDED
        superseded.version_state_reason = (
            f"superseded by {superseding_id} ({superseding.original_filename}), "
            f"recorded by {decided_by}"
        )

    session.flush()
    _log.info(
        "supersession.recorded",
        project_id=str(project_id),
        superseding=str(superseding_id),
        superseded=str(superseded_id),
        created=created,
        resulting_state=superseded.version_state.value,
    )
    return SupersedeOutcome(
        project=project, superseding=superseding, superseded=superseded, created=created
    )
