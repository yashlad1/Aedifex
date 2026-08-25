#!/usr/bin/env bash
# Stage 5 -- schema.
#
# `alembic upgrade head` is already idempotent: at head it applies nothing and exits zero. The
# runner still asks alembic first whether the schema is current, so the console can say "already up
# to date" instead of implying work happened. The database is never dropped or recreated; there is
# no code path in this runner that does either.

migrate_database() {
    step "Preparing the database..."

    _database_is_reachable || return 1

    if _schema_is_current; then
        ok "Database is already up to date"
        return 0
    fi

    say "  Updating the database..."
    if run_logged "$VENV_DIR/bin/alembic" upgrade head; then
        ok "Database updated"
        return 0
    fi
    die 60 "Could not prepare the database." \
            "" \
            "The database is running but the update did not finish." \
            "Nothing was deleted. Trying again usually works."
}

# Asked before migrating, because a refused connection and a failed migration are different
# problems with different fixes, and reporting the first as the second sends an operator round a
# loop that cannot succeed.
_database_is_reachable() {
    local version
    if version="$("$VENV_PY" -m scripts.india.bundle ping 2>>"$LOG_FILE")"; then
        log "database answered: PostgreSQL $version"
        return 0
    fi
    die 60 "Could not connect to the database." \
            "" \
            "The database container is running, but this Mac could not talk to it." \
            "The usual cause is another copy of PostgreSQL already using port 5432, so the" \
            "connection reaches the wrong server." \
            "" \
            "If PostgreSQL was ever installed on this Mac outside of Docker, quitting or" \
            "uninstalling it will clear this."
}

_schema_is_current() {
    # `alembic check` exits non-zero when the models and the migrations disagree, which is a
    # developer problem rather than an operator one; here it is only used as "is there anything to
    # do", and a non-zero result simply means "run the upgrade".
    run_logged "$VENV_DIR/bin/alembic" check
}
