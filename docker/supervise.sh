#!/bin/bash
# Required child lifecycle; tini reaps orphans and forwards process-group signals.
set -euo pipefail
if [ "$#" -gt 0 ]; then exec "$@"; fi
children=()
probes=()
cleanup() {
    trap '' TERM INT
    for pid in "${children[@]}" "${probes[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
    for _ in {1..100}; do
        alive=false
        for pid in "${children[@]}" "${probes[@]}"; do kill -0 "$pid" 2>/dev/null && alive=true; done
        if [ "$alive" = false ]; then break; fi
        sleep 0.1
    done
    for pid in "${children[@]}" "${probes[@]}"; do kill -KILL "$pid" 2>/dev/null || true; done
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
python3 -m print_buddy.hermes.moonraker_event_listener &
children+=("$!")
# The bot starts when the configured chat platform's token is present (#164). The
# platform and the name of the environment variable holding its token are read from
# Print Buddy's own settings in one probe, so the mapping lives in exactly one
# place. The probe runs in the background with a bound: a hung or broken settings
# load must never wedge startup or delay a shutdown signal, and any failure falls
# back to the Discord default with the reason logged.
bot_platform=""
bot_token_var=""
probe_out=$(mktemp)
python3 -c '
from print_buddy import settings
cfg = settings.current()
platform = str(cfg["bot"].get("platform") or "discord")
print(platform)
print(str(cfg["matrix"]["access_token_env"]) if platform == "matrix" else str(cfg[platform]["token_env"]))
' >"$probe_out" 2>/dev/null &
probe_pid=$!
probes+=("$probe_pid")
for _ in {1..50}; do
    kill -0 "$probe_pid" 2>/dev/null || break
    sleep 0.1
done
if kill -0 "$probe_pid" 2>/dev/null; then kill -KILL "$probe_pid" 2>/dev/null || true; fi
probe_rc=0
wait "$probe_pid" 2>/dev/null || probe_rc=$?
probes=()
if [ "$probe_rc" -eq 0 ]; then
    { IFS= read -r bot_platform || true; IFS= read -r bot_token_var || true; } <"$probe_out"
fi
rm -f "$probe_out"
case "$bot_platform" in
    discord|telegram|matrix) ;;
    *) bot_platform="" ;;
esac
if [ -z "$bot_platform" ] || [ -z "$bot_token_var" ]; then
    echo 'Could not read the chat platform from the settings; falling back to Discord (DISCORD_BOT_TOKEN).'
    bot_platform=discord
    bot_token_var=DISCORD_BOT_TOKEN
fi
if [ -n "${!bot_token_var:-}" ]; then
    python3 -m print_buddy.bot &
    children+=("$!")
else
    echo "$bot_token_var is empty; bot disabled; listener and Spoolman remain active."
fi
status=0
wait -n "${children[@]}" || status=$?
echo "Required child exited (status $status); stopping container." >&2
if [ "$status" -eq 0 ]; then status=1; fi
exit "$status"
