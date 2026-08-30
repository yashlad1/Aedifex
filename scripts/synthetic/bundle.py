"""Computing the bundle's documents from the catalogue and the planted defects.

Everything here is a pure function of :mod:`scripts.synthetic.catalogue` and
:mod:`scripts.synthetic.spec`. Given the same inputs it produces the same numbers, and there is no
clock, no randomness and no filesystem in this module — which is what makes the bundle a *function
of its specification* rather than a pile of files somebody adjusted until a run looked good.

The progress model is deliberately dull. A clean item's claim equals its measurement exactly, so a
clean row must produce ``PASS``; anything else is a false positive and the benchmark's real subject.
Only the twelve rows named in the defect specification depart from that, and each departure is
applied in one place, :func:`_apply_defects`, so the whole delta between "correct bundle" and
"bundle under test" can be read in one screen.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from scripts.synthetic.catalogue import BoqItem, contract_value, item_by_number, items
from scripts.synthetic.spec import DEFECTS, PERIODS, Defect

__all__ = [
    "BillRow",
    "Bundle",
    "ExtraClaim",
    "MeasurementRow",
    "VariationOrder",
    "build",
]

_QUANTITY = Decimal("0.001")
_MONEY = Decimal("0.01")


def _round_q(value: Decimal) -> Decimal:
    return value.quantize(_QUANTITY, rounding=ROUND_HALF_UP)


def _round_m(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class MeasurementRow:
    """One line of a measurement sheet: what site says has been done, cumulatively."""

    item: BoqItem
    measured_quantity: Decimal


@dataclass(frozen=True, slots=True)
class BillRow:
    """One line of a running account bill."""

    item: BoqItem
    previous_certified: Decimal
    current_claim: Decimal
    cumulative_claim: Decimal
    claimed_rate: Decimal

    @property
    def amount(self) -> Decimal:
        return _round_m(self.current_claim * self.claimed_rate)


@dataclass(frozen=True, slots=True)
class ExtraClaim:
    """A billed line with no parent in any BOQ revision.

    ``authorised_by`` is the whole point of the type. One of these is authorised by a variation
    order and one is not, and no rule exists yet that can tell them apart — which is the gap the
    pair was planted to specify.
    """

    number: str
    description: str
    unit: str
    quantity: Decimal
    rate: Decimal
    authorised_by: str | None

    @property
    def amount(self) -> Decimal:
        return _round_m(self.quantity * self.rate)


@dataclass(frozen=True, slots=True)
class VariationOrder:
    reference: str
    dated: str
    description: str
    unit: str
    quantity: Decimal
    rate: Decimal
    approved_by: str

    @property
    def amount(self) -> Decimal:
        return _round_m(self.quantity * self.rate)


@dataclass(frozen=True, slots=True)
class Bundle:
    """Every document the generator will write, as numbers."""

    boq_rev1: tuple[BoqItem, ...]
    boq_rev2: tuple[BoqItem, ...]
    measurements: dict[int, tuple[MeasurementRow, ...]]
    bills: dict[int, tuple[BillRow, ...]]
    extras: dict[int, tuple[ExtraClaim, ...]]
    variations: tuple[VariationOrder, ...]
    stated_bill_totals: dict[int, Decimal]
    """What each RA bill *prints* as its total, which SYN-D12 makes disagree with its own rows."""

    contract_value: Decimal


# ---------------------------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------------------------


def _jitter(number: str) -> Decimal:
    """A stable ±5% wobble per item, so intermediate periods do not all land on clean thirds.

    Derived from the item number rather than from a seeded generator, so it does not depend on
    iteration order and stays correct if the catalogue is reordered.
    """
    digest = hashlib.sha256(number.encode("ascii")).hexdigest()
    return (Decimal(int(digest[:8], 16) % 11) - 5) / Decimal(100)


def _fraction(item: BoqItem, period: int) -> Decimal:
    """How much of an item is complete at the end of a period, as a fraction of its quantity."""
    if period < item.first_period:
        return Decimal(0)
    if period >= item.last_period:
        return Decimal(1)
    span = item.last_period - item.first_period + 1
    base = Decimal(period - item.first_period + 1) / Decimal(span)
    return min(Decimal("0.98"), max(Decimal("0.02"), base + _jitter(item.number)))


def _measured(item: BoqItem, period: int) -> Decimal:
    return _round_q(item.quantity * _fraction(item, period))


# ---------------------------------------------------------------------------------------------
# The planted departures from a correct bundle
# ---------------------------------------------------------------------------------------------

# item -> period -> (measured override, cumulative-claim override, claimed-rate override)
_OVERRIDES: Final[dict[tuple[str, int], tuple[Decimal | None, Decimal | None, Decimal | None]]] = {
    # SYN-D01 -- 462.000 claimed against 430.000 measured.
    ("2.3.2", 3): (Decimal("430.000"), Decimal("462.000"), None),
    # SYN-D02 -- 12.900 MT claimed at 78,500.00 against a contracted 76,000.00.
    ("3.1.2", 2): (Decimal("12.900"), Decimal("12.900"), Decimal("78500.00")),
    # SYN-D03 -- RA-03 certifies 3,240.000 and RA-04 states 3,180.000. Also carries SYN-D05, whose
    # 214.400 m2 of undeducted openings is inside the 3,240.000.
    ("6.2.1", 3): (Decimal("3240.000"), Decimal("3240.000"), None),
    ("6.2.1", 4): (Decimal("6480.000"), Decimal("3180.000"), None),
    # SYN-D10 -- a floor area that grew by 128.000 m2 after the slab was cast. The measurement was
    # inflated to match the claim, so only the contracted comparison can see it.
    ("7.1.3", 4): (Decimal("2088.000"), Decimal("2088.000"), None),
    # SYN-D11 -- billed at 100%, measured at 62%.
    ("9.1.1", 3): (Decimal("731.600"), Decimal("1180.000"), None),
}

# SYN-D08 and SYN-D09: two unparented claims, one authorised and one not.
_EXTRAS: Final[dict[int, tuple[ExtraClaim, ...]]] = {
    2: (
        ExtraClaim(
            number="V-001",
            description="Extra depth of excavation in hard rock below founding level",
            unit="m3",
            quantity=Decimal("88.000"),
            rate=Decimal("640.00"),
            authorised_by="VO-01",
        ),
    ),
    3: (
        ExtraClaim(
            number="V-002",
            description="Providing and fixing MS handrail to terrace parapet, 40mm dia pipe",
            unit="Rmt",
            quantity=Decimal("96.000"),
            rate=Decimal("1450.00"),
            authorised_by=None,
        ),
    ),
}

_VARIATIONS: Final[tuple[VariationOrder, ...]] = (
    VariationOrder(
        reference="VO-01",
        dated="2025-06-12",
        description="Extra depth of excavation in hard rock below founding level",
        unit="m3",
        quantity=Decimal("88.000"),
        rate=Decimal("640.00"),
        approved_by="Placeholder Project Management Consultants (FICTIONAL)",
    ),
)

# SYN-D04: the quantity BOQ Rev-02 states for 5.1.1, against Rev-01's 1,850.000.
_REVISED_QUANTITIES: Final[dict[str, Decimal]] = {"5.1.1": Decimal("1910.000")}

# SYN-D12: RA-04 prints a total 1,000.00 above the sum of its own rows.
_STATED_TOTAL_OFFSET: Final[dict[int, Decimal]] = {4: Decimal("1000.00")}


def _apply_defects(
    item: BoqItem, period: int, measured: Decimal, cumulative: Decimal, rate: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    override = _OVERRIDES.get((item.number, period))
    if override is None:
        return measured, cumulative, rate
    measured_override, cumulative_override, rate_override = override
    return (
        measured if measured_override is None else measured_override,
        cumulative if cumulative_override is None else cumulative_override,
        rate if rate_override is None else rate_override,
    )


# ---------------------------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------------------------


def build() -> Bundle:
    """The whole bundle as numbers, with every planted defect applied and checked."""
    catalogue = items()

    boq_rev2 = tuple(
        (
            replace(item, quantity=_REVISED_QUANTITIES[item.number])
            if item.number in _REVISED_QUANTITIES
            else item
        )
        for item in catalogue
    )

    measurements: dict[int, tuple[MeasurementRow, ...]] = {}
    bills: dict[int, tuple[BillRow, ...]] = {}
    stated_totals: dict[int, Decimal] = {}

    # Cumulative claim carried forward, so RA-04's "previous certified" is genuinely RA-03's
    # cumulative rather than a recomputation that could silently disagree with it.
    carried: dict[str, Decimal] = {item.number: Decimal(0) for item in catalogue}

    for period in PERIODS:
        measured_rows: list[MeasurementRow] = []
        bill_rows: list[BillRow] = []

        for item in catalogue:
            measured = _measured(item, period.number)
            cumulative = measured
            rate = item.rate
            measured, cumulative, rate = _apply_defects(
                item, period.number, measured, cumulative, rate
            )

            if measured > 0:
                measured_rows.append(MeasurementRow(item=item, measured_quantity=measured))

            previous = carried[item.number]
            if cumulative == 0 and previous == 0:
                continue
            bill_rows.append(
                BillRow(
                    item=item,
                    previous_certified=previous,
                    current_claim=_round_q(cumulative - previous),
                    cumulative_claim=cumulative,
                    claimed_rate=rate,
                )
            )
            carried[item.number] = cumulative

        measurements[period.number] = tuple(measured_rows)
        bills[period.number] = tuple(bill_rows)

        rows_total = sum((row.amount for row in bill_rows), start=Decimal("0.00"))
        extras_total = sum(
            (extra.amount for extra in _EXTRAS.get(period.number, ())), start=Decimal("0.00")
        )
        stated_totals[period.number] = _round_m(
            rows_total + extras_total + _STATED_TOTAL_OFFSET.get(period.number, Decimal("0.00"))
        )

    bundle = Bundle(
        boq_rev1=catalogue,
        boq_rev2=boq_rev2,
        measurements=measurements,
        bills=bills,
        extras=_EXTRAS,
        variations=_VARIATIONS,
        stated_bill_totals=stated_totals,
        contract_value=contract_value(),
    )
    _verify(bundle)
    return bundle


# ---------------------------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------------------------


def _row(bundle: Bundle, item: str, period: int) -> BillRow:
    for row in bundle.bills[period]:
        if row.item.number == item:
            return row
    raise AssertionError(f"no bill row for {item} in RA-{period:02d}")


def _measurement(bundle: Bundle, item: str, period: int) -> Decimal:
    for row in bundle.measurements[period]:
        if row.item.number == item:
            return row.measured_quantity
    raise AssertionError(f"no measurement row for {item} in period {period}")


def _computed_money(bundle: Bundle, defect: Defect) -> Decimal:
    """What the planted defect is actually worth in the generated numbers.

    Checked against the hand-computed figure in the specification. The two are derived
    independently on purpose: a specification that is merely a transcript of the generator's output
    cannot catch the generator drifting.
    """
    if defect.ref == "SYN-D01":
        row = _row(bundle, "2.3.2", 3)
        return _round_m((row.cumulative_claim - _measurement(bundle, "2.3.2", 3)) * row.item.rate)
    if defect.ref == "SYN-D02":
        row = _row(bundle, "3.1.2", 2)
        return _round_m((row.claimed_rate - row.item.rate) * row.current_claim)
    if defect.ref == "SYN-D03":
        return _round_m(
            (_row(bundle, "6.2.1", 3).cumulative_claim - _row(bundle, "6.2.1", 4).cumulative_claim)
            * item_by_number("6.2.1").rate
        )
    if defect.ref == "SYN-D05":
        return _round_m(Decimal("214.400") * item_by_number("6.2.1").rate)
    if defect.ref == "SYN-D06":
        return _round_m(Decimal("214.400") * item_by_number("8.1.2").rate)
    if defect.ref == "SYN-D07":
        return _round_m(Decimal("128.600") * item_by_number("4.2.1").rate)
    if defect.ref == "SYN-D08":
        return bundle.extras[3][0].amount
    if defect.ref == "SYN-D10":
        row = _row(bundle, "7.1.3", 4)
        return _round_m((row.cumulative_claim - row.item.quantity) * row.item.rate)
    if defect.ref == "SYN-D11":
        row = _row(bundle, "9.1.1", 3)
        return _round_m((row.cumulative_claim - _measurement(bundle, "9.1.1", 3)) * row.item.rate)
    if defect.ref == "SYN-D12":
        rows = sum((r.amount for r in bundle.bills[4]), start=Decimal("0.00"))
        extras = sum((e.amount for e in bundle.extras.get(4, ())), start=Decimal("0.00"))
        return _round_m(bundle.stated_bill_totals[4] - rows - extras)
    return Decimal("0.00")


def _verify(bundle: Bundle) -> None:
    """Every planted defect is present and worth what the specification says it is worth.

    A generator that quietly stops planting a defect would otherwise show up as an improvement in
    the score, which is the most dangerous possible failure of a benchmark.
    """
    for defect in DEFECTS:
        computed = _computed_money(bundle, defect)
        if computed != defect.money_at_stake:
            raise AssertionError(
                f"{defect.ref}: specification says Rs {defect.money_at_stake}, "
                f"generated bundle is worth Rs {computed}"
            )

    # SYN-D04 needs both revisions to disagree, and to disagree only about 5.1.1.
    differing = {
        one.number
        for one, two in zip(bundle.boq_rev1, bundle.boq_rev2, strict=True)
        if one.quantity != two.quantity
    }
    if differing != {"5.1.1"}:
        raise AssertionError(f"SYN-D04: revisions differ on {sorted(differing)}, expected 5.1.1")

    # SYN-D09's control must be authorised and SYN-D08's must not.
    if bundle.extras[2][0].authorised_by != "VO-01":
        raise AssertionError("SYN-D09: the control claim lost its variation order")
    if bundle.extras[3][0].authorised_by is not None:
        raise AssertionError("SYN-D08: the unparented claim acquired an authorisation")

    # Clean rows must be genuinely clean: claim equals measurement, rate equals contract rate.
    planted = {(defect.item, defect.period) for defect in DEFECTS}
    for period, rows in bundle.bills.items():
        for row in rows:
            if (row.item.number, period) in planted:
                continue
            if row.claimed_rate != row.item.rate:
                raise AssertionError(
                    f"clean row {row.item.number} RA-{period:02d} has a rate delta"
                )
