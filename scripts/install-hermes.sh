#!/usr/bin/env bash
# Install the Print Buddy Hermes profile by symlink. Safe to run again.
#
#   scripts/install-hermes.sh [--dry-run] [--hermes-home DIR] [--python PATH]
#
# Env: HERMES_HOME, PYTHON, SYSTEMD_USER_DIR (default ~/.config/systemd/user),
#      PRINT_BUDDY_OVERLAY (default config/overlay), NO_SYSTEMCTL=1 to skip daemon-reload.
#      Template values: LLM_PROVIDER LLM_MODEL LLM_BASE_URL TIMEZONE DISCORD_CHANNEL_ID DISPLAY_NAME.
#
# Code folders are symlinked to this checkout. Templates are rendered only when the target is
# missing, so your edited AGENTS.md, SOUL.md and config.yaml are never overwritten. Files under
# config/overlay/ are then copied over the profile. Anything replaced is moved to <name>.bak-<time>.
set -eu

REPO=$(cd "$(dirname "$0")/.." && pwd)
DRY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        --hermes-home) shift; HERMES_HOME=${1:?--hermes-home needs a directory} ;;
        --python) shift; PYTHON=${1:?--python needs a path} ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ -z "${HERMES_HOME:-}" ]; then
    HERMES_HOME=$(cd "$REPO" && python3 -m print_buddy.settings get paths.hermes_home 2>/dev/null) || HERMES_HOME=""
    [ -n "$HERMES_HOME" ] || HERMES_HOME="$HOME/.hermes/profiles/3dprinting"
fi
if [ -z "${PYTHON:-}" ]; then
    if [ -x "$HOME/.hermes/hermes-agent/venv/bin/python" ]; then
        PYTHON="$HOME/.hermes/hermes-agent/venv/bin/python"
    else
        PYTHON=$(command -v python3)
    fi
fi
SYSTEMD_USER_DIR=${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}
OVERLAY=${PRINT_BUDDY_OVERLAY:-$REPO/config/overlay}
STAMP=$(date +%Y%m%d-%H%M%S)
LAST_CHANGED=0

say() { printf '%s\n' "$*"; }
act() { if [ "$DRY" = 1 ]; then say "would: $*"; else say "$*"; fi; }

backup_path() {  # print a free <path>.bak-<stamp> name
    local b="$1.bak-$STAMP" n=1
    while [ -e "$b" ] || [ -L "$b" ]; do b="$1.bak-$STAMP-$n"; n=$((n + 1)); done
    printf '%s' "$b"
}

backup() {  # move a path aside
    local b; b=$(backup_path "$1")
    act "backup $1 -> $b"
    [ "$DRY" = 1 ] || mv "$1" "$b"
}

ensure_dir() {
    [ -d "$1" ] && return 0
    act "mkdir $1"
    [ "$DRY" = 1 ] || mkdir -p "$1"
}

link() {  # link SRC DST: DST becomes a symlink to SRC
    local src="$1" dst="$2"
    if [ -L "$dst" ]; then
        if [ "$(readlink "$dst")" = "$src" ]; then say "ok      $dst -> $src"; return 0; fi
        act "relink $dst -> $src"
        [ "$DRY" = 1 ] || ln -sfn "$src" "$dst"
        return 0
    fi
    ensure_dir "$(dirname "$dst")"
    if [ -e "$dst" ]; then backup "$dst"; fi
    act "link   $dst -> $src"
    [ "$DRY" = 1 ] || ln -s "$src" "$dst"
}

render() {  # render SRC DST: substitute ${NAME} and {{NAME}} placeholders
    LLM_PROVIDER=${LLM_PROVIDER:-} LLM_MODEL=${LLM_MODEL:-} LLM_BASE_URL=${LLM_BASE_URL:-} \
    DISCORD_CHANNEL_ID=${DISCORD_CHANNEL_ID:-} \
    TIMEZONE=${TIMEZONE:-${TZ:-UTC}} DISPLAY_NAME=${DISPLAY_NAME:-3D Printing} \
    PROFILE_DIR="$HERMES_HOME" HERMES_HOME="$HERMES_HOME" REPO="$REPO" PYTHON="$PYTHON" \
    python3 - "$1" <<'PY'
import os, re, sys
text = open(sys.argv[1]).read()
def fill(match):
    name = match.group(1) or match.group(2)
    return os.environ.get(name) or match.group(0)
sys.stdout.write(re.sub(r"\$\{(\w+)\}|\{\{(\w+)\}\}", fill, text))
PY
}

