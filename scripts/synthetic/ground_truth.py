"""The answer key.

Written alongside the documents and **never read by the pipeline**. Extraction, classification,
calculation and verification do not import this module or open this file; the scorer does, after a
run has finished and its findings are already stored. That separation is rule 102's third
constraint and it is the only thing that makes a score mean anything.

Structured so a person can check it by hand. Every planted defect carries the arithmetic that makes
it a defect, in the same units the documents print, so a reviewer can open the bill, find the row,
and confirm the claim without running anything.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from scripts.synthetic.bundle import Bundle
from scripts.synthetic.catalogue import CATALOGUE
from scripts.synthetic.spec import (
    DEFECTS,
    PERIODS,
    PROJECT_NAME,
    PROJECT_REF,
    DefectClass,
)
from scripts.synthetic.workbooks import BANNER

__all__ = ["write_ground_truth"]


def _defect_payload() -> list[dict[str, Any]]:
    return [
        {
            "ref": defect.ref,
            "class": defect.defect_class.value,
            "item": defect.item,
            "ra_bill": None if defect.period is None else f"RA-{defect.period:02d}",
            "summary": defect.summary,
            "detectable_by_a_registered_rule": defect.detectable_by,
            "expected_outcome": defect.expected_outcome,
            "money_at_stake_inr": str(defect.money_at_stake),
            "why_this_was_planted": defect.rationale,
        }
        for defect in DEFECTS
    ]


def write_ground_truth(bundle: Bundle, path: Path) -> None:
    detectable = [defect for defect in DEFECTS if defect.detectable_by is not None]
    undetectable = [
        defect
        for defect in DEFECTS
        if defect.detectable_by is None and defect.defect_class is not DefectClass.CONTROL
    ]
    controls = [defect for defect in DEFECTS if defect.defect_class is DefectClass.CONTROL]

    payload: dict[str, Any] = {
        "warning": BANNER,
        "corpus_tier": 5,
        "synthetic": True,
        "project_reference": PROJECT_REF,
        "project_name": PROJECT_NAME,
        "generated_by": "python -m scripts.generate_synthetic_bundle",
        "governed_by": [
            "docs/adr/0019-synthetic-benchmark-corpus-and-conditional-unfreeze.md",
            "AEDIFEX-RULES.md rule 102",
            "SRS.md section 18a, tier 5",
        ],
        "what_this_file_is_not": (
            "Not evidence about real documents. A score against this file says a rule executes and "
            "is specific on generated input. It says nothing about whether the rule is right about "
            "documents a customer would upload, and quoting a detection rate from it as a product "
            "accuracy figure is forbidden by rule 102."
        ),
        "shape": {
            "trade_groups": len(CATALOGUE),
            "priced_items": len(bundle.boq_rev1),
            "boq_revisions": 2,
            "measurement_sheets": len(bundle.measurements),
            "ra_bills": len(bundle.bills),
            "variation_orders": len(bundle.variations),
            "contract_value_inr": str(bundle.contract_value),
            "planted_defects": len(DEFECTS),
            "clean_bill_rows": sum(len(rows) for rows in bundle.bills.values())
            - len({(d.item, d.period) for d in DEFECTS if d.period is not None}),
        },
        "scoring": {
            "detectable_today": [defect.ref for defect in detectable],
            "no_rule_exists_yet": [defect.ref for defect in undetectable],
            "controls_that_must_not_fire": [defect.ref for defect in controls],
            "how_to_read_a_miss": (
                "A miss in detectable_today is a defect report: a rule that was believed to work "
                "does not. A miss in no_rule_exists_yet is expected and is a specification for "
                "work, not a failure. A control that fires is the worst outcome available, because "
                "a rule that flags legitimately varied work would be switched off on day one of a "
                "real deployment."
            ),
            "false_positives_are_reported_with_equal_prominence": True,
        },
        "periods": [
            {
                "ra_bill": detail.label,
                "measured_on": detail.measured_on,
                "billed_on": detail.billed_on,
                "bill_rows": len(bundle.bills[detail.number]),
                "measurement_rows": len(bundle.measurements[detail.number]),
                "stated_total_inr": str(bundle.stated_bill_totals[detail.number]),
                "sum_of_printed_rows_inr": str(
                    sum(
                        (row.amount for row in bundle.bills[detail.number]),
                        start=Decimal("0.00"),
                    )
                    + sum(
                        (extra.amount for extra in bundle.extras.get(detail.number, ())),
                        start=Decimal("0.00"),
                    )
                ),
            }
            for detail in PERIODS
        ],
        "unparented_claims": [
            {
                "ref": extra.number,
                "ra_bill": f"RA-{period:02d}",
                "description": extra.description,
                "quantity": str(extra.quantity),
                "unit": extra.unit,
                "rate_inr": str(extra.rate),
                "amount_inr": str(extra.amount),
                "authorised_by": extra.authorised_by,
                "note": (
                    "Authorised. Any rule flagging unparented claims must NOT flag this one."
                    if extra.authorised_by
                    else "Not authorised by any variation order in the bundle."
                ),
            }
            for period, extras in sorted(bundle.extras.items())
            for extra in extras
        ],
        "defects": _defect_payload(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
