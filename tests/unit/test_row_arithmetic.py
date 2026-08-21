"""Precision-aware row arithmetic, pinned to the real rows that forced it.

Money, so the cases are the observed ones rather than invented ones. Every row below was read off a
real bill in the corpus, and the three IIT Bombay rows are the exact rows that made the previous
exact-equality rule reject an entire 661-row bill.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aedifex.calculation.row_arithmetic import (
    ArithmeticConsistency,
    classify_row_arithmetic,
)


class TestRealRows:
    """The rows from IIT Bombay Hostel 19 and the NHAI bill, with their expected classification."""

    @pytest.mark.parametrize(
        ("quantity", "rate", "amount", "expected"),
        [
            # 115 x 8,556.65 = 984,014.75 against a stated 984,014.26: out by Rs.0.49, and a rate
            # printed to two places over 115 units can hide up to Rs.0.575.
            ("115", "8556.65", "984014.26", ArithmeticConsistency.CONSISTENT_WITH_DISPLAY_ROUNDING),
            # The one that matters most: out by Rs.4.50, which no sane fixed tolerance would admit,
            # and which 1125 x 0.005 = Rs.5.625 explains exactly.
            (
                "1125",
                "5528.09",
                "6219105.75",
                ArithmeticConsistency.CONSISTENT_WITH_DISPLAY_ROUNDING,
            ),
            # Closes with no remainder.
            ("215", "654.00", "140610.00", ArithmeticConsistency.EXACT),
            # A recovery, stated in accounting parentheses on the NHAI bill. Negative rate, and the
            # envelope has to be ordered by value rather than by which factor is larger.
            ("661.50", "-1785.60", "-1181174.40", ArithmeticConsistency.EXACT),
            # Real discrepancies, verified against the page: the bills genuinely state these.
            # 67 x 3,260.60 = 218,460.20, not 216,960.10 — out by Rs.1,500.10.
            ("67", "3260.60", "216960.10", ArithmeticConsistency.REVIEW),
            # 86 x 631.00 = 54,266.00, not 54,518.40.
            ("86", "631.00", "54518.40", ArithmeticConsistency.REVIEW),
        ],
    )
    def test_classification(
        self, quantity: str, rate: str, amount: str, expected: ArithmeticConsistency
    ) -> None:
        result = classify_row_arithmetic(Decimal(quantity), Decimal(rate), Decimal(amount))
        assert result.consistency is expected

    def test_the_envelope_is_derived_from_the_quantity(self) -> None:
        """Two rows, same rate precision, different quantities — so different envelopes.

        This is the property a global tolerance cannot have. The Rs.4.50 discrepancy that is
        acceptable over 1,125 units would not be acceptable over one.
        """
        many = classify_row_arithmetic(Decimal("1125"), Decimal("5528.09"), Decimal("6219105.75"))
        one = classify_row_arithmetic(Decimal("1"), Decimal("5528.09"), Decimal("5532.59"))

        width = many.maximum_possible_amount - many.minimum_possible_amount
        assert width == Decimal("11.250")
        assert one.maximum_possible_amount - one.minimum_possible_amount == Decimal("0.010")
        assert many.consistency is ArithmeticConsistency.CONSISTENT_WITH_DISPLAY_ROUNDING
        assert one.consistency is ArithmeticConsistency.REVIEW

    def test_a_rate_printed_to_more_places_narrows_the_envelope(self) -> None:
        """Precision is evidence: ``8,556.6500`` claims more than ``8,556.65`` and is held to it."""
        coarse = classify_row_arithmetic(Decimal("115"), Decimal("8556.65"), Decimal("984014.26"))
        fine = classify_row_arithmetic(Decimal("115"), Decimal("8556.6500"), Decimal("984014.26"))

        assert coarse.rate_decimals == 2
        assert fine.rate_decimals == 4
        assert coarse.consistency is ArithmeticConsistency.CONSISTENT_WITH_DISPLAY_ROUNDING
        assert fine.consistency is ArithmeticConsistency.REVIEW


class TestDerivedRate:
    def test_implied_rate_is_offered_and_never_substituted(self) -> None:
        result = classify_row_arithmetic(Decimal("67"), Decimal("3260.60"), Decimal("216960.10"))

        assert result.implied_rate == Decimal("3238.2104477612")
        assert result.rate_difference == Decimal("3238.2104477612") - Decimal("3260.60")
        # The stated rate is untouched. Overwriting it with the implied one would falsify the page.
        assert result.exact_product == Decimal("67") * Decimal("3260.60")

    def test_zero_quantity_implies_no_rate(self) -> None:
        """A quantity of zero cannot imply a rate, and dividing by it must not raise."""
        result = classify_row_arithmetic(Decimal("0"), Decimal("100.00"), Decimal("500.00"))

        assert result.implied_rate is None
        assert result.rate_difference is None
        assert result.consistency is ArithmeticConsistency.REVIEW
