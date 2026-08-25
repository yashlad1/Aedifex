#!/usr/bin/env bash
# Stage 1b -- install what is missing.
#
# Only two things: Python and a container runtime. Both come from their vendor's own signed,
# notarized installer, downloaded over TLS and verified before anything is run:
#
#   Python           python.org .pkg   Developer ID Installer: Python Software Foundation
#   Docker Desktop   docker.com .dmg   Developer ID Application: Docker Inc
#
# Homebrew is deliberately not used, and the reason is specific to Intel Macs rather than a
# preference. `brew install docker` installs only the CLI client -- macOS has no native Docker
# daemon, so containers need a Linux VM and the client alone cannot start one. Getting a daemon
# through Homebrew means colima, which means lima, and Homebrew's own signed .pkg installs to
# /opt/homebrew on every architecture while Intel bottles are built for /usr/local. An Intel
# Homebrew at that prefix builds from source, which for qemu on an old Mac is hours. That .pkg also
# refuses outright when Xcode Command Line Tools are absent, and the curl-to-bash installer that
# would fix the prefix cannot be signature-verified at all.
#
# Two rules hold throughout:
#
#   Nothing is installed without the operator being told, in plain words, what and why.
#   The administrator password is typed by the operator into macOS's own prompt. There is no
#   attempt to capture, store, cache beyond sudo's own timeout, or work around it.

readonly PYTHON_VERSION="3.13.9"
readonly PYTHON_PKG_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-macos11.pkg"
# Read from the real artifacts rather than guessed: `pkgutil --check-signature` on the python.org
# package, and `codesign -dv` on an installed Docker.app.
readonly PYTHON_TEAM_ID="BMM5U3QVKW"
readonly DOCKER_TEAM_ID="9BNSXJN65R"

INSTALL_TMP=""

install_prerequisites() {
    if (( NEED_PYTHON == 0 && NEED_DOCKER == 0 )); then
        return 0
    fi

    _confirm_installation || return 1
    _obtain_admin_rights || return 1

    INSTALL_TMP="$(mktemp -d "${TMPDIR:-/tmp}/aedifex-install.XXXXXX")"
    trap _cleanup_installation RETURN

    (( NEED_PYTHON )) && { _install_python || return 1; }
    (( NEED_DOCKER )) && { _install_docker || return 1; }

    return 0
}

_cleanup_installation() {
    [[ -n "$INSTALL_TMP" ]] || return 0
    rm -rf "$INSTALL_TMP"
    INSTALL_TMP=""
}

_confirm_installation() {
    # A run driven by a script rather than a person must not silently install system software.
    if [[ ! -t 0 ]]; then
        die 20 "Some required software is missing, and this run cannot ask for permission to" \
                "install it because it was not started from a Terminal window." \
                "" \
                "Double-click 'Run Aedifex.command' instead."
    fi

    say ""
    say "-------------------------------------------------"
    say "  FIRST-TIME SETUP"
    say "-------------------------------------------------"
    say ""
    say "  This Mac is missing some software. This needs to be installed once,"
    say "  and never again."
    say ""
    (( NEED_PYTHON )) && say "    - Python ${PYTHON_VERSION}, from python.org  (about 70 MB)"
    (( NEED_DOCKER )) && say "    - Docker Desktop, from docker.com     (about 640 MB)"
    say ""
    say "  Both are downloaded from the companies that make them, and this"
    say "  tool checks Apple's signature on each one before installing it."
    (( NEED_DOCKER )) && say "  Installing Docker also accepts its licence for personal use."
    say ""
    say "  macOS will ask for this Mac's password. That is normal and expected:"
    say "  installing software always requires it. Type the same password you"
    say "  use to log in to this Mac. It is not sent anywhere."
    say ""
    say "  This will take 20 to 40 minutes depending on the internet speed."
    say ""
    printf '  Press Enter to start, or close this window to stop.'
    read -r _ || true
    printf '\n'
    log "operator confirmed installation (python=${NEED_PYTHON} docker=${NEED_DOCKER})"
    return 0
}

