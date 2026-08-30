"""Rendering the bundle as printed documents.

This is the half of the benchmark that tests the *reader* rather than the rules. The spreadsheets
in :mod:`scripts.synthetic.workbooks` carry column headers that
``aedifex.extraction.spreadsheet`` already recognises, so they exercise reconciliation and
verification while telling us nothing about extraction. A printed bill offers no such help: the
layout is whatever the typesetter produced, and ``aedifex.extraction.pdf_boq`` has to find the rows
in flattened text.

**These are laid out as a bill is laid out, not as the parser prefers.** That distinction is the
point. Item number, description, unit, quantity, rate and amount across the page; Indian digit
grouping; a repeated header on every page; a stated total at the end. If the reader cannot find the
rows, that is a finding about the reader, and reporting it is more valuable than quietly reshaping
the document until the numbers come out.

LaTeX rather than a Python PDF library because pandoc and a TeX distribution are already required by
``scripts/build_pdf.sh``, and adding reportlab to a proprietary project's dependency set to generate
test fixtures is not a trade worth making.
"""

from __future__ import annotations

import shutil
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Final

from scripts.synthetic.bundle import Bundle
from scripts.synthetic.spec import (
    CONSULTANT,
    CONTRACTOR,
    EMPLOYER,
    PERIODS,
    PROJECT_NAME,
    PROJECT_REF,
)
from scripts.synthetic.workbooks import BANNER

__all__ = ["latex_available", "write_pdfs"]

_ENGINE: Final[str] = "pdflatex"


def latex_available() -> bool:
    return shutil.which(_ENGINE) is not None


