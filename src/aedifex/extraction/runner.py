"""The analysis pipeline: one stored document, all the way to persisted findings.

.. code-block:: text

    stored bytes  ->  bounded text  ->  facts (+evidence)  ->  rules  ->  findings

One orchestration path, and it is deliberately the only one. Each stage is a pure function of the
last except the two that touch infrastructure, which keeps the interesting parts testable by calling
them and keeps this module small enough to read.

The document's own bytes are re-hashed on the way in. Object storage is immutable and content
addressed, so a digest that no longer matches its key means something is wrong with storage rather
than with this document — and analysing bytes that are not the evidence we recorded would put a
finding's whole provenance chain in doubt.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.calculation.engine import (
    DERIVED_BID_SECURITY_SHARE,
    DERIVED_BILL_ITEMS_TOTAL,
    DERIVED_REQUIRED_BID_SECURITY,
    compute_for_document,
    compute_for_work_item,
    compute_required_bid_security,
)
from aedifex.domain.documents import DocumentState, DocumentType, assert_transition_allowed
from aedifex.errors import ExtractionError
from aedifex.extraction.applicability import ApplicableProvision, select_provision
from aedifex.extraction.pdf_boq import (
    FIELD_STATED_BILL_TOTAL,
    PdfBoq,
    boq_fields,
    currency_for,
    fact_kinds,
    read_pdf_boq,
    value_of,
)
from aedifex.extraction.pdftext import extract_text
from aedifex.extraction.policy import PROVISION_BID_SECURITY_SHARE, read_bid_security_policy
from aedifex.extraction.selection import Selected, select_facts
from aedifex.extraction.spreadsheet import (
    FIELD_CONTRACTED_QUANTITY,
    SheetFact,
    read_construction_sheet,
)
from aedifex.extraction.store import (
    persist_derived_facts,
    persist_facts,
    persist_finding,
    persist_project_finding,
    persist_provisions,
    persist_work_item_finding,
)
from aedifex.extraction.tender_notice import (
    FIELD_ESTIMATED_COST,
    FIELD_NIT_NUMBER,
    Evidence,
    ExtractedField,
    TenderNotice,
    extract_tender_notice,
)
from aedifex.extraction.work_items import link_work_items
from aedifex.infrastructure.database.models import (
    DerivedFact,
    Document,
    DocumentRelationship,
    ExtractedFact,
    Finding,
    Project,
    ProjectDocument,
    WorkItem,
)
from aedifex.infrastructure.observability.logging import get_logger
from aedifex.infrastructure.storage.objects import RawObjectStore
from aedifex.verification import evaluate_all, evaluate_project
from aedifex.verification.cross_document import load_project_facts
from aedifex.verification.reconciliation import WorkItemFacts, evaluate_work_item

__all__ = [
    "AnalysisOutcome",
    "ProjectAnalysis",
    "analyse_document",
    "analyse_project",
    "analyse_spreadsheet",
    "reconcile_work_items",
]

_log = get_logger(__name__)

# Deep enough to reach an Instructions to Bidders section, which is where a document states the
# rate its own bid security must satisfy — in the observed corpus, page 13 of 145. A notice-only
# extract is three pages and simply has no such clause.
DEFAULT_MAX_PAGES = 260

# Recorded on spreadsheet facts so they are distinguishable from PDF-extracted ones, and so a change
# to the sheet reader versions independently of the notice reader.
SPREADSHEET_EXTRACTOR = "construction_spreadsheet"

# Document types whose content is *about other projects*: manuals, rate schedules, specifications,
# model agreements, audit reports. The tender-notice reader must not emit document-scoped facts from
# these without positive evidence that a value describes the document itself.
#
# Found the hard way. The NHAI Works Manual states "two percent of the estimated cost for works up
# to Rs. 20 crore" and version 1 of the reader recorded `estimated_cost = Rs 20,00,00,000` as a fact
# about a 297-page procedure manual — then cited it as evidence in a finding. A quoted amount inside
# a reference document is not a fact about that document.
#
# Found the hard way a second time, on 2026-08-21, when five real documents from two new sources
# landed outside this set and produced five false facts:
#
#   * three CAG audit reports, ingested as UNKNOWN because no audit type existed, each emitted an
#     `estimated_cost` scraped from narrative about some other project — ₹13,262 crore of Polavaram
#     R&R colonies, ₹140 crore of a metro station car park, ₹4 crore of a "design ecosystem" — and
#     the Polavaram report also emitted `document_date = 27.07.1989`, a date it merely cites;
#   * two NHAI Model Concession Agreements, ingested as CONTRACT because that is what they are
#     shaped like, each emitted a `document_date` from a date printed inside a specimen form.
#
# The lesson is not "add more types". It is that **reference-versus-project is a property of a
# document's role, not of its shape**, and the two contract-shaped cases prove it: a model
# concession agreement and an executed one are the same clauses in the same order. So the role is
# declared by the operator at ingest — MODEL_AGREEMENT or CONTRACT, AUDIT_REPORT or TENDER_NOTICE —
# and never inferred from the text. An inferred role would fail silently, which is how all five of
# these facts were created.
_REFERENCE_DOCUMENT_TYPES: Final[frozenset[DocumentType]] = frozenset(
    {
        DocumentType.TECHNICAL_SPECIFICATION,
        DocumentType.SCHEDULE_OF_RATES,
        DocumentType.MODEL_AGREEMENT,
        DocumentType.AUDIT_REPORT,
    }
)


def _self_metadata_evidence(notice: TenderNotice) -> bool:
    """Whether the notice identifies the document as being *about* one procurement.

    The test is its own tender identifier. A document that names the tender it concerns is stating
    facts about that tender; a document that names none, while quoting amounts and rates throughout,
    is stating rules about other people's tenders.

    Deliberately one positive signal rather than a list of negative ones. A guard built from "things
    that look like policy language" would be endless and would still miss the next phrasing.
    """
    return notice.field(FIELD_NIT_NUMBER) is not None


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    """What analysing one document produced."""

    document_id: uuid.UUID
    notice: TenderNotice
    facts: tuple[ExtractedFact, ...]
    derived: tuple[DerivedFact, ...]
    findings: tuple[Finding, ...]
    pages_read: int
    page_count: int
    had_text_layer: bool

    @property
    def unsupported(self) -> tuple[str, ...]:
        """Why any field is missing. Empty means everything the extractor looks for was found."""
        return self.notice.unsupported


def analyse_document(
    session: Session,
    store: RawObjectStore,
    document_id: uuid.UUID,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    prescribed_share: Decimal | None = None,
) -> AnalysisOutcome:
    """Take one already-acquired document through the whole analysis path.

    Safe to re-run: facts and findings are keyed by extractor and rule version, so a second pass
    updates rather than duplicates.

    Raises:
        ExtractionError: if the document is unknown, its bytes do not match their digest, or the
            PDF cannot be parsed at all. Never raised for a document that merely yields no facts —
            a scan with no text layer is a recorded limitation, not an error.
    """
    document = session.execute(
        select(Document).where(Document.id == document_id)
    ).scalar_one_or_none()
    if document is None:
        raise ExtractionError(f"unknown document {document_id}")

    data = _read_verified_bytes(store, document)

    text = extract_text(data, max_pages=max_pages)
    notice = extract_tender_notice(text)

    # A bid document can carry a priced bill of quantities as well as its notice, and on the one
    # real example in this corpus it carries 34 line items worth 8.46 crore that the notice reader
    # cannot see. Both readers run; the fields merge into one set of facts.
    # Reference documents state norms, not facts about themselves. Suppress document-scoped
    # extraction unless the document identifies its own procurement, and read the norms instead.
    is_reference = document.document_type in _REFERENCE_DOCUMENT_TYPES
    suppressed: tuple[str, ...] = ()
    if is_reference and not _self_metadata_evidence(notice):
        # Named by document type rather than lumped under "reference document", because the two
        # cases read very differently to an operator: a manual quotes a *norm*, an audit report
        # quotes a figure it found in *someone else's records*. Both are about another project;
        # saying which one it is saves the reader from opening the PDF to find out.
        because = (
            "an audit report states what an auditor found in records it does not contain"
            if document.document_type is DocumentType.AUDIT_REPORT
            else "this is a reference document"
        )
        suppressed = tuple(
            f"{field.name}: suppressed — {because}, and it states no tender identifier, so a "
            f"quoted value is about another project rather than a fact about itself"
            for field in notice.fields
        )
        notice = TenderNotice(fields=(), unsupported=notice.unsupported + suppressed)

    provisions = persist_provisions(
        session, document_id, read_bid_security_policy(text) if is_reference else ()
    )

    boq = read_pdf_boq(text)
    if boq.rows:
        notice = TenderNotice(
            fields=notice.fields + _boq_fields(boq),
            unsupported=notice.unsupported + boq.rejected,
        )

    _advance(document, DocumentState.PROCESSING)
    session.flush()

    facts = persist_facts(session, document_id, notice)

    # Calculate, then judge. The order is the architecture: the calculation layer turns facts into
    # reusable derived facts and knows nothing about thresholds, and the rules consume what it
    # produced rather than dividing the same two numbers again.
    #
    # Given *every* fact, not one per type. A bill of quantities states thirty-seven line amounts
    # and the calculation that sums them needs all of them; passing the type-keyed view summed one
    # row and called it the bill total.
    calculated = compute_for_document(list(facts.all))

    # A reference provision reaching into this document: explicit applicability, decided from the
    # authority the document was acquired from and the cost it states. Not global visibility.
    cost_fact = facts.by_type.get(FIELD_ESTIMATED_COST)
    applicable: ApplicableProvision | None = None
    if cost_fact is not None and cost_fact.numeric_value is not None:
        applicable = select_provision(
            session,
            provision_type=PROVISION_BID_SECURITY_SHARE,
            document_id=document_id,
            value=Decimal(cost_fact.numeric_value),
            applies_to=FIELD_ESTIMATED_COST,
        )
        if applicable.provision is not None:
            required = compute_required_bid_security(cost_fact, applicable.provision)
            if required is not None:
                calculated = (*calculated, required)

    derived = persist_derived_facts(session, calculated, document_id=document_id)

    findings = tuple(
        persist_finding(session, document_id, result, facts.by_type)
        for result in evaluate_all(
            notice,
            prescribed_share=prescribed_share,
            share=derived.get(DERIVED_BID_SECURITY_SHARE),
            refused_rows=len(boq.rejected),
            bill_total=derived.get(DERIVED_BILL_ITEMS_TOTAL),
            applicable=applicable,
            required=derived.get(DERIVED_REQUIRED_BID_SECURITY),
        )
    )

    _advance(document, DocumentState.PROCESSED)
    session.flush()

    _log.info(
        "analysis.finished",
        document_id=str(document_id),
        facts=len(facts.all),
        derived=len(derived),
        provisions=len(provisions),
        findings=len(findings),
        pages_read=text.pages_read,
        page_count=text.page_count,
        had_text_layer=text.has_text_layer,
        outcomes=",".join(sorted({finding.outcome for finding in findings})),
    )

    return AnalysisOutcome(
        document_id=document_id,
        notice=notice,
        facts=facts.all,
        derived=tuple(derived.values()),
        findings=findings,
        pages_read=text.pages_read,
        page_count=text.page_count,
        had_text_layer=text.has_text_layer,
    )


def _read_verified_bytes(store: RawObjectStore, document: Document) -> bytes:
    """Fetch the document's bytes and confirm they are the ones we recorded."""
    with tempfile.TemporaryDirectory(prefix="aedifex-analysis-") as scratch:
        path = store.download_to(document.storage_key, Path(scratch) / "artifact")
        data = path.read_bytes()

    digest = hashlib.sha256(data).hexdigest()
    if digest != document.sha256:
        raise ExtractionError(
            f"stored bytes for {document.id} hash to {digest} but the document records "
            f"{document.sha256}; refusing to analyse evidence that does not match its provenance"
        )
    return data


