"""Attaching facts from different documents to the same item of work.

Payment reconciliation is impossible until this exists. A bill of quantities, a measurement book and
a running bill each make statements about "item 4.7.2"; three unconnected statements reconcile to
nothing. This module connects them, and it does so deterministically.

Matching is layered, strongest first: an exact item identifier, then a normalised form of it
(case folded, separators unified, leading zeros in each segment dropped). Every link records which
layer matched it, so a weaker match is visibly weaker in the database rather than indistinguishable
from an exact one. That field is also the seam for semantic matching later — a fuzzy match would
record itself as such and a rule could decline to rely on it, which is not possible if every link
looks equally certain.

No embeddings and no model, deliberately. An item number is an identifier; guessing that "RCC M30 in
foundation" and "M-30 reinforced concrete, footings" are the same item is a judgement, and a
judgement dressed as a link would put an inference underneath every quantity comparison built on it.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.extraction.spreadsheet import (
    FIELD_ITEM_DESCRIPTION,
    FIELD_ITEM_IDENTIFIER,
)
from aedifex.infrastructure.database.models import (
    ExtractedFact,
    ProjectDocument,
    WorkItem,
)
from aedifex.infrastructure.observability.logging import get_logger

__all__ = ["MATCH_EXACT", "MATCH_NORMALISED", "LinkOutcome", "link_work_items", "normalise_item"]

_log = get_logger(__name__)

MATCH_EXACT: Final[str] = "exact_identifier"
MATCH_NORMALISED: Final[str] = "normalised_identifier"

_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"[\s\-/_]+")


@dataclass(frozen=True, slots=True)
class LinkOutcome:
    """What linking changed. All zeroes on a second run over unchanged facts."""

    work_items_created: int
    facts_linked: int
    facts_without_item: int

    def describe(self) -> str:
        return (
            f"{self.work_items_created} work items created, {self.facts_linked} facts linked; "
            f"{self.facts_without_item} facts belong to no item"
        )


def normalise_item(identifier: str) -> str:
    """Canonical form of an item number, for matching only.

    ``4.7.2``, ``4-7-2`` and ``04.07.02`` are one item written three ways, and all three appear in
    real records. Leading zeros are dropped per segment rather than from the whole string, so
    ``4.07.2`` and ``4.7.2`` match while ``4.7.20`` stays distinct from ``4.7.2``.

    The original spelling is kept on the work item; this value exists to compare, not to display.
    """
    unified = _SEPARATORS.sub(".", identifier.strip()).upper()
    segments = [segment.lstrip("0") or "0" for segment in unified.split(".") if segment]
    return ".".join(segments)


def link_work_items(session: Session, project_id: uuid.UUID) -> LinkOutcome:
    """Create work items for one project and attach every item-scoped fact to one.

    A fact is item-scoped when it shares a document *row* with an item identifier. Facts about the
    document as a whole, such as a project reference, are left unattached, which is correct: they
    belong to the document, not to an item of work.

    Idempotent. Work items are keyed on (project, normalised identifier) and a fact already pointing
    at the right item is left alone.
    """
    document_ids = list(
        session.execute(
            select(ProjectDocument.document_id).where(ProjectDocument.project_id == project_id)
        ).scalars()
    )
    if not document_ids:
        return LinkOutcome(0, 0, 0)

    facts = list(
        session.execute(
            select(ExtractedFact)
            .where(ExtractedFact.document_id.in_(document_ids))
            .order_by(ExtractedFact.document_id, ExtractedFact.sheet_row)
        ).scalars()
    )

    # An item identifier claims every fact sharing its (document, row). Facts with no row are not
    # about an item at all, so they are never claimed.
    identifiers: dict[tuple[uuid.UUID, int], ExtractedFact] = {}
    for fact in facts:
        if fact.fact_type == FIELD_ITEM_IDENTIFIER and fact.sheet_row is not None:
            identifiers[(fact.document_id, fact.sheet_row)] = fact

    grouped: dict[str, list[ExtractedFact]] = defaultdict(list)
    descriptions: dict[str, str] = {}
    units: dict[str, str] = {}
    originals: dict[str, str] = {}
    unattached = 0

    for fact in facts:
        anchor = (
            identifiers.get((fact.document_id, fact.sheet_row))
            if fact.sheet_row is not None
            else None
        )
        if anchor is None:
            unattached += 1
            continue
        key = normalise_item(anchor.literal)
        originals.setdefault(key, anchor.literal)
        grouped[key].append(fact)
        if fact.fact_type == FIELD_ITEM_DESCRIPTION:
            descriptions.setdefault(key, fact.literal)
        if fact.unit:
            units.setdefault(key, fact.unit)

    created = 0
    linked = 0
    for key in sorted(grouped):
        existing = session.execute(
            select(WorkItem).where(
                WorkItem.project_id == project_id, WorkItem.normalised_identifier == key
            )
        ).scalar_one_or_none()
        original = originals[key]
        if existing is None:
            # Exact when every document spelled it identically; normalised when they did not.
            spellings = {
                identifiers[(fact.document_id, fact.sheet_row)].literal
                for fact in grouped[key]
                if fact.sheet_row is not None and (fact.document_id, fact.sheet_row) in identifiers
            }
            existing = WorkItem(
                project_id=project_id,
                item_identifier=original,
                normalised_identifier=key,
                description=descriptions.get(key),
                unit=units.get(key),
                matched_by=MATCH_EXACT if len(spellings) == 1 else MATCH_NORMALISED,
            )
            session.add(existing)
            session.flush()
            created += 1
        elif existing.description is None and key in descriptions:
            existing.description = descriptions[key]

        for fact in grouped[key]:
            if fact.work_item_id != existing.id:
                fact.work_item_id = existing.id
                linked += 1

    session.flush()
    outcome = LinkOutcome(
        work_items_created=created, facts_linked=linked, facts_without_item=unattached
    )
    _log.info(
        "work_items.linked",
        project_id=str(project_id),
        work_items_created=created,
        facts_linked=linked,
        facts_without_item=unattached,
    )
    return outcome
