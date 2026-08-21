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

from aedifex import __version__
from aedifex.calculation.engine import Calculated
from aedifex.extraction.policy import (
    POLICY_EXTRACTOR,
    POLICY_EXTRACTOR_VERSION,
    ExtractedProvision,
)
from aedifex.extraction.tender_notice import EXTRACTOR, EXTRACTOR_VERSION, TenderNotice
from aedifex.infrastructure.database.models import (
    DerivedFact,
    DerivedFactInput,
    ExtractedFact,
    FactRetraction,
    Finding,
    FindingEvidence,
    PolicyProvision,
    WorkItem,
)
from aedifex.infrastructure.observability.logging import get_logger
from aedifex.verification.cross_document import ProjectRuleResult
from aedifex.verification.reconciliation import WorkItemRuleResult
from aedifex.verification.rules import RuleResult

# Ten decimal places, matching DerivedFact.numeric_value's NUMERIC(28, 10).
_DERIVED_SCALE = Decimal("1E-10")


def _fingerprint(
    inputs: Mapping[str, ExtractedFact],
    provisions: Mapping[str, PolicyProvision] | None = None,
) -> str:
    """A digest of exactly which facts and provisions fed a calculation.

    Roles are included, not just ids: swapping which fact fills ``measured_quantity`` and which
    fills ``cumulative_claim_quantity`` is a different calculation with the same two inputs.

    Provisions are folded in for the same reason facts are. A required amount recomputed against a
    re-read rate schedule is a different value with the same estimated cost, and a fingerprint that
    ignored the clause would report it as unchanged.
    """
    applied = provisions or {}
    parts = [f"{role}={inputs[role].id}" for role in sorted(inputs)]
    parts += [f"provision:{role}={applied[role].id}" for role in sorted(applied)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


_log = get_logger(__name__)

__all__ = [
    "FactSet",
    "persist_derived_facts",
    "persist_facts",
    "persist_finding",
    "persist_project_finding",
    "persist_provisions",
    "persist_retractions",
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


def persist_retractions(
    session: Session,
    document_id: uuid.UUID,
    fact_types: Sequence[str],
    *,
    reason: str,
    extractor: str = EXTRACTOR,
    extractor_version: str = EXTRACTOR_VERSION,
) -> tuple[FactRetraction, ...]:
    """Record that this extractor version withdraws earlier facts of these types.

    Called when the extractor deliberately declines to emit a document-scoped fact it previously
    emitted — the suppression case. Suppression alone is silent: writing nothing leaves the old row
    as the newest one for its document and fact type, so it stays selected and stays served. This is
    what makes the decision explicit.

    Scope is deliberately narrow, because a retraction removes evidence from view and the blast
    radius of getting it wrong is high:

    * only document-scoped facts (``sheet_row IS NULL``). A suppressed bill line is not a thing that
      happens — suppression is about values quoted in prose.
    * only facts not already retracted, so re-running is idempotent rather than accumulating
      duplicate opinions.

    **Version is deliberately not part of the filter, and it used to be.** The original rule
    withdrew only *older* extractor versions, reasoning that a version cannot contradict itself
    within one run. That reasoning holds for a re-run and fails for a *reclassification*: the
    document's declared type is an input to extraction, so the same version reading a document
    retyped from ``contract`` to ``model_agreement`` is a corrected reading of a corrected input,
    not a self-contradiction.

    A real document proved it. IIT Bombay's Hostel 19 general conditions of contract, ingested as
    ``contract``, produced ``estimated_cost = Rs. 5 crores`` from the clause "shall not be
    applicable for works with estimated cost put to tender being less than Rs. 5 crores", plus a
    ``document_date`` of 31-12-1979 from another clause. Retyped to ``model_agreement`` the
    extractor correctly emitted nothing — and both false facts stayed live and selectable, because
    they carried the same version as the run withdrawing them.

    Dropping the version clause is safe rather than merely convenient, and the invariant is worth
    stating: this function is only ever called with the fact types the run has *decided to
    suppress*, and the caller empties the notice before persisting anything, so no fact of a
    suppressed type is written in the same run. Anything this query finds is necessarily from an
    earlier one.

    Args:
        fact_types: The fact types this run suppressed.
        reason: Why, in prose. Stored verbatim on every row written, because a withdrawal nobody can
            argue with is not auditable.

    Returns:
        The retractions written. Empty when there was nothing to withdraw, which is the normal case
        for a document being analysed for the first time.
    """
    if not fact_types:
        return ()

    stale = list(
        session.execute(
            select(ExtractedFact)
            .outerjoin(FactRetraction, FactRetraction.fact_id == ExtractedFact.id)
            .where(
                ExtractedFact.document_id == document_id,
                ExtractedFact.fact_type.in_(list(fact_types)),
                ExtractedFact.sheet_row.is_(None),
                FactRetraction.id.is_(None),
            )
        ).scalars()
    )

    written: list[FactRetraction] = []
    for fact in stale:
        retraction = FactRetraction(
            fact_id=fact.id,
            retracted_by_extractor=extractor,
            retracted_by_version=extractor_version,
            reason=reason,
            software_version=__version__,
        )
        session.add(retraction)
        written.append(retraction)

    if written:
        session.flush()
        _log.info(
            "extraction.facts_retracted",
            document_id=str(document_id),
            retracted=len(written),
            fact_types=sorted(set(fact_types)),
            by_version=extractor_version,
        )
    return tuple(written)


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
    for role, provision in sorted(result.provision_evidence.items()):
        finding.evidence.append(FindingEvidence(provision_id=provision.id, role=role))

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
        row.inputs_fingerprint = _fingerprint(item.inputs, item.provisions)
        if existing is None:
            session.add(row)
        else:
            row.inputs.clear()
        session.flush()

        for role in sorted(item.inputs):
            row.inputs.append(DerivedFactInput(role=role, fact_id=item.inputs[role].id))
        for role in sorted(item.provisions):
            row.inputs.append(
                DerivedFactInput(role=f"provision:{role}", provision_id=item.provisions[role].id)
            )
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


def persist_provisions(
    session: Session,
    document_id: uuid.UUID,
    provisions: Sequence[ExtractedProvision],
    *,
    extractor: str = POLICY_EXTRACTOR,
    extractor_version: str = POLICY_EXTRACTOR_VERSION,
) -> tuple[PolicyProvision, ...]:
    """Store the norms one reference document states, keyed by clause.

    Idempotent on (document, provision type, clause, extractor version), so re-reading the same
    manual updates its clauses rather than accumulating them. Versioned for the same reason facts
    are: a corrected reading of a rate schedule supersedes the earlier one without deleting it,
    because a finding recorded against the old reading must stay explicable.
    """
    stored: list[PolicyProvision] = []
    for provision in provisions:
        existing = session.execute(
            select(PolicyProvision).where(
                PolicyProvision.document_id == document_id,
                PolicyProvision.provision_type == provision.provision_type,
                PolicyProvision.clause == provision.clause,
                PolicyProvision.extractor_version == extractor_version,
            )
        ).scalar_one_or_none()

        row = existing if existing is not None else PolicyProvision(document_id=document_id)
        row.provision_type = provision.provision_type
        row.clause = provision.clause
        row.authority = provision.authority
        row.jurisdiction = provision.jurisdiction
        row.page = provision.page
        row.span_start = provision.span_start
        row.span_end = provision.span_end
        row.snippet = provision.snippet
        row.applies_to = provision.applies_to
        row.applies_from = provision.applies_from
        row.applies_to_max = provision.applies_to_max
        row.share = provision.share
        row.cap_amount = provision.cap_amount
        row.currency = provision.currency
        row.extractor = extractor
        row.extractor_version = extractor_version
        if existing is None:
            session.add(row)
        stored.append(row)

    session.flush()
    return tuple(stored)
