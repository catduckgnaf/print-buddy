#!/bin/bash
# Required child lifecycle; tini reaps orphans and forwards process-group signals.
set -euo pipefail
if [ "$#" -gt 0 ]; then exec "$@"; fi
children=()
listener_loops=()
listener_run_dir=""
cleanup() {
    trap '' TERM INT
    local pid file
    for pid in "${children[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
    for pid in "${listener_loops[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
    if [ -n "$listener_run_dir" ]; then
        for file in "$listener_run_dir"/*.pid; do
            [ -f "$file" ] || continue
            kill -TERM "$(cat "$file")" 2>/dev/null || true
        done
    fi
    for _ in {1..100}; do
        alive=false
        for pid in "${children[@]}" "${listener_loops[@]}"; do kill -0 "$pid" 2>/dev/null && alive=true; done
        if [ -n "$listener_run_dir" ]; then
            for file in "$listener_run_dir"/*.pid; do
                [ -f "$file" ] || continue
                kill -0 "$(cat "$file")" 2>/dev/null && alive=true
            done
        fi
        if [ "$alive" = false ]; then break; fi
        sleep 0.1
    done
    for pid in "${children[@]}" "${listener_loops[@]}"; do kill -KILL "$pid" 2>/dev/null || true; done
    if [ -n "$listener_run_dir" ]; then
        for file in "$listener_run_dir"/*.pid; do
            [ -f "$file" ] || continue
            kill -KILL "$(cat "$file")" 2>/dev/null || true
        done
        rm -rf "$listener_run_dir"
    fi
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
# Listener instances (#336, design §2.5): one per roster printer whose
# listener domain (print_buddy.listeners, #299) has an implementation. The
# gate resolves the effective configuration per printer (model -> vendor
# connection -> domain), never the presence of a service URL, which
# settings forbid for most connections. Gate status per printer: 0 =
# start that printer's listener through the registry launcher, 3 = the
# domain has no listener (yet, or by definition), anything else = the
# configuration could not be resolved; stop instead of guessing. The
# roster itself failing to resolve stops the container the same way.
roster_status=0
roster_ids="$(python3 -m print_buddy.listener_gate --roster)" || roster_status=$?
if [ "$roster_status" -ne 0 ]; then
    echo "Listener gate failed (status $roster_status); configuration unresolved, stopping container." >&2
    exit "$roster_status"
fi
listener_run_dir="$(mktemp -d)"
run_listener() {
    # One printer's listener, restarted alone when it exits, with backoff
    # and a restart budget (design §2.5): listener children are NOT
    # required children — a dead or looping listener degrades to "that
    # printer unhealthy" in the healthcheck, never to a container restart
    # loop (the #256 failure shape), and never touches the bot, Spoolman
    # or another printer's listener. The backoff/budget/window are
    # env-tunable for the container-shaped tests; defaults are production.
    local printer_id="$1"
    local backoff="${PRINT_BUDDY_LISTENER_RESTART_BACKOFF_S:-5}"
    local budget="${PRINT_BUDDY_LISTENER_RESTART_BUDGET:-5}"
    local window="${PRINT_BUDDY_LISTENER_RESTART_WINDOW_S:-600}"
    local restarts=0 window_start=$SECONDS child="" status=0
    trap 'if [ -n "$child" ]; then kill -TERM "$child" 2>/dev/null || true; fi; exit 0' TERM INT
    while true; do
        python3 -m print_buddy.listeners --printer "$printer_id" &
        child=$!
        echo "$child" > "$listener_run_dir/$printer_id.pid"
        status=0
        wait "$child" || status=$?
        child=""
        rm -f "$listener_run_dir/$printer_id.pid"
        if [ $((SECONDS - window_start)) -ge "$window" ]; then
            window_start=$SECONDS
            restarts=0
        fi
        restarts=$((restarts + 1))
        if [ "$restarts" -gt "$budget" ]; then
            echo "Listener for printer '$printer_id' exited (status $status) and exhausted its restart budget ($budget restarts in ${window}s); leaving it down — the healthcheck reports this printer unhealthy." >&2
            return 0
        fi
        echo "Listener for printer '$printer_id' exited (status $status); restarting in ${backoff}s (restart $restarts/$budget)." >&2
        sleep "$backoff" & wait $! || true
        backoff=$((backoff * 2))
        if [ "$backoff" -gt 60 ]; then backoff=60; fi
    done
}
if [ -n "$roster_ids" ]; then
    while IFS= read -r printer_id; do
        [ -n "$printer_id" ] || continue
        listener_gate=0
        python3 -m print_buddy.listener_gate --printer "$printer_id" || listener_gate=$?
        if [ "$listener_gate" -eq 0 ]; then
            run_listener "$printer_id" &
            listener_loops+=("$!")
        elif [ "$listener_gate" -eq 3 ]; then
            echo "Printer listener not started for printer '$printer_id': its domain has no listener."
        else
            echo "Listener gate failed for printer '$printer_id' (status $listener_gate); configuration unresolved, stopping container." >&2
            exit "$listener_gate"
        fi
    done <<< "$roster_ids"
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
    # No required children for this configuration (no bot, no bundled
    # Spoolman, no Web UI; listener instances run under their own loops
    # and are never required): stay up idling instead of exiting into a
    # restart loop.
    echo 'No supervised children for this configuration; idling.'
    sleep infinity &
    children+=("$!")
fi
status=0
wait -n "${children[@]}" || status=$?
echo "Required child exited (status $status); stopping container." >&2
if [ "$status" -eq 0 ]; then status=1; fi
exit "$status"
