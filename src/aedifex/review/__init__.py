"""Recording what a person concluded about a finding.

Its own package rather than a function in ``extraction.store`` because it is not extraction. Every
other write here is a machine asserting something about a document; this is the one place a human
asserts something about a machine's conclusion, and keeping that seam visible is the point.

Deliberately tiny. Two functions: record a decision, and read the decisions back. No assignment, no
queues, no notifications, no state machine — those are workflow software, and none of them is needed
to answer "did a person look at this, and what did they say?"
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex import __version__
from aedifex.domain.review import ReviewDecision
from aedifex.errors import AedifexError
from aedifex.infrastructure.database.models import Finding, FindingReview
from aedifex.infrastructure.observability.logging import get_logger

__all__ = [
    "ReviewError",
    "record_review",
    "reviews_for",
]

_log = get_logger(__name__)


class ReviewError(AedifexError):
    """A review that cannot be recorded as asked."""


def record_review(
    session: Session,
    finding_id: uuid.UUID,
    *,
    decision: ReviewDecision,
    note: str,
    reviewer: str,
) -> FindingReview:
    """Record one person's decision about one finding.

    The outcome and rule version the reviewer was looking at are captured from the finding **at the
    moment of review**, not supplied by the caller. That is what makes the record honest: a reviewer
    can only have been reviewing what the finding said when they read it, and a later change to the
    rule must invalidate this decision rather than inherit it. See
    :attr:`~aedifex.infrastructure.database.models.Finding.current_review`.

    Appends. An existing review is never updated and never replaced, because a second reviewer
    disagreeing with the first is exactly the thing an audit trail is for.

    Args:
        finding_id: The finding being decided.
        decision: What the reviewer concluded.
        note: Why, in prose. Required and must not be blank.
        reviewer: Who decided, as the caller knows them.

    Raises:
        ReviewError: if the finding does not exist, or if the note or reviewer is blank.
    """
    if not note.strip():
        raise ReviewError(
            "a review needs a reason: a decision with no note is indistinguishable from a mis-click"
        )
    if not reviewer.strip():
        raise ReviewError("a review needs a reviewer, because judgement has to be attributable")

    finding = session.get(Finding, finding_id)
    if finding is None:
        raise ReviewError(f"no finding {finding_id}")

    review = FindingReview(
        finding_id=finding.id,
        decision=decision.value,
        note=note.strip(),
        reviewer=reviewer.strip(),
        # Read from the finding, never from the caller. See the docstring.
        reviewed_outcome=finding.outcome,
        reviewed_rule_version=finding.rule_version,
        software_version=__version__,
    )
    session.add(review)
    session.flush()

    _log.info(
        "review.recorded",
        finding_id=str(finding.id),
        rule_id=finding.rule_id,
        decision=decision.value,
        reviewed_outcome=finding.outcome,
        reviewer=review.reviewer,
    )
    return review


def reviews_for(session: Session, finding_id: uuid.UUID) -> Sequence[FindingReview]:
    """Every review of one finding, oldest first. Empty means nobody has looked."""
    return list(
        session.execute(
            select(FindingReview)
            .where(FindingReview.finding_id == finding_id)
            .order_by(FindingReview.reviewed_at)
        ).scalars()
    )
