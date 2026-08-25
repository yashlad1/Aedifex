#!/usr/bin/env bash
# Stage 6 -- acquisition.
#
# This stage does not acquire anything itself. It reads the run list and calls the operator CLI that
# already exists, once per source:
#
#     python -m apps.crawler.main crawl <source_id> [limits]
#
# Everything that makes a crawl safe -- robots, rate limits, the SSRF guard, format allowlists,
# content validation, immutable storage, provenance rows, the approval gate -- lives behind that
# command and is untouched. The runner cannot pass a URL, a rate or a permitted format, because the
# CLI does not accept them; those are reviewed configuration in config/sources/.
#
# Re-running is safe by construction rather than by checking: storage is content-addressed, so the
# same bytes are the same artifact, and the frontier persists, so an interrupted crawl continues
# instead of starting over.

readonly HEARTBEAT_SECONDS=60

DOCUMENTS_BEFORE=0
DOCUMENTS_AFTER=0
SOURCES_RUN=0

acquire() {
    step "Collecting documents..."

    DOCUMENTS_BEFORE="$(_document_count)" || return 1
    log "documents before: $DOCUMENTS_BEFORE"

    local sources_tsv source_id args
    if ! sources_tsv="$("$VENV_PY" -m scripts.india.manifest sources 2>>"$LOG_FILE")"; then
        die 80 "Could not read the run list." \
                "This is a configuration problem, not something you can fix on this Mac."
    fi
    while IFS=$'\t' read -r source_id args; do
        [[ -n "$source_id" ]] || continue
        _crawl_one "$source_id" "$args"
        SOURCES_RUN=$(( SOURCES_RUN + 1 ))
    done <<<"$sources_tsv"

    if (( SOURCES_RUN == 0 )); then
        die 80 "The run list named no sources to collect from." \
                "This is a configuration problem, not something you can fix on this Mac."
    fi

    DOCUMENTS_AFTER="$(_document_count)" || return 1
    log "documents after: $DOCUMENTS_AFTER"
    return 0
}

_document_count() {
    local count
    if ! count="$("$VENV_PY" -m scripts.india.bundle count 2>>"$LOG_FILE")"; then
        die 80 "Could not read the document list from the database." \
                "The database is running but did not answer. Trying again usually works."
    fi
    printf '%s' "$count"
}

_crawl_one() {
    local source_id="$1" args="$2"
    say "  Collecting from ${source_id}..."
    log "crawl ${source_id} ${args}"

    local before after
    before="$(_document_count)"

    # shellcheck disable=SC2086  # args is a validated, space-separated flag list from manifest.py
    "$VENV_PY" -m apps.crawler.main crawl "$source_id" $args >>"$LOG_FILE" 2>&1 &
    local crawl_pid=$!
    local status=0
    _wait_with_heartbeat "$crawl_pid" || status=$?

    after="$(_document_count)"
    local gained=$(( after - before ))

    if (( status != 0 )); then
        die 80 "Could not collect from ${source_id}." \
                "" \
                "$(_explain_crawl_failure "$status")" \
                "" \
                "$(( gained > 0 ? gained : 0 )) document(s) were saved before it stopped, and they are safe." \
                "Running this again will continue from where it stopped."
    fi

    if (( gained == 0 )); then
        # Not a failure. A source with nothing new is the normal result of a second run, and the
        # difference matters: reporting it as an error would teach the operator to ignore errors.
        warn "${source_id}: nothing new (everything already collected)"
    else
        ok "${source_id}: ${gained} new document(s)"
    fi
    return 0
}

_wait_with_heartbeat() {
    local pid="$1" waited=0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 5
        waited=$(( waited + 5 ))
        if (( waited % HEARTBEAT_SECONDS == 0 )); then
            note "still working... ($(( waited / 60 )) min)"
        fi
    done
    wait "$pid"
}

# The CLI's exit codes, translated. Anything unrecognised is reported honestly as unrecognised
# rather than guessed at -- a wrong explanation is worse than "the log says why".
_explain_crawl_failure() {
    case "$1" in
        2)  printf 'The website refused the connection, or it is not reachable from this Mac.' ;;
        130) printf 'The run was stopped before it finished.' ;;
        *)  printf 'The collection stopped with an error. The log records what it was.' ;;
    esac
}
