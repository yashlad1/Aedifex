#!/usr/bin/env bash
# Console output and the run log.
#
# Two audiences, one source of truth. The operator sees short status lines and never sees a
# traceback, a Docker log or a pip resolution; all of that goes to the run log, which is the file
# they are asked to send back. Every helper here writes to both, so a line can never appear on the
# console without also appearing in the log.

# Set by run.sh before anything else is sourced.
: "${LOG_FILE:?logging.sh requires LOG_FILE}"

if [[ -t 1 ]]; then
    C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
    C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_OFF=""
fi

_stamp() { date "+%Y-%m-%d %H:%M:%S"; }

# Log only. Use for anything an operator should not have to read.
log() { printf '[%s] %s\n' "$(_stamp)" "$*" >>"$LOG_FILE"; }

# Console and log.
say() { printf '%s\n' "$*"; log "$*"; }

banner() {
    say ""
    say "================================================="
    say "  $*"
    say "================================================="
    say ""
}

ok()   { printf '  %s✓%s %s\n' "$C_OK" "$C_OFF" "$*";   log "OK      $*"; }
warn() { printf '  %s!%s %s\n' "$C_WARN" "$C_OFF" "$*"; log "WARNING $*"; }
bad()  { printf '  %s✗%s %s\n' "$C_ERR" "$C_OFF" "$*";  log "FAILED  $*"; }
note() { printf '  %s%s%s\n' "$C_DIM" "$*" "$C_OFF";    log "NOTE    $*"; }

step() { say ""; say "$*"; }

# Stop the run. $1 is the exit code, the rest is the explanation shown to the operator.
#
# The explanation is written for someone who cannot read a stack trace: what failed, why, and the
# one file to send. Nothing that ran before this point is undone -- the pipeline's own guarantees
# make a partial run safe to repeat, so "nothing has been broken" is a statement of fact and not
# reassurance.
die() {
    local code="$1"; shift
    # This is a *reported* failure, not an unexpected one. Releasing the EXIT trap stops run.sh
    # printing its "something went wrong that this tool did not expect" block underneath a message
    # that already explained the problem -- two contradictory endings is worse than either alone.
    trap - EXIT
    printf '\n'
    bad "FAILED"
    printf '\n'
    local line
    for line in "$@"; do
        if [[ -z "$line" ]]; then
            printf '\n'
        else
            printf '%s\n' "$line" | fold -s -w 76 | sed 's/^/  /'
        fi
        log "        $line"
    done
    printf '\n'
    printf '  Nothing has been broken. Running this again is safe.\n'
    printf '\n'
    printf '  Please send this file to Yash:\n'
    printf '    %s\n\n' "$LOG_FILE"
    log "EXIT $code"
    exit "$code"
}

# Run a command with all of its output captured to the log. Returns the command's status so the
# caller decides whether it is fatal; nothing here decides that on its own.
run_logged() {
    log "RUN     $*"
    # `status=$?` after a failed `if` reads the status of the *if statement*, which is 0 when the
    # condition was false and there is no else branch -- so an earlier version of this function
    # reported every failure as success, and `docker info` failing looked exactly like Docker
    # running. Capturing the status on the command itself is the only form that is correct.
    local status=0
    "$@" >>"$LOG_FILE" 2>&1 || status=$?
    if (( status == 0 )); then
        log "RUN OK  $*"
    else
        log "RUN ERR ($status) $*"
    fi
    return "$status"
}

# The last few lines of the log, for the operator to quote if they cannot send the file. Kept short
# on purpose: it is a hint for a human helping them, not a diagnosis.
log_tail() {
    printf '\n  Last lines of the log:\n'
    tail -n 8 "$LOG_FILE" | sed 's/^/    /'
}