def _advance(document: Document, target: DocumentState) -> None:
    """Move the document's state, tolerating a re-run that is already past this point.

    A document analysed twice is already ``PROCESSED``, and the state machine rightly refuses
    ``PROCESSED -> PROCESSING``. That is not an error here: re-analysis is a supported operation, so
    a transition that is already satisfied is skipped rather than raised.
    """
    current = document.state
    if current is target or current is DocumentState.PROCESSED:
        return
    if current is DocumentState.DOWNLOADED and target is DocumentState.PROCESSING:
        # The fetch layer already validated format, size and digest on the way in, so the
        # intermediate state is a fact about this document rather than work still to do.
        assert_transition_allowed(current, DocumentState.VALIDATED)
        document.state = DocumentState.VALIDATED
        current = DocumentState.VALIDATED
    assert_transition_allowed(current, target)
    document.state = target


@dataclass(frozen=True, slots=True)
class ProjectAnalysis:
    """What evaluating one project's cross-document rules produced."""

    project: Project
    documents: tuple[Document, ...]
    facts: tuple[ExtractedFact, ...]
    derived: tuple[DerivedFact, ...]
    relationships: tuple[DocumentRelationship, ...]
    findings: tuple[Finding, ...]

    def filename(self, document_id: uuid.UUID) -> str:
        for document in self.documents:
            if document.id == document_id:
                return document.original_filename or str(document_id)
        return str(document_id)


