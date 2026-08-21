"""The cross-document agreement rule, including the case real documents cannot exercise.

The corpus contains one project whose two documents agree, so running the pipeline proves the rule
returns PASS and proves nothing about whether it can return FAIL. A comparison that has only ever
agreed is indistinguishable from one that does not work, and this rule's whole purpose is to notice
disagreement — so that path is tested here rather than left to the first real mismatch to discover
in production.

Deliberately narrow (rule 18b): four cases covering the outcomes that mean different things. No
mocks and no fixtures — the rule is pure, so the test constructs the rows it compares.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from aedifex.domain.evidence import FactKind
from aedifex.infrastructure.database.models import (
    Document,
    ExtractedFact,
    FactRetraction,
    Project,
)
from aedifex.verification.cross_document import ProjectFacts, evaluate_fact_agreement
from aedifex.verification.rules import NOT_SOURCED, Outcome

NIT = uuid.UUID("11111111-1111-1111-1111-111111111111")
RFP = uuid.UUID("22222222-2222-2222-2222-222222222222")


def a_fact(
    document_id: uuid.UUID,
    fact_type: str,
    value: Decimal | None,
    *,
    kind: FactKind = FactKind.MONEY,
    page: int = 1,
) -> ExtractedFact:
    return ExtractedFact(
        id=uuid.uuid4(),
        document_id=document_id,
        fact_type=fact_type,
        kind=kind,
        literal=f"Rs. {value}" if value is not None else "NHAI/X/1",
        numeric_value=value,
        currency="INR" if value is not None else None,
        page=page,
        span_start=0,
        span_end=10,
        snippet="...",
        method="test",
        extractor="test",
        extractor_version="1",
    )


def project_of(*facts: ExtractedFact) -> ProjectFacts:
    document_ids = {fact.document_id for fact in facts}
    return ProjectFacts(
        project=Project(
            id=uuid.uuid4(), source_id="nhai", external_ref="NHAI/X/1", established_by="test"
        ),
        documents={
            document_id: Document(id=document_id, original_filename=f"{document_id.hex[:4]}.pdf")
            for document_id in document_ids
        },
        facts=facts,
        relationships=(),
    )


def test_two_documents_stating_different_amounts_fail_and_both_are_cited() -> None:
    """The case the corpus cannot produce, and the only reason this rule exists."""
    result = evaluate_fact_agreement(
        project_of(
            a_fact(NIT, "estimated_cost", Decimal("84649969")),
            a_fact(RFP, "estimated_cost", Decimal("84649000"), page=6),
        )
    )

    assert result.outcome is Outcome.FAIL
    assert result.observed == "1 disagreement(s)"
    # Both values appear, so a reader can see the conflict without opening either document -- and
    # neither is presented as the correct one.
    assert "84,649,969" in result.summary
    assert "84,649,000" in result.summary
    assert "not something this rule can determine" in result.summary
    # Both spans are cited, one per document.
    assert {fact.document_id for fact in result.evidence.values()} == {NIT, RFP}


def test_two_documents_stating_the_same_amount_pass() -> None:
    result = evaluate_fact_agreement(
        project_of(
            a_fact(NIT, "estimated_cost", Decimal("84649969")),
            a_fact(RFP, "estimated_cost", Decimal("84649969"), page=6),
        )
    )

    assert result.outcome is Outcome.PASS
    assert result.observed == "0 disagreements"
    assert len(result.evidence) == 2


def test_a_value_stated_by_only_one_document_is_inconclusive_not_agreement() -> None:
    """A project with nothing to compare has not been checked, and must not report a pass."""
    result = evaluate_fact_agreement(project_of(a_fact(NIT, "estimated_cost", Decimal("1"))))

    assert result.outcome is Outcome.INCONCLUSIVE
    assert result.expected == NOT_SOURCED
    assert "estimated_cost" in result.summary
    assert result.evidence == {}


def test_matching_identifiers_alone_do_not_constitute_agreement() -> None:
    """Identifiers are how the project was formed; comparing them would be circular.

    Both documents state the same tender number, which is why they are one project. If that counted
    as an agreed value, every project would pass its own reconciliation by construction.
    """
    result = evaluate_fact_agreement(
        project_of(
            a_fact(NIT, "nit_number", None, kind=FactKind.IDENTIFIER),
            a_fact(RFP, "nit_number", None, kind=FactKind.IDENTIFIER, page=6),
        )
    )

    assert result.outcome is Outcome.INCONCLUSIVE
    assert result.observed == "nothing compared"


def test_a_retracted_fact_is_not_compared() -> None:
    """The defect the first end-to-end product run found, pinned so it cannot come back.

    Real case: the Hostel 19 general conditions of contract quote a threshold — "works with an
    estimated cost put to tender of less than Rs. 5 crores", page 48 — and version 4 of the
    extractor had already retracted it, because a value quoted inside a model agreement is about
    other people's projects. The rule loaded it anyway and reported ₹5,00,00,000 as this project's
    estimated cost disagreeing with ₹85,39,81,318.41, producing a confident FAIL from evidence the
    system itself had withdrawn.

    Two things are asserted, and the second is the one that matters: the outcome is PASS, and the
    retracted row is not cited. A finding may cite a fact it was computed from; it may never be
    computed from a fact that no longer stands.
    """
    withdrawn = a_fact(
        uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "estimated_cost",
        Decimal("50000000"),
        page=48,
    )
    withdrawn.retraction = FactRetraction(
        fact_id=withdrawn.id,
        retracted_by_extractor="test",
        retracted_by_version="4",
        reason="quoted inside a model agreement, so it is not a fact about this document",
        software_version="0",
    )

    result = evaluate_fact_agreement(
        project_of(
            a_fact(NIT, "estimated_cost", Decimal("853981318.41")),
            a_fact(RFP, "estimated_cost", Decimal("853981318.41"), page=2),
            withdrawn,
        )
    )

    assert result.outcome is Outcome.PASS
    assert all(
        fact.numeric_value == Decimal("853981318.41") for fact in result.evidence.values()
    ), "a withdrawn value must not appear as evidence for anything"
