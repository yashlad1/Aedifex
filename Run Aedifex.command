#!/bin/bash
#
# Double-click this file to collect documents and produce the file to send back.
#
# It is a launcher and nothing more: it finds the folder it lives in and hands over to
# scripts/india/run.sh. See docs/INDIA_RUNNER.md.
#
# run.sh is invoked as `bash <path>` rather than executed directly, so the run only depends on THIS
# file being executable. A ZIP downloaded from GitHub does not always preserve the executable bit,
# and one file to fix is better than nine.

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here" || exit 1

runner="$here/scripts/india/run.sh"
if [[ ! -f "$runner" ]]; then
    printf '\n  This file has been moved out of the Aedifex folder.\n'
    printf '  Please put it back next to the "scripts" folder and try again.\n\n'
    printf '  Press Enter to close this window.'
    read -r _
    exit 1
fi

bash "$runner"
status=$?

printf '  Press Enter to close this window.'
read -r _
exit "$status"