def analyse_project(session: Session, project_id: uuid.UUID) -> ProjectAnalysis:
    """Run the cross-document rules over one project's already-extracted facts.

    Reads facts rather than documents: extraction has happened, and re-parsing PDFs to compare two
    numbers would make the comparison depend on the extractor running twice identically rather than
    on the stored evidence. Everything this rule cites is already persisted, which is what makes the
    finding reproducible from the database alone.

    Raises:
        ExtractionError: if the project does not exist.
    """
    project_facts = load_project_facts(session, project_id)
    if project_facts is None:
        raise ExtractionError(f"unknown project {project_id}")

    findings = tuple(
        persist_project_finding(session, project_id, result)
        for result in evaluate_project(project_facts)
    )
    session.flush()

    _log.info(
        "project_analysis.finished",
        project_id=str(project_id),
        external_ref=project_facts.project.external_ref,
        documents=len(project_facts.documents),
        facts=len(project_facts.facts),
        relationships=len(project_facts.relationships),
        derived=len(project_facts.derived),
        outcomes=",".join(sorted({finding.outcome for finding in findings})),
    )

    return ProjectAnalysis(
        project=project_facts.project,
        documents=tuple(
            project_facts.documents[key] for key in sorted(project_facts.documents, key=str)
        ),
        facts=project_facts.facts,
        derived=project_facts.derived,
        relationships=project_facts.relationships,
        findings=findings,
    )


