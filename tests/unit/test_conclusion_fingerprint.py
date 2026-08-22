"""What a review is bound to, and why the binding is the whole conclusion.

Justified by failure mode. The defect this pins was silent and consequential in one direction only:
an acceptance surviving onto a conclusion nobody read. Nothing about the system would look wrong
afterwards — the finding shows "accepted", the reviewer's note is
there, and the numbers underneath it are different ones.
"""

from __future__ import annotations

from aedifex.domain.review import conclusion_fingerprint

_BASE = {
    "rule_id": "claim_within_measured_quantity",
    "rule_version": "1",
    "outcome": "review",
    "expected": "claim <= measured",
    "observed": "520 m3",
    "detail": {"measured": "470", "claimed": "520", "variance": "50"},
    "evidence": [("claim", "extracted", "cumulative_claim_quantity", "520", "520", "page:1")],
}


def _with(**changes: object) -> str:
    return conclusion_fingerprint(**{**_BASE, **changes})  # type: ignore[arg-type]


class TestWhatChangesIt:
    def test_the_same_conclusion_digests_the_same(self) -> None:
        assert _with() == _with()

    def test_a_different_observed_value_is_a_different_conclusion(self) -> None:
        """The case the previous comparison missed entirely.

        Same rule, same version, same verdict word, different number. A reviewer who accepted
        "claim 520 exceeds measured 470" has not accepted "claim 900 exceeds measured 470".
        """
        assert _with(observed="900 m3") != _with()

    def test_a_different_comparison_is_a_different_conclusion(self) -> None:
        assert _with(detail={"measured": "470", "claimed": "900", "variance": "430"}) != _with()

    def test_different_evidence_is_a_different_conclusion(self) -> None:
        """Cited values and locations are part of what was reviewed.

        The reviewer clicked through to a cell. If the citation now points somewhere else, or says
        something else, they have not checked it.
        """
        moved = [("claim", "extracted", "cumulative_claim_quantity", "520", "520", "page:7")]
        relabelled = [("claim", "extracted", "cumulative_claim_quantity", "900", "900", "page:1")]
        assert _with(evidence=moved) != _with()
        assert _with(evidence=relabelled) != _with()

    def test_a_revised_rule_or_a_changed_verdict_still_changes_it(self) -> None:
        """The two cases the old comparison did catch. They must keep working."""
        assert _with(rule_version="2") != _with()
        assert _with(outcome="fail") != _with()

    def test_a_dropped_citation_changes_it(self) -> None:
        assert _with(evidence=[]) != _with()


class TestWhatDoesNotChangeIt:
    def test_detail_key_order_does_not_matter(self) -> None:
        """A dictionary that differs only in iteration order is the same conclusion."""
        reordered = {"variance": "50", "claimed": "520", "measured": "470"}
        assert _with(detail=reordered) == _with()

    def test_the_summary_is_not_part_of_it(self) -> None:
        """Asserted by construction: the function takes no summary.

        A rule whose sentence is reworded has not changed its conclusion, and invalidating every
        review over better prose would teach reviewers that their work is disposable. A rule whose
        *logic* changes gets a new version, which does change the digest.
        """
        assert "summary" not in conclusion_fingerprint.__code__.co_varnames

    def test_it_is_a_sha256_hex_digest(self) -> None:
        digest = _with()
        assert len(digest) == 64
        assert all(character in "0123456789abcdef" for character in digest)
