"""Generate the Tier 5 synthetic benchmark bundle.

Run: ``python -m scripts.generate_synthetic_bundle``

Writes a complete fictional building project — two BOQ revisions, four measurement sheets, four
running account bills and a variation order — as both spreadsheets and printed PDFs, plus the
ground-truth answer key describing the twelve defects planted in it.

**Everything it produces is fictional and is quarantined by rule 102.** No real project,
contractor, employer or price appears anywhere in it. Read
``docs/adr/0019-synthetic-benchmark-corpus-and-conditional-unfreeze.md`` before using the output for
anything, and in particular before quoting a number from it to anyone outside this repository.

``--no-pdf`` skips rendering when no TeX distribution is available. The spreadsheets alone exercise
reconciliation and verification; the PDFs are what exercise the reader.
"""

from __future__ import annotations

import argparse
import hashlib
import tempfile
from pathlib import Path

from scripts.synthetic.bundle import build
from scripts.synthetic.ground_truth import write_ground_truth
from scripts.synthetic.render import latex_available, write_pdfs
from scripts.synthetic.spec import PROJECT_REF
from scripts.synthetic.workbooks import write_workbooks

OUTPUT_DIR = Path("data/synthetic") / PROJECT_REF


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="skip PDF rendering (no TeX distribution required)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DIR,
        help=f"where to write the bundle (default: {OUTPUT_DIR})",
    )
    arguments = parser.parse_args()

    bundle = build()
    written = write_workbooks(bundle, arguments.output)

    if arguments.no_pdf:
        print("skipping PDF rendering (--no-pdf)")
    elif not latex_available():
        print("skipping PDF rendering: no pdflatex on PATH")
    else:
        with tempfile.TemporaryDirectory() as work:
            written.extend(write_pdfs(bundle, arguments.output, Path(work)))

    ground_truth = arguments.output / "GROUND_TRUTH.json"
    write_ground_truth(bundle, ground_truth)
    written.append(ground_truth)

    for path in sorted(written):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        print(f"{path.stat().st_size:>9}  {digest}  {path.name}")
    print(f"\n{len(written)} files in {arguments.output}")
    print(f"contract value Rs {bundle.contract_value:,.2f}, 12 planted defects, all verified")


if __name__ == "__main__":
    main()
