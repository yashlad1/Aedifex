"""Run the Tier 5 bundle through the product path and score it against the answer key.

Run against a **clean database**, because the first run is the experiment::

    dropdb --if-exists aedifex_synth && createdb aedifex_synth
    alembic upgrade head
    python -m scripts.generate_synthetic_bundle
    python -m scripts.run_synthetic_benchmark

Re-running over an existing project would score stale findings produced by whatever the rules were
the last time it ran, which is the benchmark equivalent of a preparatory fix.

Two halves that never meet until the end. The first drives the same functions the API and the
viewer drive — ``create_project``, ``attach_upload``, ``process_project``, ``reconcile_work_items``
— with no knowledge of what was planted. The second opens ``GROUND_TRUTH.json`` and compares.

**The scoring is deliberately unflattering.** Three numbers are reported with equal weight:

* **detections** — planted defects a rule surfaced
* **misses** — planted defects nothing surfaced, split by whether a rule for them exists at all
* **false positives** — findings on rows where nothing was planted

The third is the one that decides whether a reviewer would tolerate the product, and a benchmark
that omits it is marketing. A run that detects every planted defect and also flags forty clean rows
has failed, and this script says so.
"""

from __future__ import annotations

import argparse
import json
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.acquisition.registry.loader import get_registry
from aedifex.config import Settings
from aedifex.domain.documents import DocumentType
from aedifex.extraction.runner import reconcile_work_items
from aedifex.infrastructure.database.models import Finding, WorkItem
from aedifex.infrastructure.database.session import build_engine
from aedifex.infrastructure.storage.client import build_s3_client
from aedifex.infrastructure.storage.objects import RawObjectStore
from aedifex.workspace import attach_upload, create_project, process_project

BUNDLE = Path("data/synthetic/AEDX-SYNTH-002")

# The sentence every ambiguity finding contains. Findings carrying it share one root cause -- the
# evidence model has no notion of a document's position in a billing sequence -- and counting them
# individually would present one architectural gap as hundreds of unrelated defects.
_SYSTEMIC_CAUSE = "none supersedes the others"
SOURCE_ID = "synthetic_projects"
OPERATOR = "synthetic-benchmark"

# Declared rather than classified. The classifier's accuracy is not what this benchmark measures,
# and a misclassified document would silently disable the rules under test — which would look like
# a rule failure and is not one.
_TYPES: dict[str, DocumentType] = {
    "BOQ": DocumentType.BILL_OF_QUANTITIES,
    "Measurement": DocumentType.MEASUREMENT_BOOK,
    "RA-Bill": DocumentType.RUNNING_BILL,
    "Variation": DocumentType.CHANGE_ORDER,
}


def _declared_type(filename: str) -> DocumentType | None:
    for marker, document_type in _TYPES.items():
        if marker in filename:
            return document_type
    return None


@dataclass
class Score:
    detected: list[str]
    missed_with_rule: list[str]
    missed_without_rule: list[str]
    controls_fired: list[str]
    false_positives: list[tuple[str, str, str]]
    systemic_false_positives: int
    outcomes: Counter[str]
    work_items: int
    findings: int


def _load_ground_truth() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((BUNDLE / "GROUND_TRUTH.json").read_text())
    return payload


def _ingest(session: Session, store: RawObjectStore, settings: Settings) -> uuid.UUID:
    source = get_registry(settings).get(SOURCE_ID)
    project = create_project(
        session,
        source=source,
        name="SYNTHETIC — Nirmaan Residency Tower B",
        external_ref="AEDX-SYNTH-002",
        description="Tier 5 synthetic benchmark bundle. Fictional. See rule 102.",
        created_by=OPERATOR,
    )
    session.flush()

    for path in sorted(BUNDLE.glob("*.xlsx")):
        declared = _declared_type(path.name)
        if declared is None:
            print(f"  skipped (no declared type): {path.name}")
            continue
        outcome = attach_upload(
            session,
            store,
            project=project,
            source=source,
            content=path.read_bytes(),
            filename=path.name,
            uploaded_by=OPERATOR,
            declared_type=declared,
            note="Tier 5 synthetic benchmark. Not evidence about real documents.",
        )
        print(f"  {declared.value:20s} {path.name}  ({outcome.document.sha256[:12]})")
    return project.id