_obtain_admin_rights() {
    step "Asking macOS for permission to install..."
    say "  Please type this Mac's password when asked, then press Enter."
    say "  Nothing appears on screen while you type. That is normal."
    say ""
    # `sudo -v` prompts once and refreshes the timestamp, so the installs below do not each prompt
    # again. Deliberately interactive: nothing here reads, stores or passes a password.
    if sudo -v; then
        ok "Permission granted"
        return 0
    fi
    die 20 "Could not get permission to install software on this Mac." \
            "" \
            "This happens if the password was mistyped three times, or if this account is not" \
            "an administrator of this Mac." \
            "" \
            "Please ask whoever set up this Mac to run it once."
}

# --- downloads and verification ---------------------------------------------

# Progress is shown on the console on purpose. A silent twenty-minute download of 640 MB is
# indistinguishable from a hang, and an operator who cannot tell those apart force-quits.
_download() {
    local url="$1" destination="$2" label="$3"
    say "  Downloading ${label}..."
    log "download $url -> $destination"
    if curl --location --fail --show-error --progress-bar \
            --connect-timeout 30 --retry 3 --retry-delay 5 \
            --output "$destination" "$url"; then
        log "downloaded $(wc -c <"$destination") bytes"
        return 0
    fi
    die 20 "Could not download ${label}." \
            "" \
            "This is almost always the internet connection. Please check the Wi-Fi and" \
            "double-click 'Run Aedifex.command' again -- it will carry on from here."
}

# Two independent checks, and both must pass. Gatekeeper (`spctl`) proves Apple notarized the
# artifact; the team identifier proves *which* developer signed it. Notarization alone would accept
# any notarized software, so a compromised download that was itself notarized would pass.
_verify_signature() {
    local path="$1" expected_team="$2" label="$3" assess_type="$4"
    log "verifying $path"

    local report
    if ! report="$(pkgutil --check-signature "$path" 2>&1)" \
       && [[ "$assess_type" == "install" ]]; then
        log "$report"
        _refuse_unsigned "$label" "it is not signed at all"
    fi

    if ! spctl --assess --type "$assess_type" -vv "$path" >>"$LOG_FILE" 2>&1; then
        _refuse_unsigned "$label" "macOS did not accept its signature"
    fi

    local authority
    authority="$(spctl --assess --type "$assess_type" -vv "$path" 2>&1 | grep '^origin=' || true)"
    log "authority: ${authority:-unknown}"
    if [[ "$authority" != *"$expected_team"* ]]; then
        _refuse_unsigned "$label" \
            "it was signed by somebody unexpected (expected ${expected_team})"
    fi

    ok "${label}: signature verified"
}

_refuse_unsigned() {
    die 20 "Refused to install ${1}, because ${2}." \
            "" \
            "Nothing was installed. This is a safety check working as intended: it means the" \
            "downloaded file is not the one the manufacturer published." \
            "" \
            "Please send the log file below and do not try again until told to."
}

# --- Python ------------------------------------------------------------------

_install_python() {
    step "Installing Python..."
    local pkg="$INSTALL_TMP/python.pkg"
    _download "$PYTHON_PKG_URL" "$pkg" "Python ${PYTHON_VERSION} (about 70 MB)"
    _verify_signature "$pkg" "$PYTHON_TEAM_ID" "Python" "install"

    say "  Installing..."
    if ! run_logged sudo installer -pkg "$pkg" -target /; then
        die 20 "Could not install Python." \
                "" \
                "The download was genuine but the installation did not finish." \
                "Restarting this Mac and trying again usually works."
    fi

    # The pkg puts the interpreter in a versioned framework and symlinks it into /usr/local/bin.
    hash -r 2>/dev/null || true
    local candidate
    for candidate in \
        "/usr/local/bin/python3.13" \
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13"; do
        if [[ -x "$candidate" ]]; then
            PYTHON_BOOTSTRAP="$candidate"
            export PYTHON_BOOTSTRAP
            NEED_PYTHON=0
            ok "Python installed"
            return 0
        fi
    done
    die 20 "Python was installed but cannot be found afterwards." \
            "Please send the log file below."
}

