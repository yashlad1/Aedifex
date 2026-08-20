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

import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.extraction.tender_notice import EXTRACTOR, EXTRACTOR_VERSION, TenderNotice
from aedifex.infrastructure.database.models import ExtractedFact, Finding, FindingEvidence
from aedifex.verification.cross_document import ProjectRuleResult
from aedifex.verification.rules import RuleResult

__all__ = ["persist_facts", "persist_finding", "persist_project_finding"]


def persist_facts(
    session: Session,
    document_id: uuid.UUID,
    notice: TenderNotice,
    *,
    extractor: str = EXTRACTOR,
    extractor_version: str = EXTRACTOR_VERSION,
) -> dict[str, ExtractedFact]:
    """Write one row per extracted field, keyed by fact type for the caller's convenience.

    Fields the extractor could not find are simply absent — never written as a row with a null
    value. An absent fact and a fact whose value is unknown are different claims, and only the
    first is true here.
    """
    stored: dict[str, ExtractedFact] = {}
    for field in notice.fields:
        existing = session.execute(
            select(ExtractedFact).where(
                ExtractedFact.document_id == document_id,
                ExtractedFact.fact_type == field.name,
                ExtractedFact.extractor_version == extractor_version,
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
        row.extractor = extractor
        row.extractor_version = extractor_version
        if existing is None:
            session.add(row)
        stored[field.name] = row

    session.flush()
    return stored


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
    session.flush()
    return finding
