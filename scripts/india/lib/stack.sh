#!/usr/bin/env bash
# Stage 4 -- PostgreSQL and MinIO, via the repository's own docker compose stack.
#
# Nothing here is destructive. `docker compose up -d` is idempotent: containers already running are
# reused and their volumes are left alone. `docker compose down -v`, which deletes the database and
# the stored objects, is never issued by this runner under any circumstance -- an interrupted run
# has to be able to continue, and evidence already acquired is immutable.

readonly RUNTIME_WAIT_SECONDS=180
readonly HEALTH_WAIT_SECONDS=180

start_stack() {
    step "Starting the database..."
    _ensure_container_runtime || return 1
    _compose_up || return 1
    _wait_for_health || return 1
}

_ensure_container_runtime() {
    if run_logged docker info; then
        ok "Docker is running"
        return 0
    fi

    # "If containers are already running, reuse them" -- including the case where the docker CLI is
    # pointed at a runtime that is not the one running. Colima's socket is adopted for this process
    # only, via DOCKER_HOST; the operator's own docker context is not modified. On a Mac with just
    # one runtime installed, which is the India machine, this does nothing.
    if _adopt_running_colima; then
        ok "Docker is running (Colima)"
        return 0
    fi

    if [[ -d "/Applications/Docker.app" ]]; then
        say "  Starting Docker Desktop. This takes up to two minutes..."
        run_logged open -a Docker || true
    elif command -v colima >/dev/null 2>&1; then
        say "  Starting Colima. This takes up to two minutes..."
        run_logged colima start || true
    else
        die 50 "Docker is installed but not running, and this tool could not start it." \
                "" \
                "To fix this:" \
                "  1. Open the Applications folder and double-click Docker" \
                "  2. Wait until its whale icon in the menu bar stops animating" \
                "  3. Double-click 'Run Aedifex.command' again"
    fi

    local waited=0
    while (( waited < RUNTIME_WAIT_SECONDS )); do
        sleep 5; waited=$(( waited + 5 ))
        if run_logged docker info; then
            ok "Docker is running"
            return 0
        fi
        log "waiting for the container runtime (${waited}s)"
    done

    die 50 "Docker did not finish starting after $(( RUNTIME_WAIT_SECONDS / 60 )) minutes." \
            "" \
            "Please open Docker Desktop from the Applications folder, wait until it says it is" \
            "running, then double-click 'Run Aedifex.command' again."
}

_adopt_running_colima() {
    command -v colima >/dev/null 2>&1 || return 1
    local socket="$HOME/.colima/default/docker.sock"
    [[ -S "$socket" ]] || return 1
    export DOCKER_HOST="unix://${socket}"
    log "trying already-running Colima at $DOCKER_HOST"
    if run_logged docker info; then
        return 0
    fi
    unset DOCKER_HOST
    return 1
}

_compose_up() {
    say "  Starting the database and file storage..."
    # `make up` -- the repository's own target, so this runner cannot drift from how the stack is
    # started everywhere else.
    if run_logged make -C "$REPO_ROOT" up; then
        ok "Database and file storage started"
        return 0
    fi
    die 50 "Could not start the database." \
            "" \
            "Docker is running but refused to start the database container." \
            "This is often fixed by quitting Docker Desktop completely and opening it again."
}

_wait_for_health() {
    # compose already declares healthchecks for both services; this waits for them rather than
    # re-testing what they test.
    local waited=0 unhealthy
    while (( waited < HEALTH_WAIT_SECONDS )); do
        if ! run_logged docker compose --project-directory "$REPO_ROOT" ps; then
            # Distinguished from "still starting" on purpose. An unreachable Docker reports every
            # service as not-healthy, which would otherwise time out after three minutes behind a
            # message about the database that names the wrong cause.
            die 50 "Lost the connection to Docker while starting the database." \
                    "" \
                    "Please open Docker Desktop from the Applications folder, wait until it says" \
                    "it is running, then double-click 'Run Aedifex.command' again."
        fi
        unhealthy="$(_unhealthy_services)"
        if [[ -z "$unhealthy" ]]; then
            ok "Database is ready"
            return 0
        fi
        log "waiting for: ${unhealthy} (${waited}s)"
        sleep 5; waited=$(( waited + 5 ))
    done
    die 50 "The database started but never became ready." \
            "" \
            "Services still not ready: ${unhealthy}" \
            "" \
            "Restarting this Mac and trying again usually clears it."
}

_unhealthy_services() {
    local service state names=""
    for service in postgres minio; do
        state="$(docker compose --project-directory "$REPO_ROOT" ps \
                    --format '{{.Service}} {{.Health}}' 2>/dev/null \
                 | awk -v s="$service" '$1 == s {print $2}')"
        [[ "$state" == "healthy" ]] || names+="${service} "
    done
    printf '%s' "${names% }"
}
