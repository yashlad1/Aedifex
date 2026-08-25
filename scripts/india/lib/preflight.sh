#!/usr/bin/env bash
# Stage 1 -- can this machine do the job at all?
#
# Everything here is a read-only check. Nothing is installed, started, written or changed. The
# stage exists so that a machine which cannot finish the run says so in one sentence at the start,
# rather than failing thirty minutes in with a message about a Docker socket.

readonly MIN_FREE_GB=12
readonly REACHABILITY_HOST="nhai.gov.in"

# Set by the checks below and acted on by install.sh. A missing prerequisite is not fatal here: it
# is a thing to install. Nothing else in preflight installs, starts or writes anything.
NEED_PYTHON=0
NEED_DOCKER=0

preflight() {
    step "Checking this computer..."

    _check_macos || return 1
    _check_arch
    # Before the disk check, because what has to be downloaded decides how much room is needed.
    _check_python
    _check_container_runtime
    _check_memory
    _check_disk || return 1
    _check_writable || return 1
    _check_network || return 1

    return 0
}

# Run after install.sh. By this point a missing prerequisite *is* fatal: it means an install
# reported success and left nothing behind, and continuing would fail later with a worse message.
recheck_prerequisites() {
    (( NEED_PYTHON == 0 )) || die 20 "Python is still missing after being installed." \
        "Please send the log file below."
    (( NEED_DOCKER == 0 )) || die 20 "Docker is still missing after being installed." \
        "Please send the log file below."
}

_check_macos() {
    local name version
    name="$(uname -s)"
    if [[ "$name" != "Darwin" ]]; then
        die 10 "This tool only runs on a Mac." \
                "This computer reports itself as '$name'."
    fi
    version="$(sw_vers -productVersion 2>/dev/null || echo unknown)"
    log "macOS $version, $(uname -m)"
    # 12 = Monterey, the oldest release Docker Desktop and Colima both still support.
    local major="${version%%.*}"
    if [[ "$major" =~ ^[0-9]+$ ]] && (( major < 12 )); then
        die 10 "This Mac runs macOS $version, which is too old for the software this needs." \
                "macOS 12 (Monterey) or newer is required."
    fi
    ok "macOS $version"
}

_check_arch() {
    local arch; arch="$(uname -m)"
    case "$arch" in
        arm64)  ok "Apple Silicon Mac" ;;
        x86_64) ok "Intel Mac" ;;
        *)      warn "Unfamiliar processor type ($arch) -- continuing, but this is untested" ;;
    esac
}

_check_python() {
    # Any Python 3.12 or 3.13 will do; the virtual environment is built from it. 3.14 is excluded
    # because the locked dependency set is not resolved for it (pyproject: >=3.12,<3.14).
    local candidate found=""
    for candidate in python3.13 python3.12 python3; do
        local path; path="$(command -v "$candidate" 2>/dev/null || true)"
        [[ -n "$path" ]] || continue
        local ver; ver="$("$path" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
        case "$ver" in
            3.12|3.13) found="$path"; PYTHON_BOOTSTRAP="$path"; ok "Python $ver"; break ;;
            *) log "rejected $path (Python ${ver:-unknown})" ;;
        esac
    done
    if [[ -z "$found" ]]; then
        NEED_PYTHON=1
        warn "Python is not installed yet -- it will be installed for you"
        return 0
    fi
    export PYTHON_BOOTSTRAP
}

# Docker asks for 4 GB of RAM, and a Linux VM plus PostgreSQL plus MinIO on an old Mac with less
# than that will thrash rather than fail cleanly -- which is much harder for an operator to report.
_check_memory() {
    local bytes gb
    bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
    gb=$(( bytes / 1073741824 ))
    if (( gb == 0 )); then
        warn "Could not measure memory -- continuing"
        return 0
    fi
    if (( gb < 4 )); then
        die 10 "This Mac has ${gb} GB of memory, and at least 4 GB is needed." \
                "" \
                "The database and the collection software cannot run reliably in less." \
                "This is a limit of the computer, not something you can change."
    fi
    if (( gb < 8 )); then
        warn "Memory: ${gb} GB -- enough, but it will be slow"
    else
        ok "Memory: ${gb} GB"
    fi
}

_check_disk() {
    local free_gb needed=$MIN_FREE_GB
    # Docker Desktop is a 640 MB download that unpacks to roughly 2.5 GB; Python is small but not
    # free. Asking for the full amount up front beats running out three quarters of the way in.
    (( NEED_DOCKER )) && needed=$(( needed + 5 ))
    (( NEED_PYTHON )) && needed=$(( needed + 1 ))

    free_gb="$(df -g "$REPO_ROOT" | awk 'NR==2 {print $4}')"
    if [[ ! "$free_gb" =~ ^[0-9]+$ ]]; then
        warn "Could not measure free disk space -- continuing"
        return 0
    fi
    if (( free_gb < needed )); then
        die 10 "This Mac has only ${free_gb} GB of free disk space, and ${needed} GB is needed." \
                "" \
                "That covers the database, the software that has to be installed, the documents" \
                "collected, and the result file." \
                "" \
                "Please empty the Trash or delete some large files, then try again."
    fi
    ok "Disk space: ${free_gb} GB free"
}

_check_writable() {
    local dir
    for dir in "$REPO_ROOT" "$REPO_ROOT/logs" "$HOME/Desktop"; do
        mkdir -p "$dir" 2>/dev/null || true
        if [[ ! -w "$dir" ]]; then
            die 10 "This tool cannot write to: $dir" \
                    "" \
                    "This usually means the folder was opened from a disk image or a read-only place." \
                    "Please drag the Aedifex folder to your Desktop and try again from there."
        fi
    done
    ok "Folders are writable"
}

_check_network() {
    # Reachability only. This does not fetch anything and does not touch the acquisition path; it
    # exists so an operator with no internet is told that, rather than watching a crawl time out.
    if run_logged curl --silent --show-error --head --max-time 20 "https://${REACHABILITY_HOST}/"; then
        ok "Internet connection works"
        return 0
    fi
    die 10 "This Mac cannot reach the internet, or ${REACHABILITY_HOST} is down." \
            "" \
            "Please check the Wi-Fi connection and try again." \
            "If other websites work in Safari, the portal itself may be temporarily unavailable;" \
            "in that case just try again later."
}

_check_container_runtime() {
    # Presence only. Starting it is stage 4's job -- this stage changes nothing.
    if command -v docker >/dev/null 2>&1; then
        ok "Docker is installed"
        return 0
    fi
    if command -v colima >/dev/null 2>&1; then
        ok "Colima is installed"
        return 0
    fi
    NEED_DOCKER=1
    warn "Docker is not installed yet -- it will be installed for you"
    return 0
}
