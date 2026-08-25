#!/usr/bin/env bash
#
# The India Acquisition Runner.
#
# One ordered sequence of stages, each in its own file under lib/. This file decides the order and
# what a finished run says; it contains no acquisition, storage or validation logic of its own, and
# every stage calls the repository's existing entry points -- `make install`, `make up`, `alembic
# upgrade`, `python -m apps.crawler.main crawl`.
#
# Stages, and the exit code each uses:
#
#     10  preflight      can this Mac do the job at all
#     20  python         the virtual environment and the locked dependency set
#     30  run list       config/india_runner.yaml, validated against the real source registry
#     40  configuration  .env if absent; the manifest's three settings into the environment
#     50  stack          PostgreSQL and MinIO via docker compose
#     60  database       migrations, if any are outstanding
#     80  acquisition    the crawl, one source at a time
#     90  packaging      the archive on the Desktop
#      1  unexpected     anything that got past the stages
#
# A stage that fails stops the run. Nothing is rolled back, because nothing needs to be: storage is
# content-addressed and append-only, the frontier persists, and a repeat run continues rather than
# restarting.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly REPO_ROOT
cd "$REPO_ROOT"

mkdir -p "$REPO_ROOT/logs"
LOG_FILE="$REPO_ROOT/logs/$(date "+%Y-%m-%d_%H-%M-%S").log"
readonly LOG_FILE
: >"$LOG_FILE"

readonly LIB="$REPO_ROOT/scripts/india/lib"
# shellcheck source=lib/logging.sh
source "$LIB/logging.sh"
# shellcheck source=lib/preflight.sh
source "$LIB/preflight.sh"
# shellcheck source=lib/python.sh
source "$LIB/python.sh"
# shellcheck source=lib/environment.sh
source "$LIB/environment.sh"
# shellcheck source=lib/stack.sh
source "$LIB/stack.sh"
# shellcheck source=lib/database.sh
source "$LIB/database.sh"
# shellcheck source=lib/acquire.sh
source "$LIB/acquire.sh"
# shellcheck source=lib/package.sh
source "$LIB/package.sh"

_unexpected() {
    local status=$?
    [[ $status -eq 0 ]] && return 0
    printf '\n'
    bad "FAILED"
    printf '\n  Something went wrong that this tool did not expect.\n'
    printf '  Nothing has been broken, and running it again is safe.\n\n'
    printf '  Please send this file to Yash:\n    %s\n\n' "$LOG_FILE"
    log "UNEXPECTED EXIT $status"
    exit 1
}
trap _unexpected EXIT

# Stage 3. Kept here rather than in a file of its own: it is the orchestrator reading its own
# configuration, and it exists to fail before anything is started rather than during a crawl.
read_run_list() {
    step "Checking the list of websites to collect from..."

    # `check` validates the file and looks every source up in the real registry. It runs first, so
    # a run list that names an unapproved source stops here -- before Docker starts and long before
    # anything touches a network. It cannot approve a source; it can only refuse one.
    local error_file="$REPO_ROOT/logs/.manifest-error"
    if ! "$VENV_PY" -m scripts.india.manifest check >>"$LOG_FILE" 2>"$error_file"; then
        local reason; reason="$(cat "$error_file")"
        cat "$error_file" >>"$LOG_FILE"
        rm -f "$error_file"
        die 30 "The list of websites to collect from cannot be used." "" \
                "${reason:-See the log for the reason.}" "" \
                "This is a configuration problem, not something you can fix on this Mac."
    fi
    rm -f "$error_file"

    # Now guaranteed to parse, so its output can be trusted into the shell.
    eval "$("$VENV_PY" -m scripts.india.manifest shell)"
    export INDIA_USER_AGENT INDIA_STORAGE_BUCKET INDIA_STORAGE_ENDPOINT

    ok "${INDIA_SOURCE_COUNT} website(s) approved and ready"
}

report_success() {
    local gained=$(( DOCUMENTS_AFTER - DOCUMENTS_BEFORE ))
    printf '\n'
    say "================================================="
    printf '  %sSUCCESS%s\n' "$C_OK" "$C_OFF"
    log "SUCCESS"
    printf '\n'
    if (( gained > 0 )); then
        say "  ${gained} new document(s) collected."
    else
        say "  No new documents this time -- everything was already collected."
    fi
    say "  ${DOCUMENTS_AFTER} document(s) in total."
    printf '\n'
    say "  File to send:"
    say "    $BUNDLE_PATH"
    say "    ($(bundle_size_human))"
    printf '\n'
    printf '  Please send that file to Yash.\n'
    printf '  It is on the Desktop. Attaching it to an email or a message is enough.\n'
    printf '\n'
    say "================================================="
    printf '\n'
    log "bundle: $BUNDLE_PATH"
}

main() {
    banner "AEDIFEX INDIA ACQUISITION"
    log "runner starting in $REPO_ROOT"

    preflight
    python_environment
    read_run_list
    configure_environment
    start_stack
    migrate_database
    acquire
    package_results
    report_success

    trap - EXIT
    log "EXIT 0"
    exit 0
}

main "$@"