write_rendered() {  # write_rendered SRC DST MODE: MODE=keep leaves an existing DST alone, MODE=sync replaces it
    local src="$1" dst="$2" mode="$3" tmp
    tmp=$(mktemp)
    render "$src" > "$tmp"
    if [ -e "$dst" ] || [ -L "$dst" ]; then
        if [ "$mode" = keep ]; then say "skipped $dst (exists, left as is)"; rm -f "$tmp"; return 0; fi
        if [ ! -L "$dst" ] && cmp -s "$tmp" "$dst"; then say "ok      $dst"; rm -f "$tmp"; return 0; fi
        backup "$dst"
    fi
    ensure_dir "$(dirname "$dst")"
    act "render $dst"
    LAST_CHANGED=1
    [ "$DRY" = 1 ] || cp "$tmp" "$dst"
    unfilled=$(grep -oE '\$\{[A-Z_]+\}|\{\{[A-Z_]+\}\}' "$tmp" 2>/dev/null | sort -u | tr '\n' ' ' || true)
    [ -z "$unfilled" ] || say "note    $dst has unfilled placeholders: $unfilled(set them in the environment or in config/overlay)"
    rm -f "$tmp"
}

copy_if_missing() {  # copy_if_missing SRC DST
    if [ -e "$2" ] || [ -L "$2" ]; then say "skipped $2 (exists, left as is)"; return 0; fi
    ensure_dir "$(dirname "$2")"
    act "copy   $2"
    [ "$DRY" = 1 ] || cp "$1" "$2"
}

copy_over() {  # copy_over SRC DST: overlay copy, replaces a different file after backing it up
    local src="$1" dst="$2"
    if [ -f "$dst" ] && [ ! -L "$dst" ] && cmp -s "$src" "$dst"; then say "ok      $dst (overlay)"; return 0; fi
    ensure_dir "$(dirname "$dst")"
    if [ -e "$dst" ] || [ -L "$dst" ]; then backup "$dst"; fi
    act "overlay $dst"
    LAST_CHANGED=1
    [ "$DRY" = 1 ] || cp "$src" "$dst"
}

say "repo:        $REPO"
say "hermes home: $HERMES_HOME"
say "python:      $PYTHON"
[ "$DRY" = 1 ] && say "(dry run: nothing will be changed)"

# 1. Profile directory and code symlinks.
ensure_dir "$HERMES_HOME"
link "$REPO/hermes/skills/klipper-3d-printing" "$HERMES_HOME/skills/smart-home/klipper-3d-printing"
link "$REPO/hermes/skills/ad5x-multicolor-slicing" "$HERMES_HOME/skills/smart-home/ad5x-multicolor-slicing"
link "$REPO/plugins/print-feedback" "$HERMES_HOME/plugins/print-feedback"
link "$REPO/hermes/profile/docs" "$HERMES_HOME/docs"

# 2. Templates: rendered or copied only when the target is missing.
P="$REPO/hermes/profile"
write_rendered "$P/config.yaml.template" "$HERMES_HOME/config.yaml" keep
write_rendered "$P/profile.yaml.template" "$HERMES_HOME/profile.yaml" keep
for f in AGENTS.md SOUL.md MEMORY.md status_phrases.yaml locales/en.yaml cron/jobs.json; do
    copy_if_missing "$P/$f" "$HERMES_HOME/$f"
done

# 3. Local overlay (gitignored): files replace the profile files at the same relative path.
overlay_units=""
if [ -d "$OVERLAY" ]; then
    while IFS= read -r f; do
        rel=${f#"$OVERLAY"/}
        case "$rel" in
            README.md|.gitignore) continue ;;
            systemd/*) overlay_units="$overlay_units $rel"; continue ;;
        esac
        copy_over "$f" "$HERMES_HOME/$rel"
    done < <(find "$OVERLAY" -type f | sort)
else
    say "no overlay folder at $OVERLAY"
fi

# 4. systemd user units. Managed files are re-rendered when they differ.
LAST_CHANGED=0
for unit in "$REPO"/hermes/systemd/*.service.template; do
    [ -e "$unit" ] || continue
    name=$(basename "$unit" .template)
    dst="$SYSTEMD_USER_DIR/$name"
    write_rendered "$unit" "$dst" sync
    for dropin in "$REPO/hermes/systemd/$name.d/"*.conf.template; do
        [ -e "$dropin" ] || continue
        write_rendered "$dropin" "$SYSTEMD_USER_DIR/$name.d/$(basename "$dropin" .template)" sync
    done
done
# Overlay drop-ins: config/overlay/systemd/<unit>.service.d/*.conf, for personal Environment= lines.
for rel in $overlay_units; do
    copy_over "$OVERLAY/$rel" "$SYSTEMD_USER_DIR/${rel#systemd/}"
done

if [ "$LAST_CHANGED" = 1 ] && [ -z "${NO_SYSTEMCTL:-}" ] && command -v systemctl >/dev/null 2>&1; then
    act "systemctl --user daemon-reload"
    [ "$DRY" = 1 ] || systemctl --user daemon-reload || say "warning: daemon-reload failed"
fi

say "done. Enable the listener with: systemctl --user enable --now hermes-print-buddy-listener.service"
