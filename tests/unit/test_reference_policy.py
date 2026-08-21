"""Reading a tiered policy out of a reference document, and judging a tender against it.

Money, thresholds and a band selection: every case here is one where being silently wrong would put
a wrong number in front of somebody certifying a payment.

The clause under test is real — NHAI Works Manual 2006, clause 4.14.1, page 79 — and so is the
tender it is applied to. The rate is written in *words* and conditional on a band, which is why the
project spent a milestone believing NHAI had no bid-security policy: the reader only understood
digits, so it reported the clause as absent, and two tenders sitting in different bands looked like
two different policies.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aedifex.calculation.engine import (
    DERIVED_REQUIRED_BID_SECURITY,
    compute_required_bid_security,
)
from aedifex.domain.evidence import FactKind
from aedifex.extraction.applicability import ApplicableProvision, _in_band
from aedifex.extraction.pdftext import DocumentText, PageText
from aedifex.extraction.policy import PROVISION_BID_SECURITY_SHARE, read_bid_security_policy
from aedifex.extraction.tender_notice import (
    FIELD_BID_SECURITY,
    FIELD_ESTIMATED_COST,
    Evidence,
    ExtractedField,
    TenderNotice,
)
from aedifex.infrastructure.database.models import DerivedFact, ExtractedFact, PolicyProvision
from aedifex.verification.reference_policy import (
    REFERENCE_BID_SECURITY_RULE_ID,
    evaluate_bid_security_against_policy,
)
from aedifex.verification.rules import NOT_SOURCED, Outcome, RuleResult

# Clause 4.14.1 as the flattened PDF presents it, verbatim from page 79.
_CLAUSE = (
    "4.14 Bid Security 4.14.1 Each bidder shall furnish bid security as a part of his bid at the "
    "following rates: (a) two percent of the estimated cost for works up to Rs. 20 crore (subject "
    "to a maximum of Rs. 30 lacs). (b) one and one-half percent of the estimated cost for works "
    "between Rs. 20 crore to Rs. 50 crore (subject to a maximum of Rs. 50 lacs). (c) one percent "
    "of the estimated cost for works above Rs. 50 crore. 4.14.2 The Bid security shall be in "
    "favour of National Highways Authority of India."
)


def _document(text: str) -> DocumentText:
    return DocumentText(pages=(PageText(number=79, text=text),), page_count=79, truncated=False)


def test_the_tiered_clause_is_read_in_words_with_bands_and_caps() -> None:
    """Three rates, three bands, two caps, and none of the rates written as a digit."""
    provisions = read_bid_security_policy(_document(_CLAUSE))

    assert [p.clause for p in provisions] == ["4.14.1(a)", "4.14.1(b)", "4.14.1(c)"]
    assert [p.share for p in provisions] == [
        Decimal("0.02"),
        Decimal("0.015"),  # "one and one-half percent"
        Decimal("0.01"),
    ]
    assert [(p.applies_from, p.applies_to_max) for p in provisions] == [
        (None, Decimal("200000000")),
        (Decimal("200000000"), Decimal("500000000")),
        (Decimal("500000000"), None),
    ]
    assert [p.cap_amount for p in provisions] == [
        Decimal("3000000"),
        Decimal("5000000"),
        None,
    ]
    # Read from the document, never asserted by whoever filed it: an authority decides which
    # projects a threshold can reach, so it may not be operator input.
    assert {p.authority for p in provisions} == {"nhai"}
    assert {p.jurisdiction for p in provisions} == {"IN"}


def test_a_document_that_names_no_authority_yields_nothing() -> None:
    """A threshold binding nobody in particular would end up binding everybody."""
    anonymous = _CLAUSE.replace("National Highways Authority of India", "the Employer")
    assert read_bid_security_policy(_document(anonymous)) == ()


def _provision(
    share: str,
    *,
    low: str | None = None,
    high: str | None = None,
    cap: str | None = None,
    clause: str = "4.14.1(a)",
) -> PolicyProvision:
    return PolicyProvision(
        provision_type=PROVISION_BID_SECURITY_SHARE,
        clause=clause,
        authority="nhai",
        jurisdiction="IN",
        page=79,
        span_start=0,
        span_end=1,
        snippet=clause,
        applies_to=FIELD_ESTIMATED_COST,
        applies_from=Decimal(low) if low else None,
        applies_to_max=Decimal(high) if high else None,
        share=Decimal(share),
        cap_amount=Decimal(cap) if cap else None,
        currency="INR",
        extractor="test",
        extractor_version="1",
    )


def _cost_fact(amount: str) -> ExtractedFact:
    return ExtractedFact(
        fact_type=FIELD_ESTIMATED_COST,
        literal=amount,
        numeric_value=Decimal(amount),
        currency="INR",
        page=6,
        span_start=0,
        span_end=1,
        snippet=amount,
        method="test",
        kind=FactKind.MONEY,
        extractor="test",
        extractor_version="1",
    )


def test_the_real_tender_reconciles_against_the_real_clause() -> None:
    """The verification this whole milestone was for.

    Estimated cost Rs 8,46,49,969 falls in band (a), so 2% is required: Rs 16,92,999.38. The tender
    states Rs 16.93 Lacs — Rs 16,93,000 — which is the same figure rounded up to the whole rupee.
    """
    provision = _provision("0.02", high="200000000", cap="3000000")
    calculated = compute_required_bid_security(_cost_fact("84649969"), provision)

    assert calculated is not None
    assert calculated.fact_type == DERIVED_REQUIRED_BID_SECURITY
    assert calculated.value == Decimal("1692999.38")
    assert calculated.expression == "84649969 x 0.02"
    # Half the origin of this number is somebody else's clause, and it is cited as such.
    assert calculated.provisions == {PROVISION_BID_SECURITY_SHARE: provision}
    assert set(calculated.inputs) == {FIELD_ESTIMATED_COST}

    result = _evaluate("84649969", "1693000", provision, calculated.value)
    assert result.rule_id == REFERENCE_BID_SECURITY_RULE_ID
    assert result.outcome is Outcome.PASS
    assert result.detail["required_bid_security"] == "1692999.38"
    assert result.detail["difference"] == "0.62"


def test_the_cap_applies_after_the_share_not_before() -> None:
    """ "Two percent ... subject to a maximum of Rs 30 lacs" is a ceiling, never a floor.

    Order matters and the clause states it. Capping first would turn the maximum into the amount
    required of every large contract.
    """
    provision = _provision("0.02", high="200000000", cap="3000000")
    # 2% of Rs 19 crore is Rs 38 lacs, above the Rs 30 lac cap.
    capped = compute_required_bid_security(_cost_fact("190000000"), provision)
    assert capped is not None
    assert capped.value == Decimal("3000000")
    assert capped.expression == "min(190000000 x 0.02, 3000000)"

    # A small contract is not lifted up to the cap.
    small = compute_required_bid_security(_cost_fact("10000000"), provision)
    assert small is not None and small.value == Decimal("200000")


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        ("100000000", True),  # inside band (a)
        ("200000000", True),  # exactly the boundary, as written
        ("200000001", False),
    ],
)
def test_band_membership_is_inclusive_as_written(cost: str, expected: bool) -> None:
    """Bounds are taken literally rather than nudged to make the bands disjoint."""
    assert _in_band(Decimal(cost), _provision("0.02", high="200000000")) is expected


def _evaluate(
    cost: str, security: str | None, provision: PolicyProvision | None, required: Decimal | None
) -> RuleResult:
    fields = [
        ExtractedField(
            name=FIELD_ESTIMATED_COST,
            kind=FactKind.MONEY,
            literal=cost,
            value=Decimal(cost),
            currency="INR",
            evidence=Evidence(page=6, start=0, end=1, snippet=cost),
            method="test",
        )
    ]
    if security is not None:
        fields.append(
            ExtractedField(
                name=FIELD_BID_SECURITY,
                kind=FactKind.MONEY,
                literal="Rs. 16.93 Lacs",
                value=Decimal(security),
                currency="INR",
                evidence=Evidence(page=6, start=0, end=1, snippet=security),
                method="test",
            )
        )
    applicable = ApplicableProvision(
        provision=provision,
        considered=(provision,) if provision else (),
        reason="test",
    )
    derived = (
        DerivedFact(fact_type=DERIVED_REQUIRED_BID_SECURITY, numeric_value=required)
        if required is not None
        else None
    )
    return evaluate_bid_security_against_policy(
        TenderNotice(fields=tuple(fields), unsupported=()),
        applicable=applicable,
        required=derived,
    )


def test_a_shortfall_beyond_tolerance_fails_and_names_the_clause() -> None:
    """A verdict is only allowed because the threshold was sourced, and it says where from."""
    provision = _provision("0.02", high="200000000", cap="3000000")
    result = _evaluate("84649969", "1000000", provision, Decimal("1692999.38"))
    assert result.outcome is Outcome.FAIL
    assert "4.14.1(a)" in result.summary
    assert result.detail["difference"] == "-692999.38"


def test_ambiguous_applicability_is_reported_rather_than_resolved() -> None:
    """A cost inside two bands at once is the document's silence, not a tie to break.

    Picking the lower rate favours the bidder and the higher favours the authority; picking either
    would be Aedifex legislating.
    """
    both = (
        _provision("0.02", high="200000000", clause="4.14.1(a)"),
        _provision("0.015", low="200000000", high="500000000", clause="4.14.1(b)"),
    )
    unresolved = ApplicableProvision(
        provision=None, considered=both, reason="200000000 falls inside 2 bands at once"
    )
    assert unresolved.ambiguous

    result = evaluate_bid_security_against_policy(
        TenderNotice(
            fields=(
                ExtractedField(
                    name=FIELD_ESTIMATED_COST,
                    kind=FactKind.MONEY,
                    literal="200000000",
                    value=Decimal("200000000"),
                    currency="INR",
                    evidence=Evidence(page=6, start=0, end=1, snippet="x"),
                    method="test",
                ),
            ),
            unsupported=(),
        ),
        applicable=unresolved,
    )
    assert result.outcome is Outcome.INCONCLUSIVE
    assert result.expected == NOT_SOURCED
    assert result.detail["provisions_considered"] == "2"
    # Both candidates are cited, so a reviewer can see the collision rather than being told of it.
    assert len(result.provision_evidence) == 2
