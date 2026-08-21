"""Whether a bill row's three stated values agree, given the precision they are printed at.

``quantity x rate == amount`` is not an invariant of commercial bills of quantities, and treating it
as one is why five real building bills yielded nothing. The rate a bill *prints* is rounded to a
fixed number of decimal places; the amount it prints was computed from the unrounded rate. So the
product of the two printed figures legitimately differs from the printed amount, by an amount that
depends on the quantity.

Measured on IIT Bombay's Hostel 19 bill, which is where this came from::

    115 x 8,556.65    = 984,014.75      stated 984,014.26        out by Rs.0.49
    1125 x 5,528.09   = 6,219,101.25    stated 6,219,105.75      out by Rs.4.50
    215 x 654.00      = 140,610.00      stated 140,610.00        exact

The middle row is out by four and a half rupees and is *not* an error. A rate printed to two places
hides up to half a paisa either way, and 1125 of them hide up to ``1125 x 0.005 = Rs.5.625`` — more
than the discrepancy. The first row's Rs.0.49 sits inside ``115 x 0.005 = Rs.0.575``. The third
closes exactly.

**So the permissible difference is derived, never chosen.** It comes from the quantity, the rate's
displayed precision and the amount's displayed precision, because those three things are what the
document actually states. A global rupee tolerance or a relative epsilon would be a number nobody
can defend, and the module this replaced had both: ``_RELATIVE_TOLERANCE = 0.0005`` with a
``_ABSOLUTE_TOLERANCE = 100`` floor, which let a row be out by Rs.100 on a small line and by
thousands on a large one, for no reason connected to the evidence.

**A row outside the envelope is classified, not discarded.** A bill whose arithmetic genuinely does
not close is evidence Aedifex exists to report — it is how over-certification and transcription
errors look — and a parser that drops it has destroyed the finding. The three outcomes are
``EXACT``, ``CONSISTENT_WITH_DISPLAY_ROUNDING`` and ``REVIEW``; all three keep the row.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

__all__ = [
    "ArithmeticConsistency",
    "RowArithmetic",
    "classify_row_arithmetic",
]

# Derived facts are stored as NUMERIC(28,10), so an implied rate is quantised to ten places rather
# than left at whatever precision division happened to produce.
_IMPLIED_RATE_EXPONENT: Final[Decimal] = Decimal("1e-10")


class ArithmeticConsistency(StrEnum):
    """How a row's stated amount relates to the product of its stated quantity and rate."""

    EXACT = "exact"
    """``quantity x rate`` reproduces the stated amount with no remainder."""

    CONSISTENT_WITH_DISPLAY_ROUNDING = "consistent_with_display_rounding"
    """The product differs, but by no more than the printed precision can hide.

    Not a weaker form of EXACT and not a tolerance: the bill is internally consistent, and the
    difference is fully explained by the rate having been rounded for display before printing.
    """

    REVIEW = "review"
    """The stated amount lies outside what display rounding can explain.

    Two quite different things look like this — a bill that really does not add up, and a row this
    reader has misread — and telling them apart needs a person. The row is kept either way.
    """


@dataclass(frozen=True, slots=True)
class RowArithmetic:
    """The classification, and every number needed to argue with it."""

    consistency: ArithmeticConsistency
    exact_product: Decimal
    """``quantity x rate`` at full precision, as stated."""

    stated_amount: Decimal
    difference: Decimal
    """``stated_amount - exact_product``. Signed: the direction matters to a reviewer."""

    minimum_possible_amount: Decimal
    maximum_possible_amount: Decimal
    """The envelope the underlying rate could have produced, given how the rate is printed."""

    rate_decimals: int
    amount_decimals: int
    rate_rounding_unit: Decimal
    implied_rate: Decimal | None
    """``stated_amount / quantity`` — what rate the amount implies. ``None`` when quantity is zero.

    A derived fact and never a substitute for the stated rate. Overwriting the printed rate with
    this would falsify what the document says; offering both lets a later rule compare them.
    """

    rate_difference: Decimal | None
    """``implied_rate - rate``. How far the printed rate is from the one the amount implies."""

    def explain(self) -> str:
        """One line a reviewer can read without opening the document."""
        if self.consistency is ArithmeticConsistency.EXACT:
            return f"{self.exact_product} exactly, as stated"
        window = f"[{self.minimum_possible_amount}, {self.maximum_possible_amount}]"
        if self.consistency is ArithmeticConsistency.CONSISTENT_WITH_DISPLAY_ROUNDING:
            return (
                f"stated {self.stated_amount} differs from {self.exact_product} by "
                f"{self.difference}, inside {window} — a rate shown to "
                f"{self.rate_decimals} place(s) can hide this"
            )
        return (
            f"stated {self.stated_amount} differs from {self.exact_product} by "
            f"{self.difference}, outside {window} — display rounding cannot explain it"
        )


