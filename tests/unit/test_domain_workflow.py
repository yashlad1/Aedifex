"""The product-facing projection: status, and which link of the chain a document serves.

Justified as tests on two of the project's five grounds. Exhaustiveness is the same argument as
``test_domain_documents.py`` makes for ``DOCUMENT_TYPE_CATEGORY``: a document type added later must
not land silently in ``OTHER``, because a category nobody notices is worse than one that is wrong.
And the status projection is user-visible correctness — telling someone a document *failed* when no
extractor exists for it sends them looking for a corrupt file that does not exist, which is a real
support cost and has already happened once inside the CLI.
"""

from __future__ import annotations

import pytest

from aedifex.domain.documents import DocumentState, DocumentType
from aedifex.domain.files import FileFormat
from aedifex.domain.workflow import (
    WORKFLOW_CATEGORY,
    ProcessingStatus,
    WorkflowCategory,
    processing_status,
    workflow_category,
)


class TestWorkflowCategory:
    def test_every_document_type_has_a_category(self) -> None:
        missing = sorted(item.value for item in DocumentType if item not in WORKFLOW_CATEGORY)
        assert missing == [], "a new document type must be placed deliberately, not defaulted"

    def test_reference_documents_are_not_filed_as_other(self) -> None:
        """The distinction this project has paid most to learn.

        A schedule of rates states norms about every project of its class. Filed beside a tender
        notice under "other" it reads like project evidence, and five false facts came from exactly
        that confusion.
        """
        for document_type in (
            DocumentType.SCHEDULE_OF_RATES,
            DocumentType.MODEL_AGREEMENT,
            DocumentType.AUDIT_REPORT,
            DocumentType.TECHNICAL_SPECIFICATION,
        ):
            assert workflow_category(document_type) is WorkflowCategory.REFERENCE

    def test_the_money_chain_separates_quantity_measurement_and_claim(self) -> None:
        """Three links, three categories. A summary that merged them could not show a gap."""
        assert workflow_category(DocumentType.BILL_OF_QUANTITIES) is WorkflowCategory.BOQ
        assert workflow_category(DocumentType.MEASUREMENT_BOOK) is WorkflowCategory.MEASUREMENT
        assert workflow_category(DocumentType.RUNNING_BILL) is WorkflowCategory.RA_BILL


class TestProcessingStatus:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (DocumentState.DISCOVERED, ProcessingStatus.UPLOADED),
            (DocumentState.DOWNLOADING, ProcessingStatus.UPLOADED),
            (DocumentState.DOWNLOADED, ProcessingStatus.UPLOADED),
            (DocumentState.VALIDATED, ProcessingStatus.UPLOADED),
            (DocumentState.PROCESSING, ProcessingStatus.PROCESSING),
            (DocumentState.PROCESSED, ProcessingStatus.PROCESSED),
            (DocumentState.FAILED, ProcessingStatus.FAILED),
            (DocumentState.QUARANTINED, ProcessingStatus.NEEDS_ATTENTION),
        ],
    )
    def test_every_internal_state_projects_to_something(
        self, state: DocumentState, expected: ProcessingStatus
    ) -> None:
        assert (
            processing_status(state, is_readable=True, needs_attention=False) is expected
        ), "an unmapped state would show a user an internal word that means nothing to them"

    def test_no_reader_reads_as_unsupported_rather_than_failed(self) -> None:
        """A stored JSON response is evidence. It is simply not evidence anything can read yet."""
        assert (
            processing_status(DocumentState.DOWNLOADED, is_readable=False, needs_attention=False)
            is ProcessingStatus.UNSUPPORTED
        )

    def test_a_failed_run_beats_no_reader(self) -> None:
        """Order matters: if an extractor ran and failed, "no reader exists" is untrue."""
        assert (
            processing_status(DocumentState.FAILED, is_readable=False, needs_attention=False)
            is ProcessingStatus.FAILED
        )

    def test_an_open_finding_asks_for_a_person(self) -> None:
        assert (
            processing_status(DocumentState.PROCESSED, is_readable=True, needs_attention=True)
            is ProcessingStatus.NEEDS_ATTENTION
        )

    def test_attention_does_not_override_an_earlier_stage(self) -> None:
        """A document still being read cannot need attention: nothing has concluded yet."""
        assert (
            processing_status(DocumentState.PROCESSING, is_readable=True, needs_attention=True)
            is ProcessingStatus.PROCESSING
        )

    def test_the_readable_formats_are_the_extraction_layer_s_to_declare(self) -> None:
        """This module must not know which formats have readers, only that the caller does."""
        from aedifex.extraction import READABLE_FORMATS

        assert frozenset({FileFormat.PDF, FileFormat.XLSX}) == READABLE_FORMATS
