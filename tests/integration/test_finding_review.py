"""Human review: the pipeline's last stage, and the one place judgement enters the system.

Integration rather than unit, because the properties worth testing are database properties — the
row is append-only, the check constraints hold, and staleness is decided by comparing stored columns
against the finding as it now stands.

Justified as a test under the project's rules on two of the five grounds: it is the trust boundary
(commitment 3 of ADR 0016/0017 is unimplementable without it), and staleness is a correctness
property whose failure mode is silent — an accepted FAIL presenting as an accepted PASS.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.acquisition.content import document_id_for_digest
from aedifex.domain.documents import DocumentCategory, DocumentType
from aedifex.domain.files import FileFormat
from aedifex.domain.review import ReviewDecision
from aedifex.infrastructure.database.models import Document, Finding, FindingReview
from aedifex.review import ReviewError, record_review


def _current(finding: Finding) -> FindingReview | None:
    """Read ``current_review`` through a function, so mypy cannot narrow it across assertions.

    These tests deliberately assert that the same property is first non-``None`` and later ``None``
    — that *is* staleness. Read directly, mypy narrows the first assertion and calls the second one
    unreachable, which is a true statement about its own inference and a false one about the code.
    """
    return finding.current_review


def _finding(session: Session, *, outcome: str = "review", rule_version: str = "1") -> Finding:
    """A document and one finding against it, persisted."""
    digest = f"{uuid.uuid4().hex}{uuid.uuid4().hex}"[:64]
    document = Document(
        id=document_id_for_digest(digest),
        sha256=digest,
        size_bytes=1,
        file_format=FileFormat.PDF,
        storage_key=f"raw/test/{digest[:2]}/{digest[2:4]}/{digest}.pdf",
        document_type=DocumentType.BILL_OF_QUANTITIES,
        document_category=DocumentCategory.FINANCIAL,
        state="downloaded",
    )
    session.add(document)
    session.flush()
    finding = Finding(
        document_id=document.id,
        rule_id="row_arithmetic_closes",
        rule_version=rule_version,
        outcome=outcome,
        summary="Item 4.26: 86 x 631.00 = 54,266.00 but the bill states 54,518.40",
        expected="quantity x rate, within display rounding",
        observed="54,518.40",
    )
    session.add(finding)
    session.flush()
    return finding


class TestRecording:
    def test_a_decision_is_attributable_and_durable(self, session: Session) -> None:
        finding = _finding(session)

        review = record_review(
            session,
            finding.id,
            decision=ReviewDecision.ACCEPTED,
            note="Checked the page: the bill really does state 54,518.40.",
            reviewer="qs.reviewer",
        )

        assert review.decision == ReviewDecision.ACCEPTED.value
        assert review.reviewer == "qs.reviewer"
        # Read off the finding, never from the caller: the record says what was actually judged.
        assert review.reviewed_outcome == "review"
        assert review.reviewed_rule_version == "1"

    def test_a_second_review_appends_and_becomes_current(self, session: Session) -> None:
        """A senior reviewer disagreeing with a junior one is what an audit trail is for."""
        finding = _finding(session)
        record_review(
            session,
            finding.id,
            decision=ReviewDecision.ACCEPTED,
            note="Looks like a real overstatement.",
            reviewer="junior",
        )
        record_review(
            session,
            finding.id,
            decision=ReviewDecision.REJECTED,
            note="No: the parser paired the wrong rate. Rule needs revising, bill is fine.",
            reviewer="senior",
        )
        session.expire(finding)

        assert len(finding.reviews) == 2, "the first review must not be replaced"
        assert [r.reviewer for r in finding.reviews] == ["junior", "senior"]
        current = finding.current_review
        assert current is not None
        assert current.decision == ReviewDecision.REJECTED.value

    @pytest.mark.parametrize(
        ("note", "reviewer"),
        [("   ", "someone"), ("a reason", "  ")],
    )
    def test_a_review_needs_a_reason_and_an_author(
        self, session: Session, note: str, reviewer: str
    ) -> None:
        finding = _finding(session)
        with pytest.raises(ReviewError):
            record_review(
                session,
                finding.id,
                decision=ReviewDecision.ACCEPTED,
                note=note,
                reviewer=reviewer,
            )

    def test_reviewing_an_absent_finding_is_refused(self, session: Session) -> None:
        with pytest.raises(ReviewError, match="no finding"):
            record_review(
                session,
                uuid.uuid4(),
                decision=ReviewDecision.ACCEPTED,
                note="n/a",
                reviewer="someone",
            )


class TestConclusionBinding:
    """A review is bound to the conclusion, not only to the verdict word.

    The defect an independent review found, and the one worth the most: until 2026-08-22 staleness
    compared ``outcome`` and ``rule_version`` alone, so a re-read that changed every number while
    leaving the verdict alone kept the old acceptance. Nothing would look wrong afterwards — the
    finding shows "accepted", the note is there, and the numbers underneath it are different ones.
    """

    def test_a_changed_observed_value_makes_a_review_stale(self, session: Session) -> None:
        finding = _finding(session, outcome="fail")
        finding.observed = "54,518.40"
        finding.conclusion_fingerprint = finding.compute_fingerprint()
        session.flush()
        record_review(
            session,
            finding.id,
            decision=ReviewDecision.ACCEPTED,
            note="Checked the page: the bill really does state 54,518.40.",
            reviewer="qs",
        )
        assert _current(finding) is not None

        # A re-read of the same document under the same rule, producing a different number. Outcome
        # and rule version are untouched, which is exactly what used to slip through.
        finding.observed = "62,900.00"
        finding.conclusion_fingerprint = finding.compute_fingerprint()
        session.flush()
        session.expire(finding)

        assert _current(finding) is None, "an acceptance of 54,518.40 cannot speak for 62,900.00"
        assert len(finding.reviews) == 1, "and the review is kept, not deleted"

    def test_changed_evidence_makes_a_review_stale(self, session: Session) -> None:
        """The reviewer clicked through to a cell. A citation that moved has not been checked."""
        from aedifex.domain.evidence import FactKind
        from aedifex.infrastructure.database.models import ExtractedFact, FindingEvidence

        finding = _finding(session, outcome="review")
        fact = ExtractedFact(
            document_id=finding.document_id,
            fact_type="claimed_rate",
            kind=FactKind.MONEY,
            literal="74500",
            numeric_value=None,
            page=1,
            span_start=0,
            span_end=0,
            snippet="RA Bill!G8",
            method="cell:RA Bill!G8",
            extractor="test",
            extractor_version="1",
            sheet_name="RA Bill",
            sheet_row=8,
            sheet_column=7,
        )
        session.add(fact)
        session.flush()
        finding.evidence.append(FindingEvidence(fact_id=fact.id, role="claimed_rate"))
        session.flush()
        finding.conclusion_fingerprint = finding.compute_fingerprint()
        session.flush()
        record_review(
            session,
            finding.id,
            decision=ReviewDecision.ACCEPTED,
            note="Confirmed against RA Bill!G8.",
            reviewer="qs",
        )
        assert _current(finding) is not None

        # Re-extraction now cites a different cell for the same value.
        fact.sheet_row = 14
        fact.snippet = "RA Bill!G14"
        session.flush()
        finding.conclusion_fingerprint = finding.compute_fingerprint()
        session.flush()
        session.expire(finding)

        assert _current(finding) is None

    def test_an_identical_re_analysis_keeps_the_review(self, session: Session) -> None:
        """The other half, and the reason the digest is content-based rather than row-based.

        Re-running analysis that reaches the same conclusion from the same values must not throw a
        reviewer's work away. A fingerprint over evidence *row ids* would have done exactly that on
        every extractor-version bump.
        """
        finding = _finding(session, outcome="fail")
        finding.conclusion_fingerprint = finding.compute_fingerprint()
        session.flush()
        record_review(
            session,
            finding.id,
            decision=ReviewDecision.REJECTED,
            note="The parser paired the wrong rate.",
            reviewer="senior",
        )

        finding.conclusion_fingerprint = finding.compute_fingerprint()
        session.flush()
        session.expire(finding)

        current = _current(finding)
        assert current is not None
        assert current.decision == ReviewDecision.REJECTED.value


class TestOrdering:
    def test_two_reviews_in_one_transaction_are_ordered(self, session: Session) -> None:
        """``now()`` is the transaction's start time, so both rows shared a timestamp.

        Which review is *current* depended on the order the planner happened to return, and the
        earlier version of this file asserted an order it could not guarantee. ``reviewed_at`` is
        now ``clock_timestamp()``, with the id as a tiebreak.
        """
        finding = _finding(session)
        first = record_review(
            session,
            finding.id,
            decision=ReviewDecision.ACCEPTED,
            note="Looks real.",
            reviewer="junior",
        )
        second = record_review(
            session,
            finding.id,
            decision=ReviewDecision.REJECTED,
            note="No: the parser paired the wrong rate.",
            reviewer="senior",
        )
        session.expire(finding)

        assert first.reviewed_at < second.reviewed_at, "one transaction, two distinct instants"
        assert [row.reviewer for row in finding.reviews] == ["junior", "senior"]


class TestStaleness:
    """The property whose failure is silent, and therefore the one worth a test.

    A review decides a verdict. If the verdict changes, the review must stop speaking for the
    finding — otherwise an accepted FAIL presents as an accepted PASS and a real finding disappears
    without anything being deleted.
    """

    def test_a_changed_outcome_makes_a_review_stale(self, session: Session) -> None:
        finding = _finding(session, outcome="fail")
        record_review(
            session,
            finding.id,
            decision=ReviewDecision.ACCEPTED,
            note="Confirmed against the page.",
            reviewer="qs",
        )
        assert _current(finding) is not None

        # Re-evaluation now says the bill is fine.
        finding.outcome = "pass"
        session.flush()
        session.expire(finding)

        assert _current(finding) is None, "a review of a FAIL cannot speak for a PASS"
        assert len(finding.reviews) == 1, "and the review is kept, not deleted"

    def test_a_revised_rule_makes_a_review_stale(self, session: Session) -> None:
        finding = _finding(session, rule_version="1")
        record_review(
            session,
            finding.id,
            decision=ReviewDecision.REJECTED,
            note="Threshold is wrong.",
            reviewer="contracts",
        )

        finding.rule_version = "2"
        session.flush()
        session.expire(finding)

        assert finding.current_review is None
        assert finding.reviews[0].reviewed_rule_version == "1"

    def test_re_reviewing_after_a_change_restores_a_current_decision(
        self, session: Session
    ) -> None:
        finding = _finding(session, outcome="fail")
        record_review(
            session,
            finding.id,
            decision=ReviewDecision.ACCEPTED,
            note="Real at v1.",
            reviewer="qs",
        )
        finding.outcome = "review"
        session.flush()

        record_review(
            session,
            finding.id,
            decision=ReviewDecision.NEEDS_EVIDENCE,
            note="Now downgraded to REVIEW; need the JMR to settle it.",
            reviewer="qs",
        )
        session.expire(finding)

        current = finding.current_review
        assert current is not None
        assert current.decision == ReviewDecision.NEEDS_EVIDENCE.value
        assert len(finding.reviews) == 2


class TestConstraints:
    def test_the_database_refuses_an_unknown_decision(self, session: Session) -> None:
        """Belt and braces: the service validates, and so does the table.

        The enum lives in Python, so a hand-written INSERT during an incident is the realistic way a
        bad value arrives.
        """
        finding = _finding(session)
        session.add(
            FindingReview(
                finding_id=finding.id,
                decision="probably_fine",
                note="n/a",
                reviewer="someone",
                reviewed_outcome=finding.outcome,
                reviewed_rule_version=finding.rule_version,
                software_version="0",
            )
        )
        with pytest.raises(Exception, match="decision_is_known"):
            session.flush()
        session.rollback()

    def test_reviews_are_removed_with_their_finding(self, session: Session) -> None:
        """CASCADE, because a review of a deleted finding says nothing about anything."""
        finding = _finding(session)
        record_review(
            session,
            finding.id,
            decision=ReviewDecision.ACCEPTED,
            note="fine",
            reviewer="someone",
        )
        finding_id = finding.id

        session.delete(finding)
        session.flush()

        remaining = session.execute(
            select(FindingReview).where(FindingReview.finding_id == finding_id)
        ).scalars()
        assert list(remaining) == []