def _displayed_decimals(value: Decimal) -> int:
    """How many decimal places a value was *printed* with.

    Read from the ``Decimal``'s own exponent, which is why parsing must not normalise: ``56.00``
    keeps exponent -2 and so records that the bill printed two places, while ``6500`` keeps 0. The
    distinction is evidence — a rate printed as ``56.00`` claims more precision than one printed as
    ``56`` — and normalising would throw it away.
    """
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):  # pragma: no cover - NaN/Infinity cannot reach here
        return 0
    return max(0, -exponent)


def classify_row_arithmetic(quantity: Decimal, rate: Decimal, amount: Decimal) -> RowArithmetic:
    """Classify one row's three stated values against each other.

    Args:
        quantity: As stated. Never rounded or rescaled here.
        rate: As stated, at the precision the document printed it.
        amount: As stated, at the precision the document printed it.

    Returns:
        The classification and the numbers behind it. Nothing is rejected.
    """
    exact_product = quantity * rate
    difference = amount - exact_product

    rate_decimals = _displayed_decimals(rate)
    amount_decimals = _displayed_decimals(amount)
    rate_unit = Decimal(1).scaleb(-rate_decimals)
    half_rate_unit = rate_unit / 2

    # min() and max() over both products rather than assuming the lower rate gives the lower amount:
    # a bill of quantities states recoveries and deductions as negatives -- the NHAI bill ends with
    # "Recovery of Milled Material" at a rate of (1,785.60) -- and with a negative multiplier the
    # inequality flips.
    low_product = quantity * (rate - half_rate_unit)
    high_product = quantity * (rate + half_rate_unit)
    minimum_possible = min(low_product, high_product)
    maximum_possible = max(low_product, high_product)

    implied_rate: Decimal | None = None
    rate_difference: Decimal | None = None
    if quantity != 0:
        implied_rate = (amount / quantity).quantize(_IMPLIED_RATE_EXPONENT)
        rate_difference = implied_rate - rate

    if exact_product == amount:
        consistency = ArithmeticConsistency.EXACT
    else:
        # The stated amount is itself printed to a fixed precision, so it stands for an interval
        # too. Containment is therefore an overlap test between two intervals, not a point-in-range
        # test: asking only whether the printed amount falls inside the product envelope would
        # wrongly review a row whose true amount does.
        half_amount_unit = Decimal(1).scaleb(-amount_decimals) / 2
        overlaps = (
            amount - half_amount_unit <= maximum_possible
            and amount + half_amount_unit >= minimum_possible
        )
        consistency = (
            ArithmeticConsistency.CONSISTENT_WITH_DISPLAY_ROUNDING
            if overlaps
            else ArithmeticConsistency.REVIEW
        )

    return RowArithmetic(
        consistency=consistency,
        exact_product=exact_product,
        stated_amount=amount,
        difference=difference,
        minimum_possible_amount=minimum_possible,
        maximum_possible_amount=maximum_possible,
        rate_decimals=rate_decimals,
        amount_decimals=amount_decimals,
        rate_rounding_unit=rate_unit,
        implied_rate=implied_rate,
        rate_difference=rate_difference,
    )