def indian_money(value: Decimal) -> str:
    """``11,02,91,018.00`` — the grouping Indian commercial documents actually print.

    Not cosmetic. The last three digits group together and every pair groups above that, so a
    lakh-grouped figure has a different comma pattern from a thousand-grouped one, and a reader
    tested only on Western grouping has not been tested on the corpus it will meet.
    """
    quantised = f"{value:.2f}"
    whole, _, fraction = quantised.partition(".")
    negative = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) <= 3:
        grouped = whole
    else:
        head, tail = whole[:-3], whole[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        grouped = ",".join([*parts, tail])
    return ("-" if negative else "") + grouped + "." + fraction


def _quantity(value: Decimal) -> str:
    return f"{value:,.3f}"


def _escape(text: str) -> str:
    for char, replacement in (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ):
        text = text.replace(char, replacement)
    return text


_PREAMBLE: Final[str] = r"""\documentclass[9pt,a4paper]{article}
\usepackage[a4paper,margin=14mm,top=22mm,bottom=18mm]{geometry}
\usepackage{longtable}
\usepackage{array}
\usepackage{fancyhdr}
\setlength{\parindent}{0pt}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\tiny SYNTHETIC -- FICTIONAL PROJECT -- NOT A REAL DOCUMENT}
\fancyhead[R]{\tiny %(reference)s}
\fancyfoot[C]{\tiny Page \thepage}
\renewcommand{\headrulewidth}{0.2pt}
\begin{document}
\begin{center}
{\large\bfseries %(title)s}\\[2pt]
{\small %(project)s}\\[1pt]
{\footnotesize Employer: %(employer)s}\\[1pt]
{\footnotesize Contractor: %(contractor)s}\\[1pt]
{\footnotesize %(subtitle)s}
\end{center}
\vspace{2mm}
{\scriptsize\itshape %(banner)s}
\vspace{3mm}
"""


def _document(title: str, subtitle: str, body: str) -> str:
    header = _PREAMBLE % {
        "title": _escape(title),
        "project": _escape(PROJECT_NAME),
        "employer": _escape(EMPLOYER),
        "contractor": _escape(CONTRACTOR),
        "subtitle": _escape(subtitle),
        "banner": _escape(BANNER),
        "reference": _escape(PROJECT_REF),
    }
    return header + body + "\n\\end{document}\n"


def _priced_table(rows: list[tuple[str, str, str, str, str, str]], total: str | None) -> str:
    """A six-column priced schedule: item, description, unit, quantity, rate, amount."""
    lines = [
        r"\begin{longtable}{@{}p{16mm}p{74mm}p{11mm}r@{\hspace{4mm}}r@{\hspace{4mm}}r@{}}",
        r"\hline",
        r"{\bfseries Item No} & {\bfseries Description} & {\bfseries Unit} & "
        r"{\bfseries Quantity} & {\bfseries Rate} & {\bfseries Amount}\\",
        r"\hline",
        r"\endhead",
        r"\hline",
        r"\endfoot",
    ]
    for number, description, unit, quantity, rate, amount in rows:
        lines.append(
            f"{_escape(number)} & {_escape(description)} & {_escape(unit)} & "
            f"{quantity} & {rate} & {amount}\\\\"
        )
    if total is not None:
        lines.append(r"\hline")
        lines.append(rf"Total & & & & & {total}\\")
    lines.append(r"\end{longtable}")
    return "\n".join(lines)


def _boq_body(bundle: Bundle, revision: str) -> str:
    items = bundle.boq_rev1 if revision == "Rev01" else bundle.boq_rev2
    total = sum((item.amount for item in items), start=Decimal("0.00"))
    rows = [
        (
            item.number,
            item.description,
            item.unit,
            _quantity(item.quantity),
            indian_money(item.rate),
            indian_money(item.amount),
        )
        for item in items
    ]
    return _priced_table(rows, indian_money(total))


def _measurement_body(bundle: Bundle, period: int) -> str:
    lines = [
        r"\begin{longtable}{@{}p{16mm}p{92mm}p{12mm}r@{}}",
        r"\hline",
        r"{\bfseries Item No} & {\bfseries Description} & {\bfseries Unit} & "
        r"{\bfseries Measured Quantity}\\",
        r"\hline",
        r"\endhead",
        r"\hline",
        r"\endfoot",
    ]
    for row in bundle.measurements[period]:
        lines.append(
            f"{_escape(row.item.number)} & {_escape(row.item.description)} & "
            f"{_escape(row.item.unit)} & {_quantity(row.measured_quantity)}\\\\"
        )
    lines.append(r"\end{longtable}")
    return "\n".join(lines)


def _bill_body(bundle: Bundle, period: int) -> str:
    """The RA bill's printed form.

    Laid out so the *claimed* figures are the priced ones — quantity billed this period, rate,
    amount — with the cumulative columns alongside, which is how a running bill reads. The unit sits
    immediately before the three figures because that is where a printed bill puts it, and it is
    also, incidentally, the anchor ``pdf_boq`` needs. Where the two agree it is because real bills
    settled the convention, not because the layout was chosen to suit the parser.
    """
    lines = [
        r"\begin{longtable}{@{}p{15mm}p{58mm}p{10mm}r@{\hspace{2mm}}r@{\hspace{3mm}}"
        r"r@{\hspace{3mm}}r@{}}",
        r"\hline",
        r"{\bfseries Item No} & {\bfseries Description} & {\bfseries Unit} & "
        r"{\bfseries Upto Date} & {\bfseries Previous} & {\bfseries Rate} & "
        r"{\bfseries Amount}\\",
        r"\hline",
        r"\endhead",
        r"\hline",
        r"\endfoot",
    ]
    for row in bundle.bills[period]:
        lines.append(
            f"{_escape(row.item.number)} & {_escape(row.item.description)} & "
            f"{_escape(row.item.unit)} & {_quantity(row.current_claim)} & "
            f"{_quantity(row.previous_certified)} & {indian_money(row.claimed_rate)} & "
            f"{indian_money(row.amount)}\\\\"
        )
    for extra in bundle.extras.get(period, ()):
        lines.append(
            f"{_escape(extra.number)} & {_escape(extra.description)} & "
            f"{_escape(extra.unit)} & {_quantity(extra.quantity)} & 0.000 & "
            f"{indian_money(extra.rate)} & {indian_money(extra.amount)}\\\\"
        )
    lines.append(r"\hline")
    lines.append(rf"Total & & & & & & {indian_money(bundle.stated_bill_totals[period])}\\")
    lines.append(r"\end{longtable}")
    return "\n".join(lines)


def _variation_body(bundle: Bundle) -> str:
    rows = [
        (
            order.reference,
            order.description,
            order.unit,
            _quantity(order.quantity),
            indian_money(order.rate),
            indian_money(order.amount),
        )
        for order in bundle.variations
    ]
    body = _priced_table(rows, None)
    approvals = "\n\n".join(
        rf"\vspace{{4mm}}{{\small Variation Order {_escape(order.reference)}, dated "
        rf"{_escape(order.dated)}, approved by {_escape(order.approved_by)}.}}"
        for order in bundle.variations
    )
    consultant = rf"\vspace{{4mm}}{{\small Consultant of record: {_escape(CONSULTANT)}.}}"
    return f"{body}\n{approvals}\n\n{consultant}\n"


def _compile(tex: str, path: Path, work: Path) -> None:
    """Run the TeX engine twice, because longtable needs a second pass to settle column widths."""
    source = work / f"{path.stem}.tex"
    source.write_text(tex, encoding="utf-8")
    for _ in range(2):
        # S603: the argument vector is a fixed engine name plus a filename this module wrote
        # into a temporary directory. No shell, and no value from outside this package.
        result = subprocess.run(  # noqa: S603
            [_ENGINE, "-interaction=nonstopmode", "-halt-on-error", source.name],
            cwd=work,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            tail = "\n".join(result.stdout.splitlines()[-25:])
            raise RuntimeError(f"{_ENGINE} failed for {path.name}:\n{tail}")
    produced = work / f"{path.stem}.pdf"
    path.write_bytes(produced.read_bytes())


def write_pdfs(bundle: Bundle, directory: Path, work: Path) -> list[Path]:
    """Render every document as a printed PDF. Returns the paths written."""
    directory.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for revision in ("Rev01", "Rev02"):
        path = directory / f"SYNTHETIC_BOQ-{revision}_{PROJECT_REF}.pdf"
        _compile(
            _document(
                "BILL OF QUANTITIES",
                f"Revision {revision[-2:]}",
                _boq_body(bundle, revision),
            ),
            path,
            work,
        )
        written.append(path)

    for detail in PERIODS:
        path = directory / f"SYNTHETIC_Measurement-{detail.number:02d}_{PROJECT_REF}.pdf"
        _compile(
            _document(
                "MEASUREMENT SHEET",
                f"Period {detail.number}, measured on {detail.measured_on}",
                _measurement_body(bundle, detail.number),
            ),
            path,
            work,
        )
        written.append(path)

    for detail in PERIODS:
        path = directory / f"SYNTHETIC_RA-Bill-{detail.number:02d}_{PROJECT_REF}.pdf"
        _compile(
            _document(
                f"RUNNING ACCOUNT BILL {detail.label}",
                f"Dated {detail.billed_on}",
                _bill_body(bundle, detail.number),
            ),
            path,
            work,
        )
        written.append(path)

    path = directory / f"SYNTHETIC_Variation-Orders_{PROJECT_REF}.pdf"
    _compile(
        _document("VARIATION ORDERS", "Approved variations to date", _variation_body(bundle)),
        path,
        work,
    )
    written.append(path)

    return written
