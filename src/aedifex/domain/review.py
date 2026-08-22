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

import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import StrEnum

__all__ = ["ReviewDecision", "conclusion_fingerprint"]


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


def conclusion_fingerprint(
    *,
    rule_id: str,
    rule_version: str,
    outcome: str,
    expected: str,
    observed: str,
    detail: Mapping[str, object],
    evidence: Sequence[Sequence[str | None]],
) -> str:
    """A digest of the conclusion a reviewer was looking at.

    **Why this exists.** A review used to be bound to the finding's ``outcome`` and
    ``rule_version``, on the reasoning that a review decides a verdict rather than a rule id. That
    was half right. The verdict is not the word ``FAIL`` — it is the whole comparison, and a
    re-read can change every number in it while leaving that word alone:

    .. code-block:: text

        reviewed:   FAIL   claim 520 m3 exceeds the measured 470 m3     accepted by a QS
        re-read:    FAIL   claim 900 m3 exceeds the measured 470 m3     same outcome, same rule

    Under the old comparison the acceptance carried straight over to a conclusion nobody had read.
    This is not hypothetical: the corpus already contains a document whose ``estimated_cost`` moved
    from ₹73,86,43,489.22 to ₹85,39,81,318.41 between extractor versions, because version 3 read the
    civil component and version 4 read the total.

    **What is included, and why each.** ``rule_id`` and ``rule_version`` identify what was checked;
    ``outcome``, ``expected`` and ``observed`` are the verdict and the two values compared;
    ``detail`` holds the rule's own numbers; and ``evidence`` is what the reviewer could click
    through to, in a stable order.

    **What is deliberately excluded.** The finding's ``summary`` prose — a rule whose sentence is
    reworded has not changed its conclusion, and invalidating every review over a better wording
    would teach reviewers their work is disposable. And evidence *row identifiers*: a re-extraction
    that writes new rows carrying the same values at the same places has not changed what a reviewer
    read, so the citation is described by its content rather than by its primary key.

    Args:
        detail: The rule's stored detail. Serialised with sorted keys, so a dictionary that changes
            only in iteration order does not change the fingerprint.
        evidence: One sequence per citation, already ordered by the caller — role, kind, and the
            value and location as displayed. ``None`` entries are permitted and are distinct from
            the empty string, since "no page" and "page ''" are different claims.
    """
    payload = {
        "rule": [rule_id, rule_version],
        "verdict": [outcome, expected, observed],
        "detail": {key: str(value) for key, value in sorted(detail.items())},
        "evidence": [list(item) for item in evidence],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
