#!/usr/bin/env bash
# One-shot rename migration for an install made before the Print Bitch -> Print Buddy rename.
# Safe to run again; every step prints what it does.
#
#   scripts/migrate-names.sh [--dry-run] [--hermes-home DIR] [--archive DIR]
#                            [--systemd-dir DIR] [--config FILE]
#
# 1. Renames files and folders whose name contains print_bitch to print_buddy in the profile
#    state dir and in the archive dir. A target that already exists is skipped.
# 2. Replaces PRINT_BITCH_ with PRINT_BUDDY_ in config/local.toml, the profile .env and
#    config.yaml, and the listener systemd unit and drop-ins. Each edited file is first copied
#    to <file>.pre-rename.
# 3. Prints the steps that have to be done by hand on the printer.
set -eu

REPO=$(cd "$(dirname "$0")/.." && pwd)
DRY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        --hermes-home) shift; HERMES_HOME=${1:?--hermes-home needs a directory} ;;
        --archive) shift; ARCHIVE=${1:?--archive needs a directory} ;;
        --systemd-dir) shift; SYSTEMD_USER_DIR=${1:?--systemd-dir needs a directory} ;;
        --config) shift; LOCAL_CONFIG=${1:?--config needs a file} ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

setting() {  # setting SECTION.KEY
    (cd "$REPO" && python3 -m print_buddy.settings get "$1" 2>/dev/null) || true
}
HERMES_HOME=${HERMES_HOME:-$(setting paths.hermes_home)}
HERMES_HOME=${HERMES_HOME:-$HOME/.hermes/profiles/3dprinting}
ARCHIVE=${ARCHIVE:-$(setting paths.archive)}
SYSTEMD_USER_DIR=${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}
LOCAL_CONFIG=${LOCAL_CONFIG:-${PRINT_BUDDY_CONFIG:-$REPO/config/local.toml}}

say() { printf '%s\n' "$*"; }
act() { if [ "$DRY" = 1 ]; then say "would: $*"; else say "$*"; fi; }

say "profile:  $HERMES_HOME"
say "archive:  ${ARCHIVE:-(not set)}"
say "config:   $LOCAL_CONFIG"
say "systemd:  $SYSTEMD_USER_DIR"
[ "$DRY" = 1 ] && say "(dry run: nothing will be changed)"

# 1. Rename state and archive entries, deepest first so a folder is renamed after its contents.
rename_tree() {  # rename_tree DIR
    local root="$1" path dir base new found=0
    if [ -z "$root" ] || [ ! -d "$root" ]; then say "skipped $root (no such directory)"; return 0; fi
    while IFS= read -r -d '' path; do
        found=1
        dir=$(dirname "$path"); base=$(basename "$path"); new="$dir/${base//print_bitch/print_buddy}"
        if [ -e "$new" ] || [ -L "$new" ]; then say "skipped $path (target $new exists)"; continue; fi
        act "rename $path -> $new"
        [ "$DRY" = 1 ] || mv "$path" "$new"
    done < <(find "$root" -depth -name '*print_bitch*' -print0)
    [ "$found" = 1 ] || say "ok      $root (nothing to rename)"
}
rename_tree "$HERMES_HOME/state"
rename_tree "$ARCHIVE"

# 2. Environment variable names inside config files and units.
edit_file() {  # edit_file FILE
    local f="$1"
    if [ ! -f "$f" ]; then say "skipped $f (not found)"; return 0; fi
    if ! grep -q 'PRINT_BITCH_' "$f"; then say "ok      $f (no old names)"; return 0; fi
    if [ -e "$f.pre-rename" ]; then say "skipped $f (backup $f.pre-rename already exists; check it by hand)"; return 0; fi
    act "backup $f -> $f.pre-rename"
    [ "$DRY" = 1 ] || cp -p "$f" "$f.pre-rename"
    act "edit   $f: PRINT_BITCH_ -> PRINT_BUDDY_ ($(grep -c 'PRINT_BITCH_' "$f") lines)"
    [ "$DRY" = 1 ] || sed -i 's/PRINT_BITCH_/PRINT_BUDDY_/g' "$f"
}
edit_file "$LOCAL_CONFIG"
edit_file "$HERMES_HOME/.env"
edit_file "$HERMES_HOME/config.yaml"
for f in "$SYSTEMD_USER_DIR"/hermes-3dprinting-moonraker-listener.service \
         "$SYSTEMD_USER_DIR"/hermes-3dprinting-moonraker-listener.service.d/*.conf; do
    case "$f" in *'*'*) continue ;; esac
    edit_file "$f"
done

# 3. Printer side.
cat <<'TXT'

Printer steps (cannot be done from here; do them while the printer is idle). Details in
docs/RENAME-MIGRATION.md.
  1. Printer console: DISABLE_PLUGIN name=print-bitch
     (if that is not available, delete mod_data/plugins/print-bitch by hand)
  2. Printer console: ENABLE_PLUGIN name=print-buddy
  3. In mod_data/user.cfg rename [gcode_macro _PRINT_BITCH_VARS] to [gcode_macro _PRINT_BUDDY_VARS].
  4. In moonraker.conf replace [update_manager print-bitch] with [update_manager print-buddy]
     and set its path to .../mod_data/plugins/print-buddy.
  5. FIRMWARE_RESTART, then run PRINT_BUDDY SLOT=1 to check.
Then on this machine, restart the listener:
  systemctl --user daemon-reload && systemctl --user restart hermes-3dprinting-moonraker-listener.service
TXT
