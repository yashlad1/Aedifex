"""Evidence selection: which revision a rule uses, and when it refuses to choose.

These five cases are the milestone's list, and each one guards a behaviour that would otherwise be
invisible. A superseded revision being excluded looks identical to it never having existed; an
ambiguous conflict being refused looks identical to a rule that simply did not run. The only way to
tell a working policy from a broken one is to assert on both the choice and the recorded reason.

The code these replace was ``{fact.fact_type: fact for fact in facts}``, which was correct for
exactly as long as every version of a document agreed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from aedifex.domain.evidence import DocumentVersionState, FactKind
from aedifex.domain.files import FileFormat
from aedifex.extraction.selection import select_facts, select_one
from aedifex.infrastructure.database.models import Document, ExtractedFact
from aedifex.infrastructure.storage.keys import raw_key


def a_document(
    state: DocumentVersionState = DocumentVersionState.ACTIVE, name: str = "BOQ.xlsx"
) -> Document:
    digest = uuid.uuid4().hex + uuid.uuid4().hex
    return Document(
        id=uuid.uuid4(),
        sha256=digest,
        size_bytes=1,
        file_format=FileFormat.XLSX,
        original_filename=name,
        storage_key=raw_key(
            source_id="synthetic_projects", sha256=digest, file_format=FileFormat.XLSX
        ),
        version_state=state,
    )


def a_fact(
    document: Document,
    value: Decimal,
    *,
    fact_type: str = "contracted_quantity",
    version: str = "1",
) -> ExtractedFact:
    return ExtractedFact(
        id=uuid.uuid4(),
        document_id=document.id,
        fact_type=fact_type,
        kind=FactKind.QUANTITY,
        literal=str(value),
        numeric_value=value,
        unit="m3",
        page=1,
        span_start=0,
        span_end=0,
        snippet="BOQ!D7",
        method="test",
        extractor="test",
        extractor_version=version,
    )


def test_a_superseded_revision_is_excluded_and_the_active_one_is_used() -> None:
    """The core of the milestone: 550 from Rev 02, not 500 from the superseded Rev 01."""
    old = a_document(DocumentVersionState.SUPERSEDED, "BOQ-Rev01.xlsx")
    new = a_document(DocumentVersionState.ACTIVE, "BOQ-Rev02.xlsx")
    facts = [a_fact(old, Decimal("500")), a_fact(new, Decimal("550"))]

    selected = select_one("contracted_quantity", facts, {old.id: old, new.id: new})

    assert selected.resolved
    assert selected.fact is not None
    assert selected.fact.numeric_value == Decimal("550")
    assert selected.fact.document_id == new.id
    # Reported as excluded, not silently dropped: a reader must be able to see that an older value
    # existed and was set aside.
    assert [fact.numeric_value for fact in selected.excluded] == [Decimal("500")]
    assert "only active document" in selected.reason


def test_two_conflicting_active_documents_resolve_to_nothing() -> None:
    """The case the old dict comprehension answered confidently and wrongly."""
    first = a_document(name="BOQ-Rev01.xlsx")
    second = a_document(name="BOQ-Unlinked.xlsx")
    facts = [a_fact(first, Decimal("1200")), a_fact(second, Decimal("1400"))]

    selected = select_one("contracted_quantity", facts, {first.id: first, second.id: second})

    assert not selected.resolved
    assert selected.conflicting
    assert selected.fact is None
    assert len(selected.considered) == 2
    assert "none supersedes the others" in selected.reason


def test_active_documents_that_agree_are_not_a_conflict() -> None:
    """Three copies of the same number is duplication, not disagreement."""
    documents = [a_document(name=f"copy{index}.xlsx") for index in range(3)]
    facts = [a_fact(document, Decimal("500.00")) for document in documents]

    selected = select_one(
        "contracted_quantity", facts, {document.id: document for document in documents}
    )

    assert selected.resolved
    assert not selected.conflicting
    assert "3 active documents agree" in selected.reason


def test_a_newer_extraction_of_one_document_wins_without_conflict() -> None:
    """Two readings of one document are our versions, not the project's."""
    document = a_document()
    facts = [
        a_fact(document, Decimal("500"), version="1"),
        a_fact(document, Decimal("550"), version="2"),
    ]

    selected = select_one("contracted_quantity", facts, {document.id: document})

    assert selected.resolved
    assert not selected.conflicting
    assert selected.fact is not None
    assert selected.fact.numeric_value == Decimal("550")


def test_a_fact_stated_only_by_superseded_documents_is_unresolved_not_absent() -> None:
    """Superseded and never-stated warrant different findings, so they must be distinguishable."""
    old = a_document(DocumentVersionState.SUPERSEDED, "BOQ-Rev01.xlsx")
    facts = [a_fact(old, Decimal("500"))]

    selected = select_one("contracted_quantity", facts, {old.id: old})

    assert not selected.resolved
    assert not selected.conflicting
    assert "superseded" in selected.reason
    assert len(selected.excluded) == 1


def test_selection_reports_every_type_including_unresolved_ones() -> None:
    """A caller must be able to tell a gap from a conflict, so both appear in the result."""
    active = a_document()
    other = a_document(name="other.xlsx")
    facts = [
        a_fact(active, Decimal("500"), fact_type="contracted_quantity"),
        a_fact(other, Decimal("600"), fact_type="contracted_quantity"),
        a_fact(active, Decimal("470"), fact_type="measured_quantity"),
    ]

    selections = select_facts(facts, {active.id: active, other.id: other})

    assert set(selections) == {"contracted_quantity", "measured_quantity"}
    assert selections["contracted_quantity"].conflicting
    assert selections["measured_quantity"].resolved