def analyse_spreadsheet(
    session: Session, store: RawObjectStore, document_id: uuid.UUID
) -> AnalysisOutcome:
    """Extract facts from a stored construction spreadsheet.

    The XLSX counterpart of :func:`analyse_document`. Rules are not evaluated here: a bill of
    quantities on its own says nothing that needs checking, and every reconciliation rule needs
    facts from three documents at once. So this stops at facts, and the work-item pass that follows
    is where the comparison happens.
    """
    document = session.execute(
        select(Document).where(Document.id == document_id)
    ).scalar_one_or_none()
    if document is None:
        raise ExtractionError(f"unknown document {document_id}")

    data = _read_verified_bytes(store, document)
    sheet = read_construction_sheet(data, document_type=document.document_type.value)

    fields: list[ExtractedField] = []
    if sheet.project_reference is not None:
        fields.append(_field_from_cell(sheet.project_reference))
    for row in sheet.rows:
        fields.extend(_field_from_cell(fact) for fact in row.facts)

    notice = TenderNotice(fields=tuple(fields), unsupported=sheet.unsupported)

    _advance(document, DocumentState.PROCESSING)
    session.flush()
    facts = persist_facts(session, document_id, notice, extractor=SPREADSHEET_EXTRACTOR)
    _advance(document, DocumentState.PROCESSED)
    session.flush()

    _log.info(
        "spreadsheet_analysis.finished",
        document_id=str(document_id),
        document_type=document.document_type.value,
        rows=len(sheet.rows),
        facts=len(facts.all),
    )
    return AnalysisOutcome(
        document_id=document_id,
        notice=notice,
        facts=facts.all,
        derived=(),
        findings=(),
        pages_read=len(sheet.rows),
        page_count=len(sheet.rows),
        had_text_layer=bool(sheet.rows),
    )


