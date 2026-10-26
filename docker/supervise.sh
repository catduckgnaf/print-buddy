#!/bin/bash
# Required child lifecycle; tini reaps orphans and forwards process-group signals.
set -euo pipefail
if [ "$#" -gt 0 ]; then exec "$@"; fi
children=()
cleanup() {
    trap '' TERM INT
    for pid in "${children[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
    for _ in {1..100}; do
        alive=false
        for pid in "${children[@]}"; do kill -0 "$pid" 2>/dev/null && alive=true; done
        if [ "$alive" = false ]; then break; fi
        sleep 0.1
    done
    for pid in "${children[@]}"; do kill -KILL "$pid" 2>/dev/null || true; done
    wait || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT
export SPOOLMAN_HOST="${SPOOLMAN_HOST:-127.0.0.1}"
export SPOOLMAN_PORT="${SPOOLMAN_PORT:-8000}"
export SPOOLMAN_DIR_DATA="${SPOOLMAN_DIR_DATA:-/data/spoolman}"
export SPOOLMAN_DIR_CONFIG="${SPOOLMAN_DIR_CONFIG:-/data/spoolman/config}"
export SPOOLMAN_DIR_LOGS="${SPOOLMAN_DIR_LOGS:-/data/spoolman/logs}"
export SPOOLMAN_DIR_BACKUPS="${SPOOLMAN_DIR_BACKUPS:-/data/spoolman/backups}"
export PRINT_BUDDY__SERVICES__SPOOLMAN_URL="${PRINT_BUDDY__SERVICES__SPOOLMAN_URL:-http://127.0.0.1:$SPOOLMAN_PORT}"
if [ "${PRINT_BUDDY_BUNDLED_SPOOLMAN:-true}" = true ]; then
    mkdir -p "$SPOOLMAN_DIR_DATA" "$SPOOLMAN_DIR_CONFIG" "$SPOOLMAN_DIR_LOGS" "$SPOOLMAN_DIR_BACKUPS"
    # Spoolman runs its migrations by spawning `alembic`, so its venv bin must lead PATH.
    (cd /opt/spoolman && PATH=/opt/spoolman/.venv/bin:$PATH exec .venv/bin/python -m uvicorn spoolman.main:app --host "$SPOOLMAN_HOST" --port "$SPOOLMAN_PORT") &
    children+=("$!")
    python3 - <<'PY'
import os, time, urllib.request
url = 'http://127.0.0.1:' + os.environ['SPOOLMAN_PORT'] + '/api/v1/health'
for attempt in range(90):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            if response.status == 200:
                break
    except OSError:
        pass
    time.sleep(1)
else:
    raise SystemExit('Bundled Spoolman failed readiness')
PY
else
    case "$PRINT_BUDDY__SERVICES__SPOOLMAN_URL" in
        http://127.0.0.1:*|http://localhost:*) echo 'External Spoolman URL required when bundled API is disabled' >&2; exit 2;;
    esac
fi
# go2rtc (#246 stage 1) normalises the camera source on loopback for
# in-container timelapse capture. A WITH_GO2RTC=false build has no binary
# (so the whole block is skipped there); the published image includes it. It
# runs only when [timelapse] capture_enabled is set. The gate resolves the
# effective configuration (print_buddy.go2rtc), never an environment
# guess: 0 = start it, 3 = not started (capture disabled, or no camera
# source configured — the feature degrades off), anything else = the
# configuration could not be resolved; stop instead of guessing.
go2rtc_bin="${GO2RTC_BIN:-/usr/local/bin/go2rtc}"
if [ -x "$go2rtc_bin" ]; then
    go2rtc_gate=0
    python3 -m print_buddy.go2rtc || go2rtc_gate=$?
    if [ "$go2rtc_gate" -eq 0 ]; then
        go2rtc_config="$(python3 -m print_buddy.go2rtc --write-config)"
        "$go2rtc_bin" -config "$go2rtc_config" &
        children+=("$!")
    elif [ "$go2rtc_gate" -eq 3 ]; then
        echo 'go2rtc not started: timelapse capture is disabled or has no camera source.'
    else
        echo "go2rtc gate failed (status $go2rtc_gate); configuration unresolved, stopping container." >&2
        exit "$go2rtc_gate"
    fi
fi
# The configured printer instance's listener runs only when its listener
# domain (print_buddy.listeners, #299) has an implementation: the gate
# resolves the effective configuration (model -> vendor connection ->
# domain), never the presence of a service URL, which settings forbid for
# most connections. Gate status: 0 = start the instance's listener through
# the registry launcher, 3 = the domain has no listener (yet, or by
# definition), anything else = the configuration could not be resolved;
# stop instead of guessing.
listener_gate=0
python3 -m print_buddy.listener_gate || listener_gate=$?
if [ "$listener_gate" -eq 0 ]; then
    python3 -m print_buddy.listeners &
    children+=("$!")
elif [ "$listener_gate" -eq 3 ]; then
    echo 'Printer listener not started: the configured printer instance has no listener for its domain.'
else
    echo "Listener gate failed (status $listener_gate); configuration unresolved, stopping container." >&2
    exit "$listener_gate"
fi
if [ -n "${DISCORD_BOT_TOKEN:-}" ]; then
    python3 -m print_buddy.bot &
    children+=("$!")
else
    echo 'DISCORD_BOT_TOKEN is empty; bot disabled.'
fi
# The optional Web UI (#286) runs only when [webui] enabled is true and a
# port is chosen: the gate resolves the effective configuration, never an
# environment guess. Gate status: 0 = start the Web UI, 3 = disabled or no
# port (start nothing), anything else = the configuration could not be
# resolved; stop instead of guessing. The gate never bypasses the
# server's own start rules: enabling the Web UI on a non-loopback host
# without the WEBUI_ACCESS_TOKEN secret makes the child refuse to start,
# which stops the container like any other required child's exit.
webui_gate=0
python3 -m print_buddy.webui_gate || webui_gate=$?
if [ "$webui_gate" -eq 0 ]; then
    python3 -m print_buddy.webui &
    children+=("$!")
elif [ "$webui_gate" -eq 3 ]; then
    echo 'Web UI not started: disabled or no port configured.'
else
    echo "Web UI gate failed (status $webui_gate); configuration unresolved, stopping container." >&2
    exit "$webui_gate"
fi
if [ "${#children[@]}" -eq 0 ]; then
    # Nothing to supervise for this configuration (no listener, no bot, no
    # bundled Spoolman): stay up idling instead of exiting into a restart loop.
    echo 'No supervised children for this configuration; idling.'
    sleep infinity &
    children+=("$!")
fi
status=0
wait -n "${children[@]}" || status=$?
echo "Required child exited (status $status); stopping container." >&2
if [ "$status" -eq 0 ]; then status=1; fi
exit "$status"
