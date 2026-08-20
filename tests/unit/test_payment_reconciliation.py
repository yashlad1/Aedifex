"""Payment reconciliation: the arithmetic, the units, the linkage, and one disagreement.

Scoped to what the milestone names and nothing more. These are the places where a wrong answer would
be both plausible and expensive: a variance computed from mismatched units, an item number that
should have matched and did not, and a claim exceeding measured work that came back PASS.

The synthetic project exercises the happy path end to end already. What it cannot show is the
refusals — a unit mismatch and a missing input produce *nothing*, and "nothing" is invisible in a
report.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from aedifex.calculation.engine import (
    compute_quantity_variance,
    compute_rate_variance,
    compute_unsupported_amount,
)
from aedifex.domain.evidence import FactKind
from aedifex.extraction.work_items import normalise_item
from aedifex.infrastructure.database.models import DerivedFact, ExtractedFact, WorkItem
from aedifex.verification.reconciliation import (
    WorkItemFacts,
    evaluate_claim_within_measured,
    evaluate_cumulative_not_regressed,
    evaluate_rate_matches_contract,
)
from aedifex.verification.rules import Outcome


def quantity(fact_type: str, value: Decimal | None, unit: str | None = "m3") -> ExtractedFact:
    return ExtractedFact(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        fact_type=fact_type,
        kind=FactKind.QUANTITY,
        literal=str(value),
        numeric_value=value,
        unit=unit,
        page=1,
        span_start=0,
        span_end=0,
        snippet="Sheet!A1",
        method="test",
        extractor="test",
        extractor_version="1",
    )


def money(fact_type: str, value: Decimal) -> ExtractedFact:
    fact = quantity(fact_type, value, None)
    fact.kind = FactKind.MONEY
    fact.currency = "INR"
    return fact


def derived(fact_type: str, value: Decimal, unit: str | None = "m3") -> DerivedFact:
    return DerivedFact(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        fact_type=fact_type,
        kind=FactKind.QUANTITY,
        numeric_value=value,
        unit=unit,
        calculation="difference",
        calculation_version="1",
        produced_by="test",
        expression="test",
    )


def item(unit: str = "m3") -> WorkItem:
    return WorkItem(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        item_identifier="4.7.2",
        normalised_identifier="4.7.2",
        description="RCC M30",
        unit=unit,
        matched_by="exact_identifier",
    )


def bundle(
    facts: dict[str, ExtractedFact], derived_facts: dict[str, DerivedFact] | None = None
) -> WorkItemFacts:
    return WorkItemFacts(work_item=item(), facts=facts, derived=derived_facts or {}, filenames={})


class TestArithmetic:
    def test_a_variance_is_the_exact_difference(self) -> None:
        result = compute_quantity_variance(
            {
                "cumulative_claim_quantity": quantity(
                    "cumulative_claim_quantity", Decimal("520.00")
                ),
                "measured_quantity": quantity("measured_quantity", Decimal("470.00")),
            }
        )
        assert result is not None
        assert result.value == Decimal("50")
        assert result.unit == "m3"
        assert result.expression == "520.00 - 470.00"

    def test_mismatched_units_are_refused_not_converted(self) -> None:
        """There is no density table here, and inventing one would fabricate a conversion."""
        assert (
            compute_quantity_variance(
                {
                    "cumulative_claim_quantity": quantity(
                        "cumulative_claim_quantity", Decimal("520"), "m3"
                    ),
                    "measured_quantity": quantity("measured_quantity", Decimal("470"), "MT"),
                }
            )
            is None
        )

    def test_a_unit_spelled_in_two_cases_is_still_one_unit(self) -> None:
        """The real NHAI bill spells cubic metres ``Cum`` on nine rows and ``cum`` on a tenth.

        Refusing on case alone would decline to reconcile a payment over a typist's shift key, and
        the refusal is silent — it produces an INCONCLUSIVE where a discrepancy should have been
        found. Case-folding only: ``Cum`` against ``m3`` is still refused, because one document is
        no basis for asserting two spellings mean the same thing.
        """
        folded = compute_quantity_variance(
            {
                "cumulative_claim_quantity": quantity(
                    "cumulative_claim_quantity", Decimal("520"), "Cum"
                ),
                "measured_quantity": quantity("measured_quantity", Decimal("470"), "cum"),
            }
        )
        assert folded is not None
        assert folded.value == Decimal("50")
        # Stored as one document actually wrote it. Comparison may normalise; evidence may not.
        assert folded.unit == "Cum"

        assert (
            compute_quantity_variance(
                {
                    "cumulative_claim_quantity": quantity(
                        "cumulative_claim_quantity", Decimal("520"), "Cum"
                    ),
                    "measured_quantity": quantity("measured_quantity", Decimal("470"), "m3"),
                }
            )
            is None
        )

    def test_exposure_is_floored_at_zero_and_priced_at_the_contract_rate(self) -> None:
        """Under-claiming creates no money owed back, so a negative variance is not exposure."""
        facts = {"contract_rate": money("contract_rate", Decimal("8000"))}

        over = compute_unsupported_amount(facts, variance=Decimal("50"))
        assert over is not None and over.value == Decimal("400000")

        under = compute_unsupported_amount(facts, variance=Decimal("-30"))
        assert under is not None and under.value == Decimal("0")

    def test_a_rate_variance_keeps_its_sign(self) -> None:
        result = compute_rate_variance(
            {
                "claimed_rate": money("claimed_rate", Decimal("74500")),
                "contract_rate": money("contract_rate", Decimal("72000")),
            }
        )
        assert result is not None
        assert result.value == Decimal("2500")
        assert result.currency == "INR"


class TestItemLinkage:
    def test_one_item_written_three_ways_normalises_to_one_key(self) -> None:
        """4.7.2, 4-7-2 and 04.07.02 are one item, and all three spellings occur in real records."""
        assert normalise_item("4.7.2") == normalise_item("4-7-2") == normalise_item("04.07.02")

    def test_a_longer_segment_stays_distinct(self) -> None:
        """Stripping zeros per segment must not merge 4.7.2 with 4.7.20."""
        assert normalise_item("4.7.2") != normalise_item("4.7.20")


class TestRules:
    def test_a_claim_exceeding_measured_work_is_flagged_for_review(self) -> None:
        """The disagreement the dataset plants, and the reason the rule set exists."""
        result = evaluate_claim_within_measured(
            bundle(
                {
                    "cumulative_claim_quantity": quantity(
                        "cumulative_claim_quantity", Decimal("520")
                    ),
                    "measured_quantity": quantity("measured_quantity", Decimal("470")),
                },
                {
                    "quantity_variance": derived("quantity_variance", Decimal("50")),
                    "unsupported_amount": derived("unsupported_amount", Decimal("400000"), None),
                },
            )
        )

        # REVIEW, not FAIL: the discrepancy is established, its cause is not.
        assert result.outcome is Outcome.REVIEW
        assert "400000" in result.summary
        assert "50 m3" in result.summary
        assert result.derived_evidence.keys() == {"quantity_variance", "unsupported_amount"}

    def test_a_claim_within_measured_work_passes(self) -> None:
        result = evaluate_claim_within_measured(
            bundle(
                {
                    "cumulative_claim_quantity": quantity(
                        "cumulative_claim_quantity", Decimal("1150")
                    ),
                    "measured_quantity": quantity("measured_quantity", Decimal("1150")),
                },
                {"quantity_variance": derived("quantity_variance", Decimal("0"))},
            )
        )
        assert result.outcome is Outcome.PASS

    def test_a_rate_above_the_contract_is_flagged_for_review(self) -> None:
        result = evaluate_rate_matches_contract(
            bundle(
                {
                    "claimed_rate": money("claimed_rate", Decimal("74500")),
                    "contract_rate": money("contract_rate", Decimal("72000")),
                },
                {"rate_variance": derived("rate_variance", Decimal("2500"), None)},
            )
        )
        assert result.outcome is Outcome.REVIEW
        assert "above" in result.summary

    def test_a_cumulative_claim_below_what_was_certified_is_flagged(self) -> None:
        """A cumulative figure cannot decrease; if it has, the bill contradicts itself."""
        result = evaluate_cumulative_not_regressed(
            bundle(
                {
                    "cumulative_claim_quantity": quantity(
                        "cumulative_claim_quantity", Decimal("380")
                    ),
                    "previous_certified_quantity": quantity(
                        "previous_certified_quantity", Decimal("420")
                    ),
                }
            )
        )
        assert result.outcome is Outcome.REVIEW
        assert "cannot decrease" in result.summary

    def test_a_missing_input_is_inconclusive_never_a_pass(self) -> None:
        """No measurement means the claim is unchecked, which is not the same as accepted."""
        result = evaluate_claim_within_measured(
            bundle(
                {"cumulative_claim_quantity": quantity("cumulative_claim_quantity", Decimal("520"))}
            )
        )
        assert result.outcome is Outcome.INCONCLUSIVE
        assert "measured_quantity" in result.summary
