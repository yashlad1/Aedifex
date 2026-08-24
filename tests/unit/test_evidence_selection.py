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
from aedifex.infrastructure.database.models import Document, ExtractedFact, FactRetraction
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


def test_a_retracted_fact_is_never_selected() -> None:
    """Policy step 0, added after a withdrawn value reached a conclusive finding.

    A retraction is a later extractor version stating that the document never said this. Selection
    is the one place that decides what a rule reasons over, so a withdrawn row must not survive it —
    and the recorded reason has to say *withdrawn* rather than "no active document states it", or an
    operator is told the document is silent when in fact we took the value back.
    """
    document = a_document()
    fact = a_fact(document, Decimal("470"))
    fact.retraction = FactRetraction(
        fact_id=fact.id,
        retracted_by_extractor="test",
        retracted_by_version="2",
        reason="quoted from another project's records",
        software_version="0",
    )

    selected = select_one("contracted_quantity", [fact], {document.id: document})

    assert selected.fact is None
    assert not selected.resolved
    assert "retracted" in selected.reason
    assert selected.excluded == (fact,), "and it is reported as excluded, not silently dropped"


def test_a_retracted_revision_does_not_hide_a_good_one() -> None:
    """The other half: withdrawing one document's value leaves the remaining one selectable."""
    withdrawn_document = a_document(name="draft-BOQ.xlsx")
    withdrawn = a_fact(withdrawn_document, Decimal("999"))
    withdrawn.retraction = FactRetraction(
        fact_id=withdrawn.id,
        retracted_by_extractor="test",
        retracted_by_version="2",
        reason="misread column",
        software_version="0",
    )
    good_document = a_document()
    good = a_fact(good_document, Decimal("470"))

    selected = select_one(
        "contracted_quantity",
        [withdrawn, good],
        {withdrawn_document.id: withdrawn_document, good_document.id: good_document},
    )

    assert selected.fact is good
    assert selected.resolved


def test_two_rows_of_one_document_are_two_claims_not_two_readings() -> None:
    """A composite bill restarts its numbering, so one item key can hold rows that disagree.

    The IIT Bombay Hostel 19 bill states 661 priced rows whose hierarchical numbers repeat across
    its four parts: 49 different rows normalise to item "1.3", with quantities from 102 to 1,250.
    Selection keyed candidates on the document alone, so 48 of the 49 were discarded — not because
    anything superseded them, but because ``4 > 4`` is false — and the survivor was whichever row
    the database returned first. The reason recorded was "the only active document stating
    contracted_quantity", which was not true of the evidence.

    Row order was an authority again, which is the one thing this module exists to prevent.
    """
    bill = a_document(name="composite-bill.pdf")
    facts = [
        a_fact(bill, Decimal("910")),
        a_fact(bill, Decimal("102")),
        a_fact(bill, Decimal("1250")),
    ]
    for row, fact in enumerate(facts, start=203):
        fact.sheet_row = row

    selected = select_one("contracted_quantity", facts, {bill.id: bill})

    assert selected.fact is None
    assert selected.conflicting is True
    assert len(selected.considered) == 3
    # Named as rows of one document, not as documents: there is one document here, and a reason
    # that miscounts the evidence is the same defect as a fact that misreads it.
    assert selected.reason == (
        "3 rows of one document state different values for contracted_quantity, so which of those "
        "rows is this item cannot be determined"
    )


def test_two_readings_of_one_row_still_resolve_to_the_newer() -> None:
    """The behaviour keying on the document was there to protect: same row, better extractor."""
    bill = a_document(name="bill.pdf")
    old = a_fact(bill, Decimal("470"), version="3")
    new = a_fact(bill, Decimal("520"), version="4")
    old.sheet_row = new.sheet_row = 12

    selected = select_one("contracted_quantity", [old, new], {bill.id: bill})

    assert selected.fact is new
    assert selected.conflicting is False