def _score(session: Session, project_id: uuid.UUID, truth: dict[str, Any]) -> Score:
    """Compare stored findings against the answer key.

    Credit is deliberately hard to earn. A defect counts as detected only when the rule the
    specification *names* produced a non-``PASS`` finding on that item. An earlier, looser version
    credited any non-pass finding on the right item, and it scored four detections the pipeline had
    not made — including two defects for which no rule exists at all. A benchmark that flatters the
    system it measures is worse than none.

    False positives are split by cause. When 242 findings all say "none supersedes the others",
    that is one architectural gap seen 242 times, not 242 independent defects, and reporting it as
    the latter would misdirect every hour spent on it.
    """
    work_items = list(
        session.execute(select(WorkItem).where(WorkItem.project_id == project_id)).scalars()
    )
    by_id = {item.id: item for item in work_items}

    findings = list(
        session.execute(select(Finding).where(Finding.project_id == project_id)).scalars()
    )
    outcomes: Counter[str] = Counter(
        str(finding.outcome).split(".")[-1].lower() for finding in findings
    )

    # (item identifier, rule id) -> outcome, for every finding that concluded something.
    raised: dict[tuple[str, str], str] = {}
    systemic = 0
    per_row: list[tuple[str, str, str]] = []
    planted_items = {defect["item"] for defect in truth["defects"]}

    for finding in findings:
        outcome = str(finding.outcome).split(".")[-1].lower()
        if outcome in {"pass", "inconclusive"}:
            continue
        item = by_id.get(finding.work_item_id) if finding.work_item_id else None
        if item is None:
            continue
        raised[(item.item_identifier, finding.rule_id)] = outcome
        if item.item_identifier in planted_items:
            continue
        if _SYSTEMIC_CAUSE in (finding.summary or ""):
            systemic += 1
        else:
            per_row.append((item.item_identifier, finding.rule_id, outcome))

    detected, missed_with_rule, missed_without_rule, controls_fired = [], [], [], []
    for defect in truth["defects"]:
        rule = defect["detectable_by_a_registered_rule"]
        hit = rule is not None and (defect["item"], rule) in raised
        if defect["class"] == "control":
            if any(key[0] == defect["item"] for key in raised):
                controls_fired.append(defect["ref"])
            continue
        if hit:
            detected.append(defect["ref"])
        elif rule is not None:
            missed_with_rule.append(defect["ref"])
        else:
            missed_without_rule.append(defect["ref"])

    return Score(
        detected=detected,
        missed_with_rule=missed_with_rule,
        missed_without_rule=missed_without_rule,
        controls_fired=controls_fired,
        false_positives=per_row,
        systemic_false_positives=systemic,
        outcomes=outcomes,
        work_items=len(work_items),
        findings=len(findings),
    )


def _report(score: Score, truth: dict[str, Any]) -> None:
    line = "=" * 78
    print(f"\n{line}\nSYNTHETIC BENCHMARK RESULT — Tier 5, {truth['project_reference']}\n{line}")
    print("THIS IS SYNTHETIC DATA. These numbers say a rule executes and is specific on")
    print("generated input. They say nothing about real documents (rule 102).\n")

    print(f"work items created      {score.work_items}")
    print(f"findings produced       {score.findings}")
    for outcome, count in sorted(score.outcomes.items()):
        print(f"    {outcome:16s} {count}")

    planted = len([d for d in truth["defects"] if d["class"] != "control"])
    controls = len(truth["scoring"]["controls_that_must_not_fire"])
    print(f"\nplanted defects         {planted} (plus {controls} control)")
    print(f"  detected              {len(score.detected)}  {score.detected}")
    print(f"  missed, rule exists   {len(score.missed_with_rule)}  {score.missed_with_rule}")
    print(f"  missed, no rule yet   {len(score.missed_without_rule)}  {score.missed_without_rule}")

    print("\nFALSE POSITIVES on clean rows")
    print(f"  systemic, one cause   {score.systemic_false_positives}" f'   ("{_SYSTEMIC_CAUSE}")')
    print(f"  independent           {len(score.false_positives)}")
    for identifier, rule, outcome in score.false_positives[:15]:
        print(f"    {identifier:10s} {rule:45s} {outcome}")
    if len(score.false_positives) > 15:
        print(f"    ... and {len(score.false_positives) - 15} more")

    print(f"\nCONTROLS THAT FIRED     {len(score.controls_fired)}  {score.controls_fired}")
    if score.controls_fired:
        print("    A control firing is the worst outcome available: a rule that flags")
        print("    legitimately varied work would be switched off on day one.")

    print(f"\n{line}")
    if score.systemic_false_positives:
        print("VERDICT: one architectural gap is flagging clean rows in bulk. Findings on real")
        print("         defects are buried among them, so the review queue is unusable as it")
        print("         stands. Fix the cause, not the rules.")
    elif score.missed_with_rule:
        print("VERDICT: a rule believed to work did not fire. Investigate before anything else.")
    elif score.controls_fired:
        print("VERDICT: a control fired. The rule is not specific enough to ship.")
    elif score.false_positives:
        print("VERDICT: clean rows were flagged. Specificity is the problem, not detection.")
    else:
        print("VERDICT: every registered rule that could fire did, with no false positives.")
    print(f"{line}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="do not drop the project afterwards")
    parser.parse_args()

    settings = Settings()
    engine = build_engine(settings)
    store = RawObjectStore(build_s3_client(settings), bucket=settings.storage_bucket)
    truth = _load_ground_truth()

    with Session(engine) as session:
        print("ingesting the synthetic bundle:")
        project_id = _ingest(session, store, settings)
        session.commit()

        print("\nprocessing:")
        report = process_project(session, store, project_id)
        print(f"  {report.describe()}")
        session.commit()

        # Called explicitly because process_project does not call it. That is SCRUM-13, and it is
        # the reason no project created through the product path has ever had a work item.
        print("\nreconciling work items:")
        analyses = reconcile_work_items(session, project_id)
        print(f"  {len(analyses)} work items analysed")
        session.commit()

        score = _score(session, project_id, truth)
        _report(score, truth)


if __name__ == "__main__":
    main()
