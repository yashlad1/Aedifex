"""Tests for the document vocabulary and the processing state machine."""

from __future__ import annotations

import itertools

import pytest

from aedifex.domain.documents import (
    DOCUMENT_TYPE_CATEGORY,
    STATE_TRANSITIONS,
    DocumentCategory,
    DocumentState,
    DocumentType,
    assert_transition_allowed,
    can_transition,
    category_for,
    is_terminal,
)
from aedifex.errors import InvalidStateTransitionError


class TestDocumentTypeCategories:
    def test_every_document_type_has_a_category(self) -> None:
        """A new document type must be classified explicitly, not defaulted.

        Without this, adding a type would silently leave it categorised as UNKNOWN and it
        would be excluded from every category-scoped query.
        """
        missing = set(DocumentType) - set(DOCUMENT_TYPE_CATEGORY)
        assert not missing, f"document types with no category: {sorted(t.value for t in missing)}"

    def test_no_category_mapping_for_unknown_types(self) -> None:
        assert set(DOCUMENT_TYPE_CATEGORY) <= set(DocumentType)

    def test_only_the_unknown_type_maps_to_the_unknown_category(self) -> None:
        unknown = {
            document_type
            for document_type, category in DOCUMENT_TYPE_CATEGORY.items()
            if category is DocumentCategory.UNKNOWN
        }
        assert unknown == {DocumentType.UNKNOWN}

    @pytest.mark.parametrize(
        ("document_type", "expected"),
        [
            (DocumentType.INVOICE, DocumentCategory.FINANCIAL),
            (DocumentType.PURCHASE_ORDER, DocumentCategory.PROCUREMENT),
            (DocumentType.MATERIAL_TEST_CERTIFICATE, DocumentCategory.MATERIAL),
            (DocumentType.CONTRACT, DocumentCategory.LEGAL),
            (DocumentType.INSPECTION_REPORT, DocumentCategory.ENGINEERING),
        ],
    )
    def test_representative_categories(
        self, document_type: DocumentType, expected: DocumentCategory
    ) -> None:
        assert category_for(document_type) is expected

    def test_the_payment_auditor_wedge_types_all_exist(self) -> None:
        """The nine document types the initial product must support."""
        required = {
            "contract",
            "bill_of_quantities",
            "purchase_order",
            "invoice",
            "delivery_challan",
            "goods_receipt_note",
            "material_test_certificate",
            "inspection_report",
            "change_order",
        }
        assert required <= {document_type.value for document_type in DocumentType}

    def test_values_are_stable_lower_snake_case(self) -> None:
        """Values are persisted in the database, so their spelling is a compatibility surface."""
        for document_type in DocumentType:
            assert document_type.value == document_type.value.lower()
            assert " " not in document_type.value
            assert "-" not in document_type.value


class TestStateMachine:
    def test_every_state_is_declared(self) -> None:
        assert set(STATE_TRANSITIONS) == set(DocumentState)

    def test_no_transition_targets_an_undeclared_state(self) -> None:
        for state, targets in STATE_TRANSITIONS.items():
            for target in targets:
                assert target in STATE_TRANSITIONS, f"{state} -> {target} is not a declared state"

    def test_no_state_transitions_to_itself(self) -> None:
        for state, targets in STATE_TRANSITIONS.items():
            assert state not in targets, f"{state} has a self-transition"

    def test_terminal_states(self) -> None:
        terminal = {state for state in DocumentState if is_terminal(state)}
        assert terminal == {DocumentState.PROCESSED, DocumentState.QUARANTINED}

    def test_every_state_is_reachable_from_discovered(self) -> None:
        """An unreachable state is dead code that will mislead an operator reading it."""
        reachable = {DocumentState.DISCOVERED}
        frontier = [DocumentState.DISCOVERED]
        while frontier:
            for target in STATE_TRANSITIONS[frontier.pop()]:
                if target not in reachable:
                    reachable.add(target)
                    frontier.append(target)
        assert reachable == set(DocumentState)

    def test_happy_path(self) -> None:
        path = [
            DocumentState.DISCOVERED,
            DocumentState.DOWNLOADING,
            DocumentState.DOWNLOADED,
            DocumentState.VALIDATED,
            DocumentState.PROCESSING,
            DocumentState.PROCESSED,
        ]
        for current, target in itertools.pairwise(path):
            assert can_transition(current, target), f"{current} -> {target} should be allowed"

    def test_failure_is_retryable(self) -> None:
        """A retry must be a legal state move, not a manual database edit."""
        assert can_transition(DocumentState.FAILED, DocumentState.DOWNLOADING)
        assert can_transition(DocumentState.FAILED, DocumentState.PROCESSING)

    def test_quarantine_is_not_self_serve(self) -> None:
        """Content that tripped a safety limit is released only by a human process."""
        assert STATE_TRANSITIONS[DocumentState.QUARANTINED] == frozenset()

    def test_processed_is_final(self) -> None:
        assert STATE_TRANSITIONS[DocumentState.PROCESSED] == frozenset()

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (DocumentState.DISCOVERED, DocumentState.PROCESSED),
            (DocumentState.DISCOVERED, DocumentState.VALIDATED),
            (DocumentState.PROCESSED, DocumentState.DOWNLOADING),
            (DocumentState.QUARANTINED, DocumentState.VALIDATED),
            (DocumentState.DOWNLOADED, DocumentState.PROCESSED),
        ],
    )
    def test_skipping_stages_is_rejected(
        self, current: DocumentState, target: DocumentState
    ) -> None:
        assert not can_transition(current, target)
        with pytest.raises(InvalidStateTransitionError):
            assert_transition_allowed(current, target)

    def test_error_message_lists_the_allowed_targets(self) -> None:
        with pytest.raises(InvalidStateTransitionError, match="downloading") as error:
            assert_transition_allowed(DocumentState.DISCOVERED, DocumentState.PROCESSED)
        assert "discovered" in str(error.value)

    def test_terminal_state_error_message_is_explicit(self) -> None:
        with pytest.raises(InvalidStateTransitionError, match="terminal"):
            assert_transition_allowed(DocumentState.PROCESSED, DocumentState.PROCESSING)

    def test_allowed_transition_does_not_raise(self) -> None:
        assert_transition_allowed(DocumentState.DISCOVERED, DocumentState.DOWNLOADING)
