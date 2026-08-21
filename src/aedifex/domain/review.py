"""What a human can conclude about a finding, and why the vocabulary is this short.

The last stage of the pipeline in [SRS §6](../../../SRS.md) is ``Findings → Human Review → Business
Decision``, and until now it had no implementation at all. That mattered beyond completeness: the
trust boundary this project is built on says an uncertain reading becomes a financial fact **only
when deterministic validation closes or a human accepts it**, and the second half of that sentence
was not expressible.

Three decisions, not five. Each one exists because it leads somewhere different:

* ``ACCEPTED`` — the finding is real. Something should happen off-platform.
* ``REJECTED`` — the finding is wrong. This is the feedback channel for a bad rule or a misread
  document, and counting rejections per rule is how a rule earns revision.
* ``NEEDS_EVIDENCE`` — a person looked and could not decide, because the document that would settle
  it is not in the corpus. Deliberately distinct from an unreviewed finding and from
  ``INCONCLUSIVE``: the rule was conclusive, the *reviewer* is not.

Anything richer — assignment, severity, due dates, escalation chains — is workflow software, and
none of it is needed to record what a person concluded.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ReviewDecision"]


class ReviewDecision(StrEnum):
    """A reviewer's conclusion about one finding, stored verbatim as the ``decision`` column."""

    ACCEPTED = "accepted"
    """The reviewer agrees: the finding is correct and stands."""

    REJECTED = "rejected"
    """The reviewer judges the finding wrong — a false positive.

    Not a deletion. The finding, its evidence and this rejection all remain readable, because "the
    rule fired and a human disagreed" is more useful than either fact alone, and because a rule that
    is rejected repeatedly is the strongest available evidence that it needs changing.
    """

    NEEDS_EVIDENCE = "needs_evidence"
    """A person looked and cannot conclude without a document the corpus does not hold.

    The most product-relevant of the three, because it names an acquisition requirement in the
    reviewer's own words at the moment they hit it — which is exactly the signal a corpus roadmap
    should be built from, rather than from what happens to be public.
    """
