#!/usr/bin/env bash
# Stage 7 -- the result file.
#
# One archive on the Desktop containing everything needed to reconstruct this acquisition
# elsewhere: the raw bytes, the provenance rows that say where each came from, the crawl records,
# the manifest, and this run's log.
#
# The export is built by walking the `documents` table, not by listing the storage bucket, so an
# object with no provenance cannot ride along unnoticed. Every file is re-hashed on the way in and
# checked against the digest the database recorded; a mismatch stops the packaging rather than
# shipping an artifact whose provenance no longer describes it.
#
# Caches, the virtual environment, the database volume and the source tree are all excluded. The
# bundle is evidence and its paperwork, nothing else.

BUNDLE_PATH=""

package_results() {
    step "Preparing the file to send..."

    local stamp bundle_name staging
    stamp="$(date "+%Y-%m-%d")"
    bundle_name="Aedifex-India-${stamp}"
    staging="$REPO_ROOT/.india-bundle/$bundle_name"

    rm -rf "$REPO_ROOT/.india-bundle"
    mkdir -p "$staging"

    local summary
    if ! summary="$("$VENV_PY" -m scripts.india.bundle export "$staging" 2>>"$LOG_FILE")"; then
        die 90 "Could not prepare the result file." \
                "" \
                "The documents were collected successfully and nothing has been lost;" \
                "only the packaging step failed. Please send the log and Yash will advise."
    fi
    log "export summary: $summary"

    mkdir -p "$staging/logs"
    cp "$LOG_FILE" "$staging/logs/" 2>/dev/null || true
    cp "$REPO_ROOT/config/india_runner.yaml" "$staging/" 2>/dev/null || true

    local desktop="$HOME/Desktop"
    mkdir -p "$desktop"
    BUNDLE_PATH="$desktop/${bundle_name}.tar.gz"

    # -C so the archive contains one clearly-named folder rather than a path from this Mac.
    if ! run_logged tar -czf "$BUNDLE_PATH" -C "$REPO_ROOT/.india-bundle" "$bundle_name"; then
        die 90 "Could not save the result file to the Desktop." \
                "" \
                "This usually means the disk is full. Please empty the Trash and try again."
    fi

    _write_checksum "$BUNDLE_PATH"
    rm -rf "$REPO_ROOT/.india-bundle"

    ok "Result file created"
    return 0
}

# A digest beside the archive, so the receiver can prove the file arrived intact. Email and chat
# apps have re-encoded attachments before now, and a silently truncated bundle would otherwise look
# exactly like a successful transfer.
_write_checksum() {
    local archive="$1"
    shasum -a 256 "$archive" | awk '{print $1}' >"${archive}.sha256"
    log "bundle sha256: $(cat "${archive}.sha256")"
}

bundle_size_human() {
    [[ -f "$BUNDLE_PATH" ]] || { printf 'unknown'; return; }
    du -h "$BUNDLE_PATH" | awk '{print $1}'
}
