"""What the synthetic bundle contains, and what was deliberately made wrong in it.

This module is the *specification*, and the ordering matters: the defects are declared here, before
any document exists, and the generator is a pure function of them. The alternative — writing
documents and then describing what happened to be in them — produces a benchmark that can never
fail, because its ground truth is derived from its own output.

**Nothing in this module is ever read by the pipeline.** Extraction, classification, calculation and
verification do not import it. Scoring is a separate pass that compares stored findings against
:data:`DEFECTS` afterwards, which is the only point at which the two halves are allowed to meet.

The distinction that makes this honest is :attr:`Defect.detectable_by`. Some planted defects are
within reach of a rule that exists today; others are not, and are planted anyway. A defect with no
rule is not a failure of the benchmark — it is the benchmark doing its second job, which is to say
precisely what the product cannot yet see.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

__all__ = [
    "DEFECTS",
    "PERIODS",
    "PROJECT_NAME",
    "PROJECT_REF",
    "Defect",
    "DefectClass",
    "Period",
    "defects_for",
]

PROJECT_REF: Final[str] = "AEDX-SYNTH-002"
PROJECT_NAME: Final[str] = "Nirmaan Residency — Tower B (G+4 Residential)"

# Fictional parties. Chosen to be obviously generic rather than plausibly real, because a synthetic
# document that names a plausible firm is one screenshot away from being mistaken for a leak.
EMPLOYER: Final[str] = "Synthetic Housing Development Authority (FICTIONAL)"
CONTRACTOR: Final[str] = "Example Constructions Pvt Ltd (FICTIONAL)"
CONSULTANT: Final[str] = "Placeholder Project Management Consultants (FICTIONAL)"


@dataclass(frozen=True, slots=True)
class Period:
    """One billing period: a measurement sheet and the RA bill that claims against it."""

    number: int
    measured_on: str
    billed_on: str

    @property
    def label(self) -> str:
        return f"RA-{self.number:02d}"


PERIODS: Final[tuple[Period, ...]] = (
    Period(1, "2025-04-28", "2025-05-05"),
    Period(2, "2025-07-30", "2025-08-06"),
    Period(3, "2025-10-29", "2025-11-05"),
    Period(4, "2026-01-28", "2026-02-04"),
)


class DefectClass(StrEnum):
    """Why a defect was planted, which decides what its absence from the findings means.

    ``MECHANICAL`` defects exist to make a registered rule execute. If one is missed, a rule that
    was believed to work does not.

    ``AUDIT_PATTERN`` defects are overbilling behaviours named independently by the market research
    and by the CAG pattern study. Most have no rule yet. Missing one is expected, and is a
    specification for work rather than a defect report.
    """

    MECHANICAL = "mechanical"
    AUDIT_PATTERN = "audit_pattern"
    CONTROL = "control"
    """Not a defect at all. Planted to catch a rule that fires when it should not."""


@dataclass(frozen=True, slots=True)
class Defect:
    """One planted fact, and what a correct pipeline should conclude about it.

    ``detectable_by`` is deliberately allowed to be ``None``. A benchmark that only plants what the
    product can already find measures nothing except that the product has not regressed.
    """

    ref: str
    defect_class: DefectClass
    item: str
    """The BOQ item number this attaches to, or a synthesised identifier for orphan claims."""

    period: int | None
    """Which RA bill carries it. ``None`` when the defect is in the BOQ or measurement itself."""

    summary: str
    detectable_by: str | None
    """Registered rule id expected to surface it, or ``None`` if no such rule exists yet."""

    expected_outcome: str | None
    """``review``, ``fail`` or ``None`` when nothing is expected to fire."""

    money_at_stake: Decimal
    """Rupees the defect is worth.

    Computed by hand so a reviewer can check the pipeline's figure against something that was not
    derived from the pipeline.
    """

    rationale: str
    """Why this behaviour was chosen, with its external source where it has one."""


# ---------------------------------------------------------------------------------------------
# The planted defects.
#
# Twelve, against roughly 180 items and four bills. The proportion is deliberate: real bills are
# mostly correct, and a benchmark whose rows are mostly wrong measures recall while hiding the
# false-positive rate that decides whether anyone would tolerate the product.
# ---------------------------------------------------------------------------------------------

DEFECTS: Final[tuple[Defect, ...]] = (
    # --- Mechanical: these must make the four never-executed rules run -------------------------
    Defect(
        ref="SYN-D01",
        defect_class=DefectClass.MECHANICAL,
        item="2.3.2",
        period=3,
        summary=(
            "RA-03 claims a cumulative 462.000 m3 of M25 slab concrete against 430.000 m3 measured "
            "on the same date. 32.000 m3 is claimed with no measurement behind it."
        ),
        detectable_by="claim_within_measured_quantity",
        expected_outcome="review",
        money_at_stake=Decimal("249600.00"),
        rationale=(
            "The rule has never executed on any real document because no corpus tier has ever held "
            "a measurement sheet and a bill for the same item. This is the minimum case that "
            "proves it runs and cites both sides."
        ),
    ),
    Defect(
        ref="SYN-D02",
        defect_class=DefectClass.MECHANICAL,
        item="3.1.2",
        period=2,
        summary=(
            "RA-02 claims Fe500D column reinforcement at Rs 78,500.00/MT against a contracted "
            "Rs 76,000.00/MT. No variation authorises the higher rate. 12.900 MT is claimed in "
            "this bill, so the rate variance is worth Rs 32,250.00."
        ),
        detectable_by="claimed_rate_matches_contract_rate",
        expected_outcome="review",
        money_at_stake=Decimal("32250.00"),
        rationale=(
            "Steel is the item most exposed to rate escalation claims, and an escalation claim is "
            "exactly the thing a price-adjustment clause governs. The rule must establish the "
            "discrepancy without asserting it is improper, since it cannot see the clause."
        ),
    ),
    Defect(
        ref="SYN-D03",
        defect_class=DefectClass.MECHANICAL,
        item="6.2.1",
        period=4,
        summary=(
            "RA-04 states a cumulative 3,180.000 m2 of internal plaster where RA-03 already "
            "certified 3,240.000 m2. The cumulative figure has gone backwards by 60.000 m2."
        ),
        detectable_by="cumulative_claim_not_below_previous_certified",
        expected_outcome="review",
        money_at_stake=Decimal("19200.00"),
        rationale=(
            "A cumulative figure that regresses is either a correction of an earlier over-claim or "
            "a transcription error, and the two are indistinguishable from the bill alone. It is "
            "the clearest case where REVIEW is the honest outcome and FAIL would overstate."
        ),
    ),
    Defect(
        ref="SYN-D04",
        defect_class=DefectClass.MECHANICAL,
        item="5.1.1",
        period=None,
        summary=(
            "Two active BOQ revisions state different contracted quantities for 230mm brickwork "
            "— 1,850.000 m3 and 1,910.000 m3 — and neither supersedes the other."
        ),
        detectable_by="work_item_evidence_unambiguous",
        expected_outcome="review",
        money_at_stake=Decimal("0.00"),
        rationale=(
            "Real projects carry several BOQ revisions and the superseding relationship is often "
            "undeclared. The required behaviour is to name both documents and refuse to choose; "
            "picking one silently is the failure this plants a trap for."
        ),
    ),
    # --- Audit patterns: named by the market research, mostly with no rule yet ------------------
    Defect(
        ref="SYN-D05",
        defect_class=DefectClass.AUDIT_PATTERN,
        item="6.2.1",
        period=3,
        summary=(
            "Internal plaster is measured at gross wall area. The 46 door and window openings on "
            "floors 1-2, totalling 214.400 m2, are not deducted."
        ),
        detectable_by=None,
        expected_outcome=None,
        money_at_stake=Decimal("68608.00"),
        rationale=(
            "Named directly by Indian construction-audit practice in "
            "MARKET_AND_COMPETITOR_SIGNALS.md section 3: 'inflated plaster, painting and tiling "
            "areas, with opening deductions misapplied or omitted'. Undetectable today: it needs "
            "IS 1200 deduction rules from the Tier 3 reference corpus and a schedule of openings "
            "the bundle does not contain. This defect is the evidence ID for both."
        ),
    ),
    Defect(
        ref="SYN-D06",
        defect_class=DefectClass.AUDIT_PATTERN,
        item="8.1.2",
        period=4,
        summary=(
            "Interior emulsion is billed over the same gross area as the plaster beneath it, "
            "carrying the identical undeducted 214.400 m2 of openings a second time."
        ),
        detectable_by=None,
        expected_outcome=None,
        money_at_stake=Decimal("27872.00"),
        rationale=(
            "The same error compounding down a finishing stack is what makes it expensive rather "
            "than trivial. Detecting it needs an area-consistency relation between a surface and "
            "its finish, which is a relationship type the evidence graph does not have."
        ),
    ),
    Defect(
        ref="SYN-D07",
        defect_class=DefectClass.AUDIT_PATTERN,
        item="4.2.1",
        period=3,
        summary=(
            "Shuttering to beam soffits (4.2.1) and to slab soffits (4.2.2) both include the "
            "same 128.600 m2 of beam-slab junction. The area is billed twice."
        ),
        detectable_by=None,
        expected_outcome=None,
        money_at_stake=Decimal("49511.00"),
        rationale=(
            "'Shuttering and formwork double-counted between structural items', "
            "MARKET_AND_COMPETITOR_SIGNALS.md section 3. Undetectable today and interestingly so: "
            "nothing in either row is arithmetically wrong. It needs a method-of-measurement rule "
            "about what adjoining items may each contain, which is a Tier 3 knowledge question "
            "rather than an arithmetic one."
        ),
    ),
    Defect(
        ref="SYN-D08",
        defect_class=DefectClass.AUDIT_PATTERN,
        item="V-002",
        period=3,
        summary=(
            "RA-03 bills 'Providing and fixing MS handrail to terrace parapet', 96.000 Rmt at "
            "Rs 1,450.00. There is no such item in any BOQ revision and no approved variation."
        ),
        detectable_by=None,
        expected_outcome=None,
        money_at_stake=Decimal("139200.00"),
        rationale=(
            "The document four independent sources point at and that no corpus tier contains: a "
            "peer-reviewed survey (n=62) ranking variations in its top six payment-delay causes, "
            "PMC practice content, external signal S-01, and the 2026-08-24 repository review. "
            "reconciliation.py already names this as the reason it cannot produce a FAIL. "
            "Undetectable today because there is no rule that asks whether a billed line has a "
            "parent at all — the work-item linker records the fact and nothing consumes it."
        ),
    ),
    Defect(
        ref="SYN-D09",
        defect_class=DefectClass.CONTROL,
        item="V-001",
        period=2,
        summary=(
            "RA-02 bills 'Extra depth of excavation in hard rock', 88.000 m3 at Rs 640.00, which "
            "is also absent from every BOQ revision — but Variation Order VO-01, dated 2025-06-12 "
            "and signed by the consultant, authorises exactly this item, quantity and rate."
        ),
        detectable_by=None,
        expected_outcome=None,
        money_at_stake=Decimal("0.00"),
        rationale=(
            "The control for SYN-D08, and the more important half of the pair. Any future rule "
            "that flags unparented claims must distinguish these two, and a rule that flags both "
            "is worse than no rule: it would fire on every legitimately varied line on a real "
            "project and be switched off within a day. This is the row that will kill a naive "
            "implementation, which is why it is planted before the rule is written."
        ),
    ),
    Defect(
        ref="SYN-D10",
        defect_class=DefectClass.AUDIT_PATTERN,
        item="7.1.3",
        period=4,
        summary=(
            "Vitrified tile flooring is claimed at 2,088.000 m2 against a contracted 1,960.000 m2 "
            "— a 6.5% overrun with no variation, in a finishing item whose area is fixed by the "
            "slab beneath it."
        ),
        detectable_by=None,
        expected_outcome=None,
        money_at_stake=Decimal("158720.00"),
        rationale=(
            "Deliberately dual-purpose, and the benchmark corrected this entry's own author. It "
            "was specified as detectable by claim_within_measured_quantity; the first run proved "
            "otherwise. The measurement was inflated to match the claim, so claim-versus-measured "
            "passes, the rate matches, and the cumulative has not regressed — every registered "
            "rule returns PASS on a row claiming 2,088.000 m2 against a contracted 1,960.000 m2. "
            "**No registered rule compares a claim against the contracted quantity at all.** That "
            "is the gap, and a finishing quantity that grew after the slab was cast is among the "
            "most ordinary overbilling patterns there is."
        ),
    ),
    Defect(
        ref="SYN-D11",
        defect_class=DefectClass.AUDIT_PATTERN,
        item="9.1.1",
        period=3,
        summary=(
            "APP membrane waterproofing to the terrace is billed at 100% in RA-03 (1,180.000 m2) "
            "while the measurement sheet for the same period records 731.600 m2 complete. "
            "448.400 m2 is claimed with no measurement behind it."
        ),
        detectable_by="claim_within_measured_quantity",
        expected_outcome="review",
        money_at_stake=Decimal("334058.00"),
        rationale=(
            "Front-loading a specialist sub-trade near the end of a period is the most common "
            "form of over-claim a PMC actually argues about, and unlike SYN-D01 the shortfall is "
            "large enough that a reviewer would expect it to be obvious. It tests that the finding "
            "reaches a person rather than being buried among the clean rows."
        ),
    ),
    Defect(
        ref="SYN-D12",
        defect_class=DefectClass.MECHANICAL,
        item="2.3.2",
        period=4,
        summary=(
            "The RA-04 bill's stated total is Rs 1,000.00 higher than the sum of its own priced "
            "rows."
        ),
        detectable_by="bill_items_reconcile_to_stated_total",
        expected_outcome="review",
        money_at_stake=Decimal("1000.00"),
        rationale=(
            "The rule that was silently disabled on the real corpus and repaired on 2026-08-24 "
            "(REAL_CORPUS_RULE_VALIDATION.md, F1). It has no regression case that a person can "
            "verify by hand, and a deliberately small discrepancy is the one most likely to be "
            "lost to a rounding tolerance somebody adds later."
        ),
    ),
)


def defects_for(item: str, period: int | None = None) -> tuple[Defect, ...]:
    """Every planted defect attaching to one item, optionally narrowed to one billing period."""
    return tuple(
        defect
        for defect in DEFECTS
        if defect.item == item and (period is None or defect.period == period)
    )
