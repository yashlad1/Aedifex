"""The calculation layer, and the registry's claim to describe it accurately.

Two things are worth testing here and little else. Deterministic monetary arithmetic, because a
silently wrong share reaches a finding and a finding reaches a person. And the knowledge registry's
own promise: its docstring says every registered type is one the code can actually produce, which is
a claim that rots the moment someone adds a fact type in one place and not the other.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from aedifex.calculation.engine import (
    CALCULATIONS,
    DERIVED_BID_SECURITY_SHARE,
    compute_bid_security_share,
    compute_for_document,
)
from aedifex.domain.evidence import FactKind, FactOrigin
from aedifex.infrastructure.database.models import ExtractedFact
from aedifex.knowledge.registry import FACT_TYPES, RULE_TYPES
from aedifex.verification import PROJECT_RULES, RULES
from aedifex.verification.reconciliation import RECONCILIATION_RULES


def a_fact(fact_type: str, value: Decimal | None, *, version: str = "1") -> ExtractedFact:
    return ExtractedFact(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        fact_type=fact_type,
        kind=FactKind.MONEY,
        literal=str(value),
        numeric_value=value,
        page=1,
        span_start=0,
        span_end=1,
        snippet="...",
        method="test",
        extractor="test",
        extractor_version=version,
    )


def test_the_share_is_the_exact_quotient_not_a_rounded_percentage() -> None:
    """2% of 84,649,969 is 1,692,999.38, so a stated 1,693,000 is *not* exactly 2%.

    The calculation must keep that difference. Rounding here would make a rule unable to compare
    against any tolerance finer than the rounding, and would quietly assert an equality that the
    documents do not support.
    """
    calculated = compute_bid_security_share(
        {
            "estimated_cost": a_fact("estimated_cost", Decimal("84649969")),
            "bid_security": a_fact("bid_security", Decimal("1693000")),
        }
    )

    assert calculated is not None
    assert calculated.value > Decimal("0.02")
    assert calculated.value.quantize(Decimal("1E-10")) == Decimal("0.0200000073")
    assert calculated.kind is FactKind.PERCENTAGE
    # The arithmetic is recorded, so the number can be redone by hand from the stored row alone.
    assert calculated.expression == "1693000 / 84649969"
    assert set(calculated.inputs) == {"estimated_cost", "bid_security"}


def test_a_missing_or_unusable_amount_yields_nothing_rather_than_zero() -> None:
    """A share of nothing is undefined. Zero would look like an answer."""
    cost = a_fact("estimated_cost", Decimal("84649969"))
    security = a_fact("bid_security", Decimal("1693000"))

    assert compute_bid_security_share({"estimated_cost": cost}) is None
    assert compute_bid_security_share({"bid_security": security}) is None
    assert compute_bid_security_share({}) is None
    assert (
        compute_bid_security_share(
            {"estimated_cost": a_fact("estimated_cost", Decimal(0)), "bid_security": security}
        )
        is None
    )
    assert (
        compute_bid_security_share(
            {"estimated_cost": a_fact("estimated_cost", None), "bid_security": security}
        )
        is None
    )


def test_the_newest_extractor_version_wins() -> None:
    """Mixing an old extraction with a new one would compare two of our runs, not two documents."""
    calculated = compute_for_document(
        [
            a_fact("estimated_cost", Decimal("100"), version="1"),
            a_fact("estimated_cost", Decimal("200"), version="2"),
            a_fact("bid_security", Decimal("4"), version="2"),
        ]
    )

    assert len(calculated) == 1
    assert calculated[0].value == Decimal("0.02")  # 4 / 200, not 4 / 100


def test_the_registry_describes_only_types_the_code_can_produce() -> None:
    """The registry's docstring promises this. Without a check it is just a comment."""
    derived = {info.fact_type for info in FACT_TYPES if info.origin is FactOrigin.DERIVED}
    assert DERIVED_BID_SECURITY_SHARE in derived
    assert derived == set(CALCULATIONS)

    registered_rules = {info.rule_id for info in RULE_TYPES}
    assert registered_rules == set(RULES) | set(PROJECT_RULES) | set(RECONCILIATION_RULES)

    # A derived fact's declared inputs must themselves be registered fact types.
    known = {info.fact_type for info in FACT_TYPES}
    for info in FACT_TYPES:
        assert set(info.inputs) <= known, f"{info.fact_type} declares unknown inputs"
