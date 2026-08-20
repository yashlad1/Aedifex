"""Shared vocabulary for the evidence layer: fact kinds, document roles, relationship types.

In ``domain/`` for the same reason as :mod:`aedifex.domain.documents` — this is the vocabulary every
other layer reads, so adding a term is one reviewable change rather than a string literal spreading
through extractors, rules, and API responses.

The distinction that earns this module its place is between *what a fact is about* and *what a
fact means*. ``estimated_cost`` and ``invoice_total`` are different facts; both are
:attr:`FactKind.MONEY`. A rule comparing two amounts needs the second answer and should not have to
know the first, which is what lets one cross-document comparison serve every money fact this project
will ever extract instead of being rewritten per document type.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["DocumentRole", "FactKind", "FactOrigin", "RelationshipType"]


class FactOrigin(StrEnum):
    """Whether a value was read out of a document or computed from values that were.

    The distinction the SRS draws between facts and derived facts, made explicit so a reader of a
    finding can tell at a glance which of its inputs a document actually states. A derived fact is
    every bit as citable — it records its inputs and its calculation — but nobody wrote it down, and
    presenting the two identically would blur that.
    """

    EXTRACTED = "extracted"
    DERIVED = "derived"


class FactKind(StrEnum):
    """What kind of value a fact holds, independent of which field it came from.

    Deliberately small. These are the kinds the SRS names, and a kind is added when a real
    extractor produces one — not in advance, because an unused kind is a guess about a document
    nobody has read yet.
    """

    MONEY = "money"
    QUANTITY = "quantity"
    PERCENTAGE = "percentage"
    DATE = "date"
    DURATION = "duration"
    IDENTIFIER = "identifier"
    COMPANY = "company"
    LOCATION = "location"
    DOCUMENT_REFERENCE = "document_reference"
    TEXT = "text"

    @property
    def is_comparable(self) -> bool:
        """Whether two facts of this kind can be compared arithmetically.

        Money, quantities, percentages and durations carry a magnitude. An identifier does not:
        two tender numbers are equal or they are not, and asking which is larger is meaningless.
        """
        return self in {
            FactKind.MONEY,
            FactKind.QUANTITY,
            FactKind.PERCENTAGE,
            FactKind.DURATION,
        }


class DocumentRole(StrEnum):
    """What part a document plays within its project.

    Assigned from evidence or left ``UNCLASSIFIED``. Guessing a role from a filename or a page count
    would put an unsourced claim at the root of every relationship built on it.
    """

    TENDER_NOTICE = "tender_notice"
    BID_DOCUMENT = "bid_document"
    CONTRACT = "contract"
    BILL_OF_QUANTITIES = "bill_of_quantities"
    MEASUREMENT_BOOK = "measurement_book"
    RUNNING_BILL = "running_bill"
    INVOICE = "invoice"
    PAYMENT_CERTIFICATE = "payment_certificate"
    INSPECTION_REPORT = "inspection_report"
    COMPLETION_CERTIFICATE = "completion_certificate"
    CORRIGENDUM = "corrigendum"
    UNCLASSIFIED = "unclassified"


class RelationshipType(StrEnum):
    """How one document relates to another, within one project.

    Most of these cannot yet be established from the documents this project holds. They are declared
    anyway because the set is the vocabulary a rule writes against, and a relationship that has no
    name cannot be stored. Only :attr:`SAME_TENDER` is currently derivable — from two documents
    stating an identical tender identifier, which is exact string equality on extracted facts rather
    than inference.
    """

    SAME_TENDER = "same_tender"
    """Both documents concern one tender. Established by a shared identifier fact."""

    SAME_CONTRACT = "same_contract"
    """Both documents concern one contract. Needs a contract identifier nothing yet extracts."""

    AMENDMENT_OF = "amendment_of"
    """This document amends the other. A corrigendum is the common case."""

    AMENDS = "amends"
    SUPERSEDES = "supersedes"
    PARENT_DOCUMENT = "parent_document"
    """The other document contains this one, e.g. a notice bound into a full bid document."""

    CHILD_DOCUMENT = "child_document"
    INVITES_BIDS_FOR = "invites_bids_for"
    AWARDS = "awards"
    PRICES = "prices"
    MEASURES = "measures"
    CLAIMS_AGAINST = "claims_against"
    CERTIFIES = "certifies"
    REFERENCES = "references"

    @property
    def is_symmetric(self) -> bool:
        """Whether the relationship reads the same in both directions.

        ``SAME_TENDER`` and ``SAME_CONTRACT`` do; ``AMENDMENT_OF`` does not. This decides whether
        one stored row is the whole truth or only half of it.
        """
        return self in {RelationshipType.SAME_TENDER, RelationshipType.SAME_CONTRACT}

    @property
    def inverse(self) -> RelationshipType:
        """The relationship read from the other document's point of view.

        Symmetric types are their own inverse. Named pairs are inverted; anything without a declared
        opposite returns itself, which is honest — an inverse that has no name cannot be stored, and
        inventing one would put a relationship in the database that no vocabulary defines.
        """
        pairs = {
            RelationshipType.PARENT_DOCUMENT: RelationshipType.CHILD_DOCUMENT,
            RelationshipType.CHILD_DOCUMENT: RelationshipType.PARENT_DOCUMENT,
        }
        return pairs.get(self, self)
