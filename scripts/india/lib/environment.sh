#!/usr/bin/env bash
# Stage 3 -- configuration.
#
# Two sources of configuration, and the split is deliberate.
#
#   .env               machine defaults. Created if absent, and NEVER modified afterwards. If an
#                      operator or a previous run left settings here, they are kept exactly.
#   the run list       the three values that decide where evidence goes and who we identify as.
#                      These are exported into the environment of the crawl process instead of
#                      being written to .env, because a process environment variable outranks .env
#                      in Settings. So the reviewed manifest wins every run without ever editing,
#                      overwriting or second-guessing a file somebody else owns.
#
# The endpoint matters more than it looks. Leaving AEDIFEX_STORAGE_ENDPOINT_URL unset does not mean
# "no storage" -- it means real AWS S3, which on this machine has no credentials and is not where
# this evidence belongs. .env.example documents the same trap for developers.

configure_environment() {
    step "Setting up configuration..."
    _create_env_if_missing || return 1
    _export_manifest_settings
    ok "Configuration ready"
}

_create_env_if_missing() {
    local env_file="$REPO_ROOT/.env"
    if [[ -f "$env_file" ]]; then
        note "Keeping the existing settings file"
        log ".env already exists; left untouched"
        return 0
    fi
    log "creating .env from the development defaults"
    cat >"$env_file" <<'ENVEOF'
# Written by the India Acquisition Runner on first run. Safe to keep between runs.
#
# Deliberately contains only machine defaults. The bucket, the storage endpoint and the User-Agent
# come from config/india_runner.yaml at run time and are not written here, so editing this file
# cannot change where evidence is stored or who we identify ourselves as to a portal.
AEDIFEX_ENVIRONMENT=development
AEDIFEX_DEBUG=false

AEDIFEX_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/aedifex
AEDIFEX_DATABASE_POOL_SIZE=5
AEDIFEX_DATABASE_STATEMENT_TIMEOUT_SECONDS=30

AEDIFEX_STORAGE_REGION=us-east-1
AEDIFEX_STORAGE_ACCESS_KEY_ID=minioadmin
AEDIFEX_STORAGE_SECRET_ACCESS_KEY=minioadmin

AEDIFEX_SOURCE_REGISTRY_DIR=config/sources

AEDIFEX_MAX_DOWNLOAD_BYTES=268435456
AEDIFEX_REQUEST_TIMEOUT_SECONDS=30

AEDIFEX_LOG_LEVEL=INFO
AEDIFEX_LOG_FORMAT=console
ENVEOF
    ok "Settings file created"
}

_export_manifest_settings() {
    # INDIA_* are produced by `manifest.py shell`, already validated and shell-quoted.
    export AEDIFEX_USER_AGENT="$INDIA_USER_AGENT"
    export AEDIFEX_STORAGE_BUCKET="$INDIA_STORAGE_BUCKET"
    export AEDIFEX_STORAGE_ENDPOINT_URL="$INDIA_STORAGE_ENDPOINT"
    log "storage -> ${INDIA_STORAGE_ENDPOINT} bucket ${INDIA_STORAGE_BUCKET}"
    log "user agent -> ${INDIA_USER_AGENT}"
}
