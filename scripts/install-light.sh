#!/usr/bin/env bash
# Print Buddy light install: Raspberry Pi 4/5 (64-bit Raspberry Pi OS) or Debian/Ubuntu. No Docker.
#
#   curl -fsSL https://raw.githubusercontent.com/catduckgnaf/print-buddy/main/scripts/install-light.sh | bash
#   curl -fsSL .../install-light.sh | bash -s -- --ref 2.1.2      # a pinned release
#
# Options:
#   --ref REF        Git branch or tag to install (default: main)
#   --dir DIR        Where the code lives (default: ~/print-buddy)
#   --answers FILE   Answer the setup questions from a file (unattended install)
#   --yes            Take the defaults for anything not answered
#   --dry-run        Ask the questions and show every step; change nothing
#   --uninstall      Stop and remove the bot services (keeps config and data)
#   --purge          With --uninstall: also delete the code folder and the data folder
#
# Steps: apt packages (python3-venv, flatpak, xvfb, git, unzip), the Flathub remote, the code, a Python
# virtual environment, then the setup wizard (python -m print_buddy.setup_wizard), which asks about
# your printer and installs the slicer and services you pick. Safe to run again: nothing that exists is
# overwritten, and config/local.yaml only gains the settings it is missing (after you see a diff).
set -euo pipefail

# Everything runs inside main so `curl | bash` reads the whole script before any command can touch stdin.
main() {
REF=main
DIR=${PRINT_BUDDY_DIR:-$HOME/print-buddy}
DRY=0 YES=0 UNINSTALL=0 PURGE=0 ANSWERS=
REPO_URL=https://github.com/catduckgnaf/print-buddy.git
PACKAGES=(python3-venv python3-pip flatpak xvfb git unzip curl)

usage() { sed -n '2,19p' "${BASH_SOURCE[0]}" 2>/dev/null | sed 's/^# \{0,1\}//' || true; }
say() { printf '%s\n' "$*"; }
fail() { printf 'install-light: %s\n' "$*" >&2; exit 1; }
run() {  # run CMD...: print it, then run it unless this is a dry run
    say "+ $*"
    [ "$DRY" = 1 ] || "$@"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --ref) shift; REF=${1:?--ref needs a value} ;;
        --dir) shift; DIR=${1:?--dir needs a value} ;;
        --answers) shift; ANSWERS=$(readlink -f "${1:?--answers needs a file}") ;;
        --yes) YES=1 ;;
        --dry-run) DRY=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --purge) PURGE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) fail "unknown option: $1 (see --help)" ;;
    esac
    shift
done
[ "$PURGE" = 0 ] || [ "$UNINSTALL" = 1 ] || fail "--purge only works with --uninstall"
[ -z "$ANSWERS" ] || [ -r "$ANSWERS" ] || fail "cannot read the answers file"

UNITS=(print-buddy-bot.service print-buddy-listener.service)
UNIT_DIR=${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}

if [ "$UNINSTALL" = 1 ]; then
    if command -v systemctl >/dev/null 2>&1 && [ "${NO_SYSTEMCTL:-0}" != 1 ]; then
        run systemctl --user disable --now "${UNITS[@]}" || true
    fi
    for unit in "${UNITS[@]}"; do
        [ -e "$UNIT_DIR/$unit" ] && run rm -f "$UNIT_DIR/$unit"
    done
    if [ "$PURGE" = 1 ]; then
        data=
        [ -x "$DIR/.venv/bin/python" ] && data=$(cd "$DIR" && .venv/bin/python -m print_buddy.settings get paths.hermes_home 2>/dev/null || true)
        case "$data" in
            */.hermes/profiles/*) say "Keeping $data: it is a Hermes profile. Remove it with: hermes profile delete $(basename "$data")" ;;
            "$HOME"/?*) run rm -rf "$data" ;;
        esac
        [ -d "$DIR" ] && run rm -rf "$DIR"
        say "Flatpak slicers stay installed. Remove them with: flatpak uninstall com.orcaslicer.OrcaSlicer com.bambulab.BambuStudio"
    else
        say "Services removed. Code in $DIR and your config and data are kept (add --purge to delete them)."
    fi
    exit 0
fi

# 1. Check the machine.
[ "$(id -u)" != 0 ] || fail "run this as your normal user, not root (it uses sudo only for apt)"
[ -r /etc/os-release ] && . /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
    *" debian "*|*" ubuntu "*|*" raspbian "*) ;;
    *) fail "this installer supports Raspberry Pi OS, Debian and Ubuntu (found ${PRETTY_NAME:-unknown})" ;;
esac
arch=$(uname -m)
case "$arch" in
    aarch64|arm64|x86_64|amd64) ;;
    armv7l|armv6l) fail "32-bit Raspberry Pi OS is not supported: OrcaSlicer and Bambu Studio need the 64-bit OS" ;;
    *) fail "unsupported CPU: $arch (needs arm64 or x86_64)" ;;
esac
say "Print Buddy light install on ${PRETTY_NAME:-Linux} ($arch), ref $REF, folder $DIR"
[ "$DRY" = 0 ] || say "Dry run: commands are shown, nothing is changed."

# 2. System packages, only the missing ones.
missing=()
for pkg in "${PACKAGES[@]}"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed' || missing+=("$pkg")
done
if [ ${#missing[@]} -gt 0 ]; then
    run sudo apt-get update -q
    run sudo apt-get install -y -q "${missing[@]}"
fi
if ! flatpak remotes --columns=name 2>/dev/null | grep -qx flathub; then
    run flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
fi

# 3. The code.
if [ -e "$DIR/.git" ]; then
    if [ -n "$(git -C "$DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
        say "$DIR has local changes; leaving the code as it is."
    else
        run git -C "$DIR" fetch -q --tags origin "$REF"
        run git -C "$DIR" checkout -q FETCH_HEAD
    fi
elif [ -e "$DIR" ]; then
    fail "$DIR exists and is not a Print Buddy checkout; pick another folder with --dir"
else
    run git clone -q --depth 1 --branch "$REF" "$REPO_URL" "$DIR"
fi

# 4. Python environment.
[ -x "$DIR/.venv/bin/python" ] || run python3 -m venv "$DIR/.venv"
run "$DIR/.venv/bin/python" -m pip install -q --upgrade pip
run "$DIR/.venv/bin/python" -m pip install -q -r "$DIR/requirements.txt"

# 5. Questions, config, slicer, services.
args=()
[ -z "$ANSWERS" ] || args+=(--answers "$ANSWERS")
[ "$YES" = 0 ] || args+=(--yes)
[ "$DRY" = 0 ] || args+=(--dry-run)
if [ "$DRY" = 1 ] && [ ! -x "$DIR/.venv/bin/python" ]; then
    say "+ $DIR/.venv/bin/python -m print_buddy.setup_wizard ${args[*]}"
    exit 0
fi
cd "$DIR"
exec "$DIR/.venv/bin/python" -m print_buddy.setup_wizard --python "$DIR/.venv/bin/python" "${args[@]}"
}

main "$@"
