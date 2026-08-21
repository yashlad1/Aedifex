"""The product-facing projection of internal state, and why it is not the internal state.

Two vocabularies meet here. Inside, a document has a
:class:`~aedifex.domain.documents.DocumentState` that exists to make a crawl resumable —
``discovered``, ``downloading``, ``validated`` — and a
:class:`~aedifex.domain.documents.DocumentType` that exists so an extractor knows what it reads.
Neither is a sentence a quantity surveyor would say. This module maps both onto what a reviewer
actually asks:

* *Has Aedifex read this yet, and does it need me?* — :class:`ProcessingStatus`
* *Which links of the chain do we have evidence for?* — :class:`WorkflowCategory`

Kept in ``domain`` and deliberately free of dependencies on ``extraction`` or ``verification``:
:func:`processing_status` takes booleans rather than reaching for the readable-format set or the
findings table, so the projection stays a pure function that a test can enumerate. The layers that
know those things pass what they know.

The point of the projection is that internal states must not leak merely because they exist. A user
told a document is ``validated`` learns nothing; a user told it is ``unsupported`` learns that the
bytes are safely held and no extractor can read them, which is a legitimate and honest answer.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

from aedifex.domain.documents import DocumentState, DocumentType

__all__ = [
    "WORKFLOW_CATEGORY",
    "ProcessingStatus",
    "WorkflowCategory",
    "processing_status",
    "workflow_category",
]


class ProcessingStatus(StrEnum):
    """Where one document has got to, in the six words a user needs.

    Six, not eight, and not the same six as ``DocumentState``. The mapping is in
    :func:`processing_status`.
    """

    UPLOADED = "uploaded"
    """Held, provenanced, and not yet read.

    Named for the product's dominant path. A crawled document awaiting analysis reads the same,
    because the difference between fetched and handed over is provenance rather than status, and
    provenance is reported separately.
    """

    PROCESSING = "processing"
    PROCESSED = "processed"
    """Read, and nothing is waiting for a person."""

    NEEDS_ATTENTION = "needs_attention"
    """Read, and at least one finding is unreviewed and not a pass.

    Derived from findings *and their reviews*, so accepting or rejecting the last open finding
    clears it, and revising a rule — which makes prior reviews stale — brings it back. That is the
    only place in this module where human review changes what a user sees.
    """

    UNSUPPORTED = "unsupported"
    """No extractor exists for this format. A legitimate outcome, not a failure.

    The bytes are stored, hashed and provenanced exactly like everything else; what is missing is a
    reader. Saying so is what stops an operator hunting for a corrupt download that does not exist.
    """

    FAILED = "failed"
    """A reader existed, ran, and could not finish. Distinct from ``UNSUPPORTED`` on purpose."""


def processing_status(
    state: DocumentState,
    *,
    is_readable: bool,
    needs_attention: bool,
) -> ProcessingStatus:
    """Project one document's internal state onto what a user is shown.

    ============================  ==================================
    Internal                      Shown
    ============================  ==================================
    ``failed``                    ``failed``
    ``quarantined``               ``needs_attention``
    no reader for the format      ``unsupported``
    ``processing``                ``processing``
    ``processed``                 ``processed`` / ``needs_attention``
    anything earlier              ``uploaded``
    ============================  ==================================

    ``failed`` is tested before readability because the two answer different questions and the
    specific one wins: if an extractor ran and failed, "no reader exists" is untrue.

    ``quarantined`` maps to ``needs_attention`` rather than ``failed`` because it is terminal only
    until a person decides — which is precisely what that status asks for.

    Args:
        is_readable: Whether an extractor exists for the document's format. Passed in rather than
            derived here, to keep this module independent of the extraction layer.
        needs_attention: Whether any finding is not a pass and has no current review.
    """
    if state is DocumentState.FAILED:
        return ProcessingStatus.FAILED
    if state is DocumentState.QUARANTINED:
        return ProcessingStatus.NEEDS_ATTENTION
    if not is_readable:
        return ProcessingStatus.UNSUPPORTED
    if state is DocumentState.PROCESSING:
        return ProcessingStatus.PROCESSING
    if state is DocumentState.PROCESSED:
        return ProcessingStatus.NEEDS_ATTENTION if needs_attention else ProcessingStatus.PROCESSED
    return ProcessingStatus.UPLOADED


class WorkflowCategory(StrEnum):
    """Which link of the construction chain a document is evidence for.

    The chain is the one in SRS §14.1 — ``Project → Contract → BOQ → Measurement → RA Bill →
    Certification → Payment → Variation → Quality Evidence`` — and these categories are its links,
    coarsened to what a reviewer can act on. The question they answer is "which parts of this
    project can be verified at all?", which is why absence is as informative as presence: a project
    with a BOQ and an RA bill but nothing under ``MEASUREMENT`` cannot have over-certification
    checked, and the summary should make that obvious without an explanation.

    Not the same as :class:`~aedifex.domain.documents.DocumentCategory`, which partitions documents
    by business domain for a data room. This partitions them by *what they let you verify*.
    """

    CONTRACT = "contract"
    """The commercial basis: the agreement and the procurement record that produced it."""

    BOQ = "boq"
    MEASUREMENT = "measurement"
    RA_BILL = "ra_bill"
    """What is claimed and what is certified — the claim side of the money chain."""

    VARIATION = "variation"
    MATERIAL = "material"
    """Purchase orders, challans, receipt notes: the consumption-versus-issued chain."""

    QUALITY = "quality"

    REFERENCE = "reference"
    """Documents that govern the flow without belonging to it: rate schedules, specifications,
    model agreements, audit reports.

    Its own category rather than ``OTHER``, because the distinction is the one this project has paid
    most to learn. A schedule of rates states norms about every project of its class; filed beside a
    tender notice under "other", it reads like project evidence, and five false facts came from
    exactly that confusion.
    """

    OTHER = "other"


# Every DocumentType must appear. ``tests/unit/test_domain_workflow.py`` enforces exhaustiveness, so
# a newly added type cannot silently land in OTHER.
WORKFLOW_CATEGORY: Final[MappingProxyType[DocumentType, WorkflowCategory]] = MappingProxyType(
    {
        # The commercial basis. A notice, a bid and an award are the record of how the contract came
        # to exist, and a reviewer asking "do we have the contract?" means all of it.
        DocumentType.CONTRACT: WorkflowCategory.CONTRACT,
        DocumentType.TENDER_NOTICE: WorkflowCategory.CONTRACT,
        DocumentType.BID_DOCUMENT: WorkflowCategory.CONTRACT,
        DocumentType.AWARD_NOTICE: WorkflowCategory.CONTRACT,
        DocumentType.CORRIGENDUM: WorkflowCategory.CONTRACT,
        DocumentType.BILL_OF_QUANTITIES: WorkflowCategory.BOQ,
        DocumentType.MEASUREMENT_BOOK: WorkflowCategory.MEASUREMENT,
        # Claim and certification together: a running bill claims, a certificate certifies, an
        # invoice demands. Separating them would suggest Aedifex can check the certification link,
        # and no document in the corpus yet lets it.
        DocumentType.RUNNING_BILL: WorkflowCategory.RA_BILL,
        DocumentType.PAYMENT_CERTIFICATE: WorkflowCategory.RA_BILL,
        DocumentType.INVOICE: WorkflowCategory.RA_BILL,
        DocumentType.CHANGE_ORDER: WorkflowCategory.VARIATION,
        DocumentType.PURCHASE_ORDER: WorkflowCategory.MATERIAL,
        DocumentType.DELIVERY_CHALLAN: WorkflowCategory.MATERIAL,
        DocumentType.GOODS_RECEIPT_NOTE: WorkflowCategory.MATERIAL,
        DocumentType.INSPECTION_REPORT: WorkflowCategory.QUALITY,
        DocumentType.MATERIAL_TEST_CERTIFICATE: WorkflowCategory.QUALITY,
        # Governs without belonging. See WorkflowCategory.REFERENCE.
        DocumentType.SCHEDULE_OF_RATES: WorkflowCategory.REFERENCE,
        DocumentType.TECHNICAL_SPECIFICATION: WorkflowCategory.REFERENCE,
        DocumentType.MODEL_AGREEMENT: WorkflowCategory.REFERENCE,
        DocumentType.AUDIT_REPORT: WorkflowCategory.REFERENCE,
        # A drawing is project evidence, but nothing reads one, so promising a link it cannot
        # support would be worse than filing it honestly.
        DocumentType.DRAWING: WorkflowCategory.OTHER,
        DocumentType.BANK_GUARANTEE: WorkflowCategory.OTHER,
        DocumentType.UNKNOWN: WorkflowCategory.OTHER,
    }
)


def workflow_category(document_type: DocumentType) -> WorkflowCategory:
    """Return which link of the chain ``document_type`` is evidence for."""
    return WORKFLOW_CATEGORY[document_type]
