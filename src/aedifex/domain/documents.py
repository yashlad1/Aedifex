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
    SCHEDULE_OF_RATES = "schedule_of_rates"
    """A published rate schedule (CPWD DSR, state PWD SOR, and equivalents).

    Distinct from a bill of quantities: a BOQ prices one project's quantities, while a schedule of
    rates is the reference rate list a whole department procures against. Widely published, revised
    periodically, and useful for rate benchmarking — one of the directions discovery may point.
    """
    CHANGE_ORDER = "change_order"

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
        DocumentType.INVOICE: DocumentCategory.FINANCIAL,
        DocumentType.DELIVERY_CHALLAN: DocumentCategory.PROCUREMENT,
        DocumentType.GOODS_RECEIPT_NOTE: DocumentCategory.PROCUREMENT,
        DocumentType.MATERIAL_TEST_CERTIFICATE: DocumentCategory.MATERIAL,
        DocumentType.INSPECTION_REPORT: DocumentCategory.ENGINEERING,
        DocumentType.CHANGE_ORDER: DocumentCategory.LEGAL,
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
