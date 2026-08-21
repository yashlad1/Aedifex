"""The classifier: what it proposes, and the line it must never cross.

Justified as a test because the boundary is a safety property, not a quality one. Accuracy on
filenames is worth little and will change; what must not change is that a proposal stays a proposal.
Two specific traps are pinned here — a model agreement is indistinguishable from an executed
contract by name, and an unnamed file must produce silence rather than a weak guess, because silence
and disagreement mean different things in the workspace.
"""

from __future__ import annotations

import pytest

from aedifex.classification import (
    CLASSIFIER,
    classifier_identity,
    suggest_document_type,
)
from aedifex.domain.documents import DocumentType


class TestRealFilenames:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            # From the acquired IIT Bombay building corpus.
            ("iitb-h19-priced-bill-of-quantities.pdf", DocumentType.BILL_OF_QUANTITIES),
            ("iitb-h19-notice-inviting-tender-r1-2022-10-31.pdf", DocumentType.TENDER_NOTICE),
            ("iitb-h19-technical-specification-vol1.pdf", DocumentType.TECHNICAL_SPECIFICATION),
            ("iitb-h19-financial-bid-percentage-on-estimate.pdf", DocumentType.BID_DOCUMENT),
            ("iitb-h19-conditions-of-contract.pdf", DocumentType.CONTRACT),
            # The filenames the owner said a customer would actually upload.
            ("BOQ.xlsx", DocumentType.BILL_OF_QUANTITIES),
            ("RA_Bill_17.xlsx", DocumentType.RUNNING_BILL),
            ("JMR_17.jpg", DocumentType.MEASUREMENT_BOOK),
            ("Architect Certificate.pdf", DocumentType.PAYMENT_CERTIFICATE),
            ("GST Invoice.pdf", DocumentType.INVOICE),
            ("Variation Order 3.pdf", DocumentType.CHANGE_ORDER),
        ],
    )
    def test_a_descriptive_name_is_read(self, filename: str, expected: DocumentType) -> None:
        suggestion = suggest_document_type(filename)
        assert suggestion is not None, f"{filename!r} names its own type and should be read"
        assert suggestion.document_type is expected

    def test_a_specification_amendment_is_a_specification(self) -> None:
        """A real filename that matches two rules, and the specific phrase has to win.

        ``cpwd-general-specifications-electrical-internal-2013-amendment-2.pdf`` contains both
        "specification" and "amendment". Reading it as a corrigendum would file a reference document
        as a change to one.
        """
        suggestion = suggest_document_type(
            "cpwd-general-specifications-electrical-internal-2013-amendment-2.pdf"
        )
        assert suggestion is not None
        assert suggestion.document_type is DocumentType.TECHNICAL_SPECIFICATION


class TestSilence:
    @pytest.mark.parametrize(
        "filename", ["scan0007.pdf", "document (1).pdf", "IMG_2231.jpg", "", "   ", ".pdf"]
    )
    def test_an_uninformative_name_produces_no_suggestion(self, filename: str) -> None:
        """No suggestion and a weak suggestion are different things.

        Silence means the workspace shows the declared type unchallenged. A weak guess would mean
        something disagrees with it, which would put a "disputed classification" badge on every
        scanned page in the corpus.
        """
        assert suggest_document_type(filename) is None

    def test_a_type_with_no_rule_is_not_invented(self) -> None:
        """Two document classes on the product's own priority list have no type yet.

        A material reconciliation statement and a completion certificate are both things a
        customer will upload, and neither has a ``DocumentType``. The honest behaviour is no
        suggestion — they file as ``unknown`` and stay visible — rather than proposing the nearest
        available label.
        """
        assert suggest_document_type("Material Reconciliation Statement.xlsx") is None
        assert suggest_document_type("Completion Certificate.pdf") is None


class TestBoundaries:
    def test_a_model_agreement_is_never_proposed(self) -> None:
        """The one type a classifier must not reach for, and the reason the boundary exists.

        A model concession agreement and an executed one are the same clauses in the same order, and
        the difference decides whether a quoted amount becomes a fact about the document. Nothing
        readable from a filename can settle it, so the classifier proposes ``contract`` and leaves
        the harder call to a person.
        """
        for filename in (
            "model-concession-agreement.pdf",
            "iitb-h19-conditions-of-contract.pdf",
            "gcc-2014.pdf",
            "agreement.pdf",
        ):
            suggestion = suggest_document_type(filename)
            proposed = None if suggestion is None else suggestion.document_type
            assert proposed is not DocumentType.MODEL_AGREEMENT

    def test_a_suggestion_is_attributable_and_deterministic(self) -> None:
        first = suggest_document_type("RA_Bill_17.xlsx")
        second = suggest_document_type("ra bill 17.xlsx")
        assert first is not None and second is not None
        assert first.document_type is second.document_type
        assert first.classifier == classifier_identity() == f"{CLASSIFIER}:1"
        assert first.matched in {"ra bill", "ra bill 17"}

    def test_confidence_stays_inside_the_column_s_constraint(self) -> None:
        """``documents.classification_confidence`` is checked to 0..1 by the database."""
        for filename in ("BOQ.xlsx", "invoice.pdf", "agreement.pdf", "drawing-01.pdf"):
            suggestion = suggest_document_type(filename)
            assert suggestion is not None
            assert 0.0 < suggestion.confidence <= 1.0