# --- Docker ------------------------------------------------------------------

# Docker's own policy is "the current and two previous major macOS releases", so what counts as
# supported moves every autumn rather than sitting at a fixed number. Warned rather than refused:
# an unsupported-but-working install is a better outcome than a tool that declines to try, and if
# it does fail the operator needs the version named as the likely cause instead of a generic error.
_warn_if_macos_unsupported() {
    local major; major="$(sw_vers -productVersion | cut -d. -f1)"
    [[ "$major" =~ ^[0-9]+$ ]] || return 0
    if (( major < 14 )); then
        warn "macOS ${major} is older than Docker now supports -- the install may not work"
        log "macOS major $major is outside Docker's current/-2 support window"
        DOCKER_MACOS_RISK=1
    fi
}
DOCKER_MACOS_RISK=0

_install_docker() {
    step "Installing Docker..."
    local arch dmg_url dmg="$INSTALL_TMP/Docker.dmg" mount="$INSTALL_TMP/docker-mount"
    arch="$(uname -m)"
    case "$arch" in
        arm64)  dmg_url="https://desktop.docker.com/mac/main/arm64/Docker.dmg" ;;
        x86_64) dmg_url="https://desktop.docker.com/mac/main/amd64/Docker.dmg" ;;
        *)      die 20 "Docker cannot be installed on this processor type ($arch)." ;;
    esac

    _warn_if_macos_unsupported
    _download "$dmg_url" "$dmg" "Docker Desktop (about 640 MB)"

    say "  Opening the download..."
    mkdir -p "$mount"
    if ! run_logged hdiutil attach -nobrowse -readonly -mountpoint "$mount" "$dmg"; then
        die 20 "Could not open the Docker download." \
                "The file may have arrived incomplete. Please try again."
    fi

    local app="$mount/Docker.app"
    if [[ ! -d "$app" ]]; then
        run_logged hdiutil detach "$mount" || true
        die 20 "The Docker download did not contain what was expected." \
                "Please send the log file below."
    fi

    _verify_signature "$app" "$DOCKER_TEAM_ID" "Docker Desktop" "execute"

    say "  Installing Docker. This is the slow part..."
    # ditto rather than cp: it preserves the bundle's extended attributes and its code signature.
    if ! run_logged sudo ditto "$app" "/Applications/Docker.app"; then
        run_logged hdiutil detach "$mount" || true
        die 20 "Could not install Docker." \
                "" \
                "This usually means the disk is full. Please empty the Trash and try again."
    fi
    run_logged hdiutil detach "$mount" || true

    # Docker's own documented non-interactive setup: installs the privileged helper and the
    # /usr/local/bin symlinks, and records licence acceptance so first launch shows no dialog for
    # the operator to puzzle over.
    say "  Finishing setup..."
    if ! run_logged sudo /Applications/Docker.app/Contents/MacOS/install --accept-license; then
        if (( DOCKER_MACOS_RISK )); then
            die 20 "Docker could not finish setting itself up, and the most likely reason is that" \
                    "this Mac's version of macOS is older than Docker now supports." \
                    "" \
                    "This is not something you can fix. Please send the log file below."
        fi
        die 20 "Docker was installed but could not finish setting itself up." \
                "" \
                "Please open Docker from the Applications folder once, accept anything it asks," \
                "then double-click 'Run Aedifex.command' again."
    fi

    hash -r 2>/dev/null || true
    NEED_DOCKER=0
    ok "Docker installed"
}
