#!/usr/bin/env bash
# Render one of this repository's markdown documents as a PDF fit to hand to someone outside it.
#
# Usage:  scripts/build_pdf.sh docs/DATA_REQUEST.md [output.pdf]
# Default output: ~/Downloads/<document title>.pdf
#
# The title block comes from the document itself -- its H1 and the paragraph under it -- so a
# document needs no metadata here to render properly, and this script needs no edit per document.
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
SRC="${1:?usage: scripts/build_pdf.sh <source.md> [output.pdf]}"
test -f "$SRC" || { echo "no such document: $SRC"; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

command -v pandoc  >/dev/null || { echo "pandoc not found: brew install pandoc"; exit 1; }
command -v xelatex >/dev/null || { echo "xelatex not found: install MacTeX or BasicTeX"; exit 1; }

# Drop the H1 and standfirst (they become the title block), and give each pipe table column a dash
# count proportional to its widest cell so the LaTeX writer allocates width by content.
python3 - "$SRC" "$WORK" <<'PY'
import pathlib, re, sys

work = pathlib.Path(sys.argv[2])
lines = pathlib.Path(sys.argv[1]).read_text().splitlines()

title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("# ") else ""
rest = lines[1:]
while rest and not rest[0].strip():
    rest.pop(0)

# The standfirst is the first paragraph only. Taking every line up to the rule swallowed the whole
# preamble into the subtitle, which on the sprint report meant three paragraphs under the title.
subtitle_lines = []
while rest and rest[0].strip() and not rest[0].startswith(("#", "|", "---")):
    subtitle_lines.append(rest.pop(0).strip())
subtitle = " ".join(subtitle_lines)

# A leading horizontal rule now separates the standfirst from the body; drop it if present.
while rest and (not rest[0].strip() or rest[0].strip() == "---"):
    rest.pop(0)
body = rest

# Written as YAML, not passed with --metadata, because --metadata sets a plain string and the bold
# in a standfirst then reaches the page as literal asterisks.
def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

work.joinpath("meta.yaml").write_text(
    "---\n"
    f"title: {yaml_quote(title)}\n"
    f"subtitle: {yaml_quote(subtitle)}\n"
    "---\n"
)

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
        # +3 because these floors are character counts and the column has to hold a rendered word
        # plus LaTeX's cell padding. Without the slack, a "Ticket" column floored at exactly
        # len("SCRUM-17") still broke it across two lines.
        longest_word = [
            max([len(w) for w in header[c].split()] +
                [len(w) for r in rows if len(r) > c for w in r[c].split()] + [3]) + 3
            for c in range(len(header))
        ]
        # Width grows with the *square root* of the content, not linearly. Linearly, a column whose
        # longest cell is 170 characters starves one whose longest is 36 -- which is how "Acquire an
        # authentic building bundle" ended up broken across four lines beside a long explanation.
        # Long text wraps and absorbs a narrow column; short text cannot.
        weight = [w ** 0.5 for w in widest]
        span = sum(weight) or len(header)
        out.append(
            "|"
            + "|".join(
                "-" * max(3, round(TOTAL * w / span), floor)
                for w, floor in zip(weight, longest_word)
            )
            + "|"
        )
        i += 1
        continue
    out.append(line)
    i += 1

work.joinpath("body.md").write_text("\n".join(out) + "\n")
PY

TITLE="$(sed -n 's/^title: "\(.*\)"$/\1/p' "$WORK/meta.yaml")"
OUT="${2:-$HOME/Downloads/$(echo "$TITLE" | sed 's/[^A-Za-z0-9]\{1,\}/-/g; s/^-//; s/-$//').pdf}"

pandoc "$WORK/meta.yaml" "$WORK/body.md" -o "$OUT" \
    --pdf-engine=xelatex \
    --from=markdown+pipe_tables+backtick_code_blocks \
    --metadata date="$(date '+%-d %B %Y')" \
    -V geometry:"a4paper,top=2.2cm,bottom=2cm,left=2.2cm,right=2.2cm" \
    -V mainfont="Helvetica Neue" \
    -V monofont="SF Mono" \
    -V fontsize=10pt \
    -V linestretch=1.08 \
    -V colorlinks=true -V linkcolor=black -V urlcolor=black \
    2>&1 | (grep -E "no . \(U\+|Overfull" || true)

echo "wrote $OUT  ($(du -h "$OUT" | cut -f1), $(pdfinfo "$OUT" 2>/dev/null | awk '/^Pages/{print $2" pages"}'))"