def _boq_fields(boq: PdfBoq) -> tuple[ExtractedField, ...]:
    """Turn accepted BOQ rows into the same ExtractedField everything else produces.

    ``sheet_row`` carries the row's position in the bill, because that is what work-item linking
    groups on — a fact and its item identifier are related by sharing a row, whether that row came
    from a spreadsheet or from a flattened page.
    """
    kinds = fact_kinds()
    fields: list[ExtractedField] = []
    for fact_type, row in boq_fields(boq):
        literal, value = value_of(fact_type, row)
        fields.append(
            ExtractedField(
                name=fact_type,
                kind=kinds[fact_type],
                literal=literal[:512],
                value=value,
                currency=currency_for(fact_type),
                unit=row.unit if fact_type == FIELD_CONTRACTED_QUANTITY else None,
                sheet_row=row.order,
                evidence=Evidence(
                    page=row.page,
                    start=0,
                    end=0,
                    snippet=f"BOQ item {row.item_identifier}, page {row.page}",
                ),
                method=f"pdf_boq:item {row.item_identifier}",
            )
        )

    # The bill's own total, if it states one. Document-scoped -- no ``sheet_row`` -- because it is a
    # statement about the whole bill rather than about a row, and because that is what makes it
    # deduplicate to one fact per document under the existing partial unique indexes.
    if boq.stated_total is not None and boq.stated_total_page is not None:
        fields.append(
            ExtractedField(
                name=FIELD_STATED_BILL_TOTAL,
                kind=kinds[FIELD_STATED_BILL_TOTAL],
                literal=(boq.stated_total_literal or f"{boq.stated_total}")[:512],
                value=boq.stated_total,
                currency=currency_for(FIELD_STATED_BILL_TOTAL),
                unit=None,
                evidence=Evidence(
                    page=boq.stated_total_page,
                    start=0,
                    end=0,
                    snippet=f"BOQ total, page {boq.stated_total_page}",
                ),
                method="pdf_boq:stated total",
            )
        )
    return tuple(fields)


def _field_from_cell(fact: SheetFact) -> ExtractedField:
    """Turn a spreadsheet cell into the same ExtractedField a PDF span produces.

    One representation for both, so everything downstream -- persistence, calculation, rules,
    evidence -- is indifferent to whether a value came from a page or a cell. The cell reference
    goes in the snippet, which is what a reviewer needs in order to look: ``BOQ!D7`` locates a value
    in a spreadsheet as precisely as a character span locates one in prose.

    The grid position goes in ``sheet_row``/``sheet_column`` rather than the character-span columns,
    which mean something else. Work-item linking groups on the row, because a fact and its item
    identifier are related by sharing one.
    """
    return ExtractedField(
        name=fact.fact_type,
        kind=fact.kind,
        literal=fact.literal,
        value=fact.value,
        currency=fact.currency,
        unit=fact.unit,
        sheet_row=fact.cell.row,
        sheet_column=fact.cell.column,
        evidence=Evidence(page=1, start=0, end=0, snippet=fact.cell.reference),
        method=f"cell:{fact.cell.reference}",
    )


