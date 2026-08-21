"""Canonical document vocabulary and processing lifecycle.

These enumerations are the shared vocabulary for the whole system: crawlers declare which
document types a source may yield, the classifier emits one of them, and the audit rules
eventually reason over them. Keeping the vocabulary in one module means adding a document
type is a single reviewable change rather than a string literal scattered across layers.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

from aedifex.errors import InvalidStateTransitionError

__all__ = [
    "DOCUMENT_TYPE_CATEGORY",
    "STATE_TRANSITIONS",
    "DocumentCategory",
    "DocumentState",
    "DocumentType",
    "assert_transition_allowed",
    "can_transition",
    "category_for",
    "is_terminal",
]


class DocumentCategory(StrEnum):
    """Business domain a document belongs to (the data-room partitions in the brief)."""

    FINANCIAL = "financial"
    PROCUREMENT = "procurement"
    ENGINEERING = "engineering"
    MATERIAL = "material"
    LEGAL = "legal"
    REGULATORY = "regulatory"
    UNKNOWN = "unknown"


class DocumentType(StrEnum):
    """Document types the platform recognises.

    Grouped by what a document *is*, not by which product might consume it. An earlier version
    of this enum led with a block labelled "payment-auditor wedge", which encoded an unvalidated
    product hypothesis into the vocabulary every other layer reads. That is the cheapest place to
    embed an assumption and among the most expensive to remove, because storage keys, indexes, and
    classifier labels all settle around it.

    No type is privileged. A schedule of rates matters as much as an invoice until interviews say
    otherwise, and the acquisition platform's job is to collect and catalogue whatever a portal
    publishes. See ``docs/research/CUSTOMER_DISCOVERY.md``.

    The vocabulary is expected to grow. It is stored as ``VARCHAR``, not a native database enum,
    precisely so that adding a type needs no migration.
    """

    # --- Procurement and award --------------------------------------------------
    TENDER_NOTICE = "tender_notice"
    BID_DOCUMENT = "bid_document"
    AWARD_NOTICE = "award_notice"
    CORRIGENDUM = "corrigendum"
    PURCHASE_ORDER = "purchase_order"

    # --- Commercial basis of a project ------------------------------------------
    CONTRACT = "contract"
    BILL_OF_QUANTITIES = "bill_of_quantities"
    MEASUREMENT_BOOK = "measurement_book"
    """A measurement book or measurement-sheet extract: what was measured on site."""

    RUNNING_BILL = "running_bill"
    """A running account bill or interim payment claim: what is being claimed, cumulatively."""

    SCHEDULE_OF_RATES = "schedule_of_rates"
    """A published rate schedule (CPWD DSR, state PWD SOR, and equivalents).

    Distinct from a bill of quantities: a BOQ prices one project's quantities, while a schedule of
    rates is the reference rate list a whole department procures against. Widely published, revised
    periodically, and useful for rate benchmarking — one of the directions discovery may point.
    """
    CHANGE_ORDER = "change_order"

    MODEL_AGREEMENT = "model_agreement"
    """A *template* contract an authority publishes for a class of project, not a signed one.

    Separate from ``CONTRACT`` because the difference is not cosmetic: an executed contract states
    facts about one project, while a model agreement states norms about every project of its class.
    Nothing distinguishes them by shape — NHAI's Model Concession Agreement and its executed
    Tada-Nellore concession agreement are both 100-plus pages of the same clauses — so the
    distinction has to be *declared* at ingest and cannot be inferred.

    It earns a type rather than a flag because the extractor already decides what to suppress by
    document type, and because getting it wrong is silent. Both model concession agreements
    acquired on 2026-08-21 emitted a ``document_date`` from a date printed inside a specimen form,
    as a fact about the template itself.
    """

    AUDIT_REPORT = "audit_report"
    """An external or internal audit report: what an auditor found, having examined other records.

    The most quotation-dense document class in the corpus. A CAG performance audit is almost
    entirely figures lifted from contracts, measurement books and bills that the report itself does
    not contain — so a value found in one is evidence of the *audit finding*, and only rarely a fact
    about the report. Three real CAG reports each produced a false ``estimated_cost`` before this
    type existed to tell the extractor what it was reading.
    """

    # --- Engineering and technical ----------------------------------------------
    TECHNICAL_SPECIFICATION = "technical_specification"
    DRAWING = "drawing"
    INSPECTION_REPORT = "inspection_report"
    MATERIAL_TEST_CERTIFICATE = "material_test_certificate"

    # --- Execution and settlement -----------------------------------------------
    INVOICE = "invoice"
    DELIVERY_CHALLAN = "delivery_challan"
    GOODS_RECEIPT_NOTE = "goods_receipt_note"
    PAYMENT_CERTIFICATE = "payment_certificate"
    BANK_GUARANTEE = "bank_guarantee"

    # --- Fallback ---------------------------------------------------------------
    # An honest "we do not know" is required: a misclassified document is worse than an
    # unclassified one, because downstream consumers would silently reason over the wrong
    # evidence.
    UNKNOWN = "unknown"


# Every DocumentType must appear here; ``tests/unit/test_domain_documents.py`` enforces
# exhaustiveness so a newly added type cannot silently default to UNKNOWN.
DOCUMENT_TYPE_CATEGORY: Final[MappingProxyType[DocumentType, DocumentCategory]] = MappingProxyType(
    {
        DocumentType.CONTRACT: DocumentCategory.LEGAL,
        DocumentType.BILL_OF_QUANTITIES: DocumentCategory.PROCUREMENT,
        DocumentType.SCHEDULE_OF_RATES: DocumentCategory.PROCUREMENT,
        DocumentType.PURCHASE_ORDER: DocumentCategory.PROCUREMENT,
        # A measurement book records what was executed on site: engineering evidence, even though a
        # payment claim is what usually cites it.
        DocumentType.MEASUREMENT_BOOK: DocumentCategory.ENGINEERING,
        # A running bill is a claim for money. Financial, though it rests on engineering evidence.
        DocumentType.RUNNING_BILL: DocumentCategory.FINANCIAL,
        DocumentType.INVOICE: DocumentCategory.FINANCIAL,
        DocumentType.DELIVERY_CHALLAN: DocumentCategory.PROCUREMENT,
        DocumentType.GOODS_RECEIPT_NOTE: DocumentCategory.PROCUREMENT,
        DocumentType.MATERIAL_TEST_CERTIFICATE: DocumentCategory.MATERIAL,
        DocumentType.INSPECTION_REPORT: DocumentCategory.ENGINEERING,
        DocumentType.CHANGE_ORDER: DocumentCategory.LEGAL,
        # A model agreement is a legal instrument even though it binds nobody yet.
        DocumentType.MODEL_AGREEMENT: DocumentCategory.LEGAL,
        # An audit report's subject is money: excess payment, non-recovery, irregular expenditure.
        DocumentType.AUDIT_REPORT: DocumentCategory.FINANCIAL,
        DocumentType.TENDER_NOTICE: DocumentCategory.PROCUREMENT,
        DocumentType.TECHNICAL_SPECIFICATION: DocumentCategory.ENGINEERING,
        DocumentType.AWARD_NOTICE: DocumentCategory.PROCUREMENT,
        DocumentType.CORRIGENDUM: DocumentCategory.PROCUREMENT,
        DocumentType.BID_DOCUMENT: DocumentCategory.PROCUREMENT,
        DocumentType.DRAWING: DocumentCategory.ENGINEERING,
        DocumentType.PAYMENT_CERTIFICATE: DocumentCategory.FINANCIAL,
        DocumentType.BANK_GUARANTEE: DocumentCategory.FINANCIAL,
        DocumentType.UNKNOWN: DocumentCategory.UNKNOWN,
    }
)


def category_for(document_type: DocumentType) -> DocumentCategory:
    """Return the business domain for ``document_type``."""
    return DOCUMENT_TYPE_CATEGORY[document_type]


class DocumentState(StrEnum):
    """Explicit processing state of a document in the acquisition pipeline.

    Modelled as a state machine rather than a set of booleans so that a stuck document
    always has one answer to "where is it?", and so that resuming an interrupted crawl is
    a matter of re-reading state (FR-013).
    """

    DISCOVERED = "discovered"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    VALIDATED = "validated"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    QUARANTINED = "quarantined"


# Allowed transitions. FAILED deliberately re-enters the pipeline so that a retry is a
# legal move rather than a database patch. QUARANTINED is terminal on purpose: content
# that tripped a safety limit is released only by an explicit human decision, which is a
# separate reviewed operation (see RUNBOOK.md).
STATE_TRANSITIONS: Final[MappingProxyType[DocumentState, frozenset[DocumentState]]] = (
    MappingProxyType(
        {
            DocumentState.DISCOVERED: frozenset({DocumentState.DOWNLOADING, DocumentState.FAILED}),
            DocumentState.DOWNLOADING: frozenset(
                {DocumentState.DOWNLOADED, DocumentState.FAILED, DocumentState.QUARANTINED}
            ),
            DocumentState.DOWNLOADED: frozenset(
                {DocumentState.VALIDATED, DocumentState.FAILED, DocumentState.QUARANTINED}
            ),
            DocumentState.VALIDATED: frozenset({DocumentState.PROCESSING, DocumentState.FAILED}),
            DocumentState.PROCESSING: frozenset(
                {DocumentState.PROCESSED, DocumentState.FAILED, DocumentState.QUARANTINED}
            ),
            DocumentState.PROCESSED: frozenset(),
            DocumentState.FAILED: frozenset({DocumentState.DOWNLOADING, DocumentState.PROCESSING}),
            DocumentState.QUARANTINED: frozenset(),
        }
    )
)


def is_terminal(state: DocumentState) -> bool:
    """Return whether ``state`` has no outgoing transitions."""
    return not STATE_TRANSITIONS[state]


def can_transition(current: DocumentState, target: DocumentState) -> bool:
    """Return whether moving from ``current`` to ``target`` is legal."""
    return target in STATE_TRANSITIONS[current]


def assert_transition_allowed(current: DocumentState, target: DocumentState) -> None:
    """Raise :class:`InvalidStateTransitionError` if the transition is not legal.

    Used by the persistence layer so that an illegal transition fails loudly at the point
    of the bug instead of corrupting pipeline state.
    """
    if not can_transition(current, target):
        allowed = sorted(state.value for state in STATE_TRANSITIONS[current])
        raise InvalidStateTransitionError(
            f"cannot move document from {current.value!r} to {target.value!r}; "
            f"allowed targets are {allowed or ['<terminal>']}"
        )
