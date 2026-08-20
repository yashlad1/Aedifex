"""Persisting facts and findings.

Idempotent by construction. Both tables carry a unique constraint — one fact per
(document, type, extractor version), one finding per (document, rule, rule version) — and this
module reads before writing, so re-analysing a document updates its rows instead of accumulating
duplicates. That matters more than it sounds: the runner is meant to be safe to re-run over the
whole corpus, and a pipeline that doubles its evidence on every pass is one nobody will re-run.

What this module will not do is delete evidence. A changed extractor gets a new version and
therefore new rows; the old facts stay readable, because a finding recorded last month must still be
explicable against the values that actually produced it.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.calculation.engine import Calculated
from aedifex.extraction.tender_notice import EXTRACTOR, EXTRACTOR_VERSION, TenderNotice
from aedifex.infrastructure.database.models import (
    DerivedFact,
    DerivedFactInput,
    ExtractedFact,
    Finding,
    FindingEvidence,
    WorkItem,
)
from aedifex.verification.cross_document import ProjectRuleResult
from aedifex.verification.reconciliation import WorkItemRuleResult
from aedifex.verification.rules import RuleResult

# Ten decimal places, matching DerivedFact.numeric_value's NUMERIC(28, 10).
_DERIVED_SCALE = Decimal("1E-10")


def _fingerprint(inputs: Mapping[str, ExtractedFact]) -> str:
    """A digest of exactly which facts fed a calculation.

    Roles are included, not just ids: swapping which fact fills ``measured_quantity`` and which
    fills ``cumulative_claim_quantity`` is a different calculation with the same two inputs.
    """
    material = "|".join(f"{role}={inputs[role].id}" for role in sorted(inputs))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "FactSet",
    "persist_derived_facts",
    "persist_facts",
    "persist_finding",
    "persist_project_finding",
    "persist_work_item_finding",
]


@dataclass(frozen=True, slots=True)
class FactSet:
    """Every fact one document yielded, and the subset that is addressable by type.

    Two views, because two callers want different things and conflating them has now caused the
    same bug twice. A rule asking for "the estimated cost" wants one fact; a calculation summing a
    bill of quantities wants all 37 of its rows. The first version of this returned only a
    type-keyed dict, so summing a bill produced the total of whichever row happened to be written
    last — a wrong figure that looked like a right one.
    """

    all: tuple[ExtractedFact, ...]
    """Every fact written, in extraction order."""

    by_type: dict[str, ExtractedFact]
    """Document-scoped facts only, keyed by type.

    Row-scoped facts are deliberately absent: a bill states thirty-seven line amounts and none of
    them is *the* line amount. Rows are reached through their work item, or through the whole list.
    """


def persist_facts(
    session: Session,
    document_id: uuid.UUID,
    notice: TenderNotice,
    *,
    extractor: str = EXTRACTOR,
    extractor_version: str = EXTRACTOR_VERSION,
) -> FactSet:
    """Write one row per extracted field.

    Fields the extractor could not find are simply absent — never written as a row with a null
    value. An absent fact and a fact whose value is unknown are different claims, and only the
    first is true here.
    """
    written: list[ExtractedFact] = []
    stored: dict[str, ExtractedFact] = {}
    for field in notice.fields:
        # Keyed on the row as well as the type, because a table states the same kind of fact once
        # per line. Without the row in the key, a three-row bill of quantities persisted one row.
        existing = session.execute(
            select(ExtractedFact).where(
                ExtractedFact.document_id == document_id,
                ExtractedFact.fact_type == field.name,
                ExtractedFact.extractor_version == extractor_version,
                ExtractedFact.sheet_row == field.sheet_row,
            )
        ).scalar_one_or_none()

        row = existing if existing is not None else ExtractedFact(document_id=document_id)
        row.fact_type = field.name
        row.literal = field.literal
        row.numeric_value = field.value
        row.currency = field.currency
        row.page = field.evidence.page
        row.span_start = field.evidence.start
        row.span_end = field.evidence.end
        row.snippet = field.evidence.snippet
        row.method = field.method
        row.kind = field.kind
        row.date_value = field.date_value
        row.unit = field.unit
        row.sheet_row = field.sheet_row
        row.sheet_column = field.sheet_column
        row.extractor = extractor
        row.extractor_version = extractor_version
        if existing is None:
            session.add(row)
        written.append(row)
        if field.sheet_row is None:
            stored[field.name] = row

    session.flush()
    return FactSet(all=tuple(written), by_type=stored)


def persist_finding(
    session: Session,
    document_id: uuid.UUID,
    result: RuleResult,
    facts: Mapping[str, ExtractedFact],
) -> Finding:
    """Write one finding and link it to the facts the rule actually read.

    The evidence links are rebuilt rather than appended, so a re-run whose rule read different
    facts does not leave the previous run's links behind claiming to have been used.
    """
    existing = session.execute(
        select(Finding).where(
            Finding.document_id == document_id,
            Finding.rule_id == result.rule_id,
            Finding.rule_version == result.rule_version,
        )
    ).scalar_one_or_none()

    finding = existing if existing is not None else Finding(document_id=document_id)
    finding.rule_id = result.rule_id
    finding.rule_version = result.rule_version
    finding.outcome = result.outcome.value
    finding.summary = result.summary
    finding.expected = result.expected
    finding.observed = result.observed
    finding.detail = dict(result.detail)
    if existing is None:
        session.add(finding)
    else:
        finding.evidence.clear()
    session.flush()

    for role in sorted(result.evidence):
        fact = facts.get(role)
        if fact is None:
            # The rule cited a field that was not persisted. Skipping the link rather than
            # inventing one keeps the evidence table honest about what it can prove.
            continue
        finding.evidence.append(FindingEvidence(fact_id=fact.id, role=role))
    for role, derived in sorted(result.derived_evidence.items()):
        finding.evidence.append(FindingEvidence(derived_fact_id=derived.id, role=role))

    session.flush()
    return finding


def persist_project_finding(
    session: Session, project_id: uuid.UUID, result: ProjectRuleResult
) -> Finding:
    """Write a cross-document finding, scoped to the project rather than to any one document.

    The evidence links point at facts belonging to *different* documents, which is the whole point:
    following them leads a reader to two pages in two files, which is where the conclusion actually
    comes from. Rebuilt on re-run rather than appended, so a changed comparison does not leave the
    previous run's citations behind.
    """
    existing = session.execute(
        select(Finding).where(
            Finding.project_id == project_id,
            Finding.rule_id == result.rule_id,
            Finding.rule_version == result.rule_version,
        )
    ).scalar_one_or_none()

    finding = existing if existing is not None else Finding(project_id=project_id)
    finding.rule_id = result.rule_id
    finding.rule_version = result.rule_version
    finding.outcome = result.outcome.value
    finding.summary = result.summary
    finding.expected = result.expected
    finding.observed = result.observed
    finding.detail = dict(result.detail)
    if existing is None:
        session.add(finding)
    else:
        finding.evidence.clear()
    session.flush()

    for role in sorted(result.evidence):
        finding.evidence.append(FindingEvidence(fact_id=result.evidence[role].id, role=role))
    for role, derived in sorted(result.derived_evidence.items()):
        finding.evidence.append(FindingEvidence(derived_fact_id=derived.id, role=role))
    session.flush()
    return finding


def persist_derived_facts(
    session: Session,
    calculated: Sequence[Calculated],
    *,
    document_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    work_item: WorkItem | None = None,
) -> dict[str, DerivedFact]:
    """Store computed values and the facts that fed them, keyed by fact type.

    Idempotent on (subject, fact type, calculation version). Recomputation updates the value in
    place and rebuilds the input links, so a re-run cannot leave a derived fact citing inputs it no
    longer used — which would be worse than a stale value, because it would look documented.
    """
    if (document_id is None) == (project_id is None):
        raise ValueError("a derived fact belongs to exactly one of a document or a project")

    # A work item's derived facts are project-scoped but must not collide across items, so the item
    # is folded into the fact type. Two items of one project both have a quantity_variance, and
    # keying them only on (project, fact_type) would make the second overwrite the first.
    prefix = f"{work_item.normalised_identifier}:" if work_item is not None else ""

    stored: dict[str, DerivedFact] = {}
    for item in calculated:
        scoped_type = f"{prefix}{item.fact_type}"
        existing = session.execute(
            select(DerivedFact).where(
                DerivedFact.document_id == document_id,
                DerivedFact.project_id == project_id,
                DerivedFact.fact_type == scoped_type,
                DerivedFact.calculation_version == item.calculation_version,
            )
        ).scalar_one_or_none()

        row = (
            existing
            if existing is not None
            else DerivedFact(document_id=document_id, project_id=project_id)
        )
        row.fact_type = scoped_type
        row.kind = item.kind
        # Quantized to the column's scale here rather than in the calculation, so what a caller
        # reads back is exactly what the database holds. The engine deliberately does not round --
        # rounding belongs at the boundary where precision is actually constrained, and that is this
        # one.
        row.numeric_value = item.value.quantize(_DERIVED_SCALE)
        row.currency = item.currency
        row.unit = item.unit
        row.calculation = item.calculation
        row.calculation_version = item.calculation_version
        row.produced_by = item.produced_by
        row.expression = item.expression
        row.inputs_fingerprint = _fingerprint(item.inputs)
        if existing is None:
            session.add(row)
        else:
            row.inputs.clear()
        session.flush()

        for role in sorted(item.inputs):
            row.inputs.append(DerivedFactInput(role=role, fact_id=item.inputs[role].id))
        stored[item.fact_type] = row

    session.flush()
    return stored


def persist_work_item_finding(
    session: Session,
    project_id: uuid.UUID,
    work_item_id: uuid.UUID,
    result: WorkItemRuleResult,
) -> Finding:
    """Write a reconciliation finding about one item of work.

    Scoped to the project *and* the work item: a reviewer filtering by project must see item
    findings, and a reviewer looking at one item must not see the others'.
    """
    existing = session.execute(
        select(Finding).where(
            Finding.work_item_id == work_item_id,
            Finding.rule_id == result.rule_id,
            Finding.rule_version == result.rule_version,
        )
    ).scalar_one_or_none()

    finding = (
        existing
        if existing is not None
        else Finding(project_id=project_id, work_item_id=work_item_id)
    )
    finding.rule_id = result.rule_id
    finding.rule_version = result.rule_version
    finding.outcome = result.outcome.value
    finding.summary = result.summary
    finding.expected = result.expected
    finding.observed = result.observed
    finding.detail = dict(result.detail)
    if existing is None:
        session.add(finding)
    else:
        finding.evidence.clear()
    session.flush()

    for role in sorted(result.evidence):
        finding.evidence.append(FindingEvidence(fact_id=result.evidence[role].id, role=role))
    for role, derived in sorted(result.derived_evidence.items()):
        finding.evidence.append(FindingEvidence(derived_fact_id=derived.id, role=role))
    session.flush()
    return finding