@dataclass(frozen=True, slots=True)
class WorkItemAnalysis:
    """One work item, everything known about it, and what the rules concluded."""

    work_item: WorkItem
    facts: tuple[ExtractedFact, ...]
    derived: tuple[DerivedFact, ...]
    findings: tuple[Finding, ...]
    selections: dict[str, Selected] = field(default_factory=dict)

    @property
    def selected(self) -> dict[str, ExtractedFact]:
        """Only the facts that selection actually chose."""
        return {
            fact_type: selection.fact
            for fact_type, selection in self.selections.items()
            if selection.fact is not None
        }

    @property
    def conflicts(self) -> tuple[Selected, ...]:
        return tuple(s for s in self.selections.values() if s.conflicting)

    @property
    def excluded(self) -> tuple[ExtractedFact, ...]:
        """Facts left out because their document is not current. Shown, never hidden."""
        return tuple(fact for s in self.selections.values() for fact in s.excluded)


def reconcile_work_items(session: Session, project_id: uuid.UUID) -> tuple[WorkItemAnalysis, ...]:
    """Link facts to work items, calculate, then reconcile — the payment path end to end.

    The order is the architecture. Linking connects three documents' statements to one item;
    calculation turns those statements into variances without judging them; the rules judge the
    variances without recomputing them. Each stage can be read, tested and corrected on its own.

    Idempotent throughout: linking is keyed on the normalised identifier, derived facts on the
    calculation version, findings on the rule version.
    """
    link_work_items(session, project_id)

    filenames: dict[str, str] = {}
    documents: dict[uuid.UUID, Document] = {}
    for document in session.execute(
        select(Document)
        .join(ProjectDocument, ProjectDocument.document_id == Document.id)
        .where(ProjectDocument.project_id == project_id)
    ).scalars():
        filenames[str(document.id)] = document.original_filename or str(document.id)
        documents[document.id] = document

    items = list(
        session.execute(
            select(WorkItem)
            .where(WorkItem.project_id == project_id)
            .order_by(WorkItem.normalised_identifier)
        ).scalars()
    )

    analyses: list[WorkItemAnalysis] = []
    for item in items:
        facts = list(
            session.execute(
                select(ExtractedFact).where(ExtractedFact.work_item_id == item.id)
            ).scalars()
        )
        # This used to be `{fact.fact_type: fact for fact in facts}`, which kept whichever fact the
        # database returned last. It was correct only while every version of a document agreed, and
        # one revised bill of quantities away from a confident finding drawn from a stale revision.
        # Selection is now explicit, records why it chose, and refuses when it cannot tell.
        selections = select_facts(facts, documents)
        chosen = {
            fact_type: selection.fact
            for fact_type, selection in selections.items()
            if selection.fact is not None
        }

        # Calculations run on the selected facts only. Deriving a variance from a superseded
        # quantity would launder the error one layer deeper, where the rule can no longer see it.
        calculated = compute_for_work_item(list(chosen.values()))
        derived = persist_derived_facts(session, calculated, project_id=project_id, work_item=item)

        bundle = WorkItemFacts(
            work_item=item,
            facts=chosen,
            derived=derived,
            filenames=filenames,
            selections=selections,
        )
        findings = tuple(
            persist_work_item_finding(session, project_id, item.id, result)
            for result in evaluate_work_item(bundle)
        )
        analyses.append(
            WorkItemAnalysis(
                work_item=item,
                facts=tuple(facts),
                derived=tuple(derived.values()),
                findings=findings,
                selections=selections,
            )
        )

    session.flush()
    _log.info(
        "work_items.reconciled",
        project_id=str(project_id),
        work_items=len(analyses),
        outcomes=",".join(sorted({f.outcome for analysis in analyses for f in analysis.findings})),
    )
    return tuple(analyses)
