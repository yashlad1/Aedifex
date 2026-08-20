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
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.calculation.engine import DERIVED_BID_SECURITY_SHARE, compute_for_document
from aedifex.domain.documents import DocumentState, assert_transition_allowed
from aedifex.errors import ExtractionError
from aedifex.extraction.pdftext import extract_text
from aedifex.extraction.store import (
    persist_derived_facts,
    persist_facts,
    persist_finding,
    persist_project_finding,
)
from aedifex.extraction.tender_notice import TenderNotice, extract_tender_notice
from aedifex.infrastructure.database.models import (
    DerivedFact,
    Document,
    DocumentRelationship,
    ExtractedFact,
    Finding,
    Project,
)
from aedifex.infrastructure.observability.logging import get_logger
from aedifex.infrastructure.storage.objects import RawObjectStore
from aedifex.verification import evaluate_all, evaluate_project
from aedifex.verification.cross_document import load_project_facts

__all__ = ["AnalysisOutcome", "ProjectAnalysis", "analyse_document", "analyse_project"]

_log = get_logger(__name__)

# Deep enough to reach an Instructions to Bidders section, which is where a document states the
# rate its own bid security must satisfy — in the observed corpus, page 13 of 145. A notice-only
# extract is three pages and simply has no such clause.
DEFAULT_MAX_PAGES = 260


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

    _advance(document, DocumentState.PROCESSING)
    session.flush()

    facts = persist_facts(session, document_id, notice)

    # Calculate, then judge. The order is the architecture: the calculation layer turns facts into
    # reusable derived facts and knows nothing about thresholds, and the rules consume what it
    # produced rather than dividing the same two numbers again.
    calculated = compute_for_document(list(facts.values()))
    derived = persist_derived_facts(session, calculated, document_id=document_id)

    findings = tuple(
        persist_finding(session, document_id, result, facts)
        for result in evaluate_all(
            notice,
            prescribed_share=prescribed_share,
            share=derived.get(DERIVED_BID_SECURITY_SHARE),
        )
    )

    _advance(document, DocumentState.PROCESSED)
    session.flush()

    _log.info(
        "analysis.finished",
        document_id=str(document_id),
        facts=len(facts),
        derived=len(derived),
        findings=len(findings),
        pages_read=text.pages_read,
        page_count=text.page_count,
        had_text_layer=text.has_text_layer,
        outcomes=",".join(sorted({finding.outcome for finding in findings})),
    )

    return AnalysisOutcome(
        document_id=document_id,
        notice=notice,
        facts=tuple(facts.values()),
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
