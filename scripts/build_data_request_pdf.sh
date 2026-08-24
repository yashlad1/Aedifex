#!/usr/bin/env bash
# Render docs/DATA_REQUEST.md as a PDF fit to hand to someone outside the project.
#
# Usage:  scripts/build_data_request_pdf.sh [output.pdf]
# Default output: ~/Downloads/Aedifex-Data-Request.pdf
#
# Three things here are not defaults and each one was a visible defect first:
#
#   --from=markdown, not gfm     pandoc's gfm reader ignores the dash counts in a pipe table's
#                                separator row, because GFM gives them no meaning. The LaTeX writer
#                                then guessed equal columns and the "Why we need it" column ran off
#                                the right edge of page 1. The markdown reader's pipe_tables reads
#                                those dashes as relative widths, which is what the pre-pass below
#                                sets from the real content.
#   monofont "SF Mono"           of the mono fonts on macOS, it is the one carrying U+20B9. Menlo,
#                                Monaco, Courier New, Andale Mono and PT Mono all drop it, and the
#                                rupee in the worked example is the whole point of that example.
#   title from metadata          the document's own H1 and standfirst are lifted into a title block,
#                                so page 1 reads as a document rather than as a wiki page.
set -euo pipefail

cd "$(dirname "$0")/.."
SRC="docs/DATA_REQUEST.md"
OUT="${1:-$HOME/Downloads/Aedifex-Data-Request.pdf}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

command -v pandoc  >/dev/null || { echo "pandoc not found: brew install pandoc"; exit 1; }
command -v xelatex >/dev/null || { echo "xelatex not found: install MacTeX or BasicTeX"; exit 1; }

# Drop the H1 and standfirst (they become the title block), and give each pipe table column a dash
# count proportional to its widest cell so the LaTeX writer allocates width by content.
python3 - "$SRC" "$WORK/body.md" <<'PY'
import pathlib, re, sys

lines = pathlib.Path(sys.argv[1]).read_text().splitlines()
start = next(i for i, line in enumerate(lines) if line.strip() == "---")
body = "\n".join(lines[start + 1:]).lstrip("\n").splitlines()

def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]

TOTAL = 74  # dashes to distribute across a table's columns
out, i = [], 0
while i < len(body):
    line = body[i]
    separator = "-" in line and re.fullmatch(r"\|[\s:|-]+\|", line.strip())
    if separator and i and body[i - 1].strip().startswith("|"):
        header = cells(body[i - 1])
        rows, j = [], i + 1
        while j < len(body) and body[j].strip().startswith("|"):
            rows.append(cells(body[j]))
            j += 1
        widest = [
            max([len(header[c])] + [len(r[c]) for r in rows if len(r) > c])
            for c in range(len(header))
        ]
        span = sum(widest) or len(header)
        out.append("|" + "|".join("-" * max(3, round(TOTAL * w / span)) for w in widest) + "|")
        i += 1
        continue
    out.append(line)
    i += 1

pathlib.Path(sys.argv[2]).write_text("\n".join(out) + "\n")
PY

pandoc "$WORK/body.md" -o "$OUT" \
    --pdf-engine=xelatex \
    --from=markdown+pipe_tables+backtick_code_blocks \
    --metadata title="Aedifex — what we are asking for, and why" \
    --metadata subtitle="A request for one real building project's documents. Written to be forwarded as-is." \
    --metadata date="$(date '+%-d %B %Y')" \
    -V geometry:"a4paper,top=2.2cm,bottom=2cm,left=2.2cm,right=2.2cm" \
    -V mainfont="Helvetica Neue" \
    -V monofont="SF Mono" \
    -V fontsize=10pt \
    -V linestretch=1.08 \
    -V colorlinks=true -V linkcolor=black -V urlcolor=black \
    2>&1 | (grep -E "no . \(U\+|Overfull" || true)

echo "wrote $OUT  ($(du -h "$OUT" | cut -f1), $(pdfinfo "$OUT" 2>/dev/null | awk '/^Pages/{print $2" pages"}'))"
