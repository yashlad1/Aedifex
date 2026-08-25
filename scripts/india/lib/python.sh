#!/usr/bin/env bash
# Stage 2 -- the Python environment.
#
# Reused, not rebuilt. A rebuild costs several minutes and a lot of bandwidth on a home connection,
# so the environment is recreated only when it is actually unusable, and dependencies are installed
# only when the lockfile has changed since the last successful install.
#
# This calls `make install`, which is the repository's own documented install path
# (`uv sync --locked --extra dev`). It does not invent a second one: an environment built here that
# differed from the one CI builds would make a failure on this Mac impossible to reproduce.

readonly VENV_DIR="$REPO_ROOT/.venv"
readonly VENV_PY="$VENV_DIR/bin/python"
readonly INSTALL_STAMP="$VENV_DIR/.india-runner-install-stamp"

python_environment() {
    step "Preparing the software..."

    if _venv_is_healthy; then
        ok "Software environment is ready"
    else
        _create_venv || return 1
    fi

    if _dependencies_are_current; then
        ok "Dependencies are up to date"
        return 0
    fi

    _install_dependencies || return 1
}

_venv_is_healthy() {
    [[ -x "$VENV_PY" ]] || { log "no interpreter at $VENV_PY"; return 1; }
    local ver
    ver="$("$VENV_PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
    case "$ver" in
        3.12|3.13) ;;
        *) log "venv interpreter reports Python ${ver:-unknown}; rebuilding"; return 1 ;;
    esac
    # The package itself, not just the interpreter: a half-finished `uv sync` leaves a venv that
    # runs but cannot import anything, and that failure is otherwise deferred to the crawl.
    run_logged "$VENV_PY" -c "import aedifex, sqlalchemy, yaml, boto3" || {
        log "venv exists but cannot import the application; rebuilding"
        return 1
    }
    return 0
}

_create_venv() {
    if [[ -e "$VENV_DIR" ]]; then
        say "  Rebuilding the software environment (the existing one is incomplete)..."
        run_logged rm -rf "$VENV_DIR" || true
    else
        say "  Setting up for the first time. This takes a few minutes..."
    fi
    # Deliberately no output on the console: pip and uv print hundreds of resolution lines.
    if ! run_logged "$PYTHON_BOOTSTRAP" -m venv "$VENV_DIR"; then
        die 20 "Could not create the Python environment." \
                "" \
                "This usually means the Python installation is damaged." \
                "Reinstalling Python 3.13 from https://www.python.org/downloads/macos/ normally fixes it."
    fi
    if ! run_logged "$VENV_DIR/bin/pip" install --quiet --upgrade pip uv; then
        die 20 "Could not download the Python package installer." \
                "" \
                "This is almost always a network problem. Please check the Wi-Fi and try again."
    fi
    rm -f "$INSTALL_STAMP"
    ok "Software environment created"
}

# The lockfile is the input; the stamp records which lockfile the current environment was built
# from. Equal means there is nothing to do -- `uv sync` would be a no-op that still costs a minute.
_lock_fingerprint() {
    cat "$REPO_ROOT/uv.lock" "$REPO_ROOT/pyproject.toml" 2>/dev/null | shasum -a 256 | cut -d' ' -f1
}

_dependencies_are_current() {
    [[ -f "$INSTALL_STAMP" ]] || return 1
    [[ "$(cat "$INSTALL_STAMP")" == "$(_lock_fingerprint)" ]]
}

_install_dependencies() {
    say "  Installing dependencies. This takes a few minutes the first time..."
    if ! run_logged make -C "$REPO_ROOT" install; then
        die 20 "Could not install the software this needs." \
                "" \
                "This is usually a network problem -- the download did not finish." \
                "Please check the Wi-Fi connection and try again."
    fi
    _lock_fingerprint >"$INSTALL_STAMP"
    ok "Dependencies installed"
}
