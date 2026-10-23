#!/bin/bash
# Deploy the Compose stack the way users do and check it end to end. Needs Docker and curl.
#
#   tests/docker/compose_smoke.sh external   # external Spoolman at host.docker.internal:7912
#   tests/docker/compose_smoke.sh bundled    # docker-compose.spoolman.yml
#
# PRINT_BUDDY_IMAGE / PRINT_BUDDY_TAG select the image under test (default print-buddy:ci); they are
# written to the stack's .env, which is its only configuration.
# Printer services are a fake Moonraker on its own container (tests/docker/compose.ci.yml).
# Checks: the stack becomes healthy without Hermes, Print Buddy reaches Moonraker and Spoolman,
# and Print Buddy data plus (bundled) Spoolman spools survive container recreation, an image
# upgrade and a rollback.
set -euo pipefail

mode=${1:?usage: compose_smoke.sh external|bundled}
repo=$(cd "$(dirname "$0")/../.." && pwd)
image_repo=${PRINT_BUDDY_IMAGE:-print-buddy} tag=${PRINT_BUDDY_TAG:-ci}
unset PRINT_BUDDY_IMAGE PRINT_BUDDY_TAG PRINT_BUDDY_DATA COMPOSE_FILE  # only .env configures the stack
export COMPOSE_PROJECT_NAME=pb-smoke-$mode

# A fresh folder holding only what a user downloads (plus the CI overlay), like a clean host.
work=$(mktemp -d)
mkdir -p "$work/tests/docker"
cp "$repo/docker-compose.yml" "$repo/docker-compose.spoolman.yml" "$work/"
cp "$repo/tests/docker/compose.ci.yml" "$repo/tests/docker/fake_moonraker.py" "$work/tests/docker/"
cd "$work"
data=$work/data
files=(-f docker-compose.yml)
[ "$mode" = bundled ] && files+=(-f docker-compose.spoolman.yml)
files+=(-f tests/docker/compose.ci.yml)
compose() { docker compose "${files[@]}" "$@"; }
step() { echo "::group::$*" 2>/dev/null; echo "== $*"; }
done_step() { echo "::endgroup::"; }
fail() { echo "FAIL: $*" >&2; compose ps -a || true; compose logs --tail 80 || true; exit 1; }
cleanup() {
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    docker rm -f pb-smoke-external-spoolman >/dev/null 2>&1 || true
    sudo rm -rf "$work" 2>/dev/null || rm -rf "$work"
}
trap cleanup EXIT

# The .env a user writes from .env.example, with this test's endpoints filled in.
set_tag() { sed -i "s#^PRINT_BUDDY_TAG=.*#PRINT_BUDDY_TAG=$1#" .env; }
sed -e "s#^PRINT_BUDDY__SERVICES__SPOOLMAN_URL=.*#PRINT_BUDDY__SERVICES__SPOOLMAN_URL=http://host.docker.internal:7912#" \
    -e "s#^PRINT_BUDDY_DATA=.*#PRINT_BUDDY_DATA=$data#" "$repo/.env.example" > .env
echo "PRINT_BUDDY_IMAGE=$image_repo" >> .env
set_tag "$tag"
mkdir -p "$data"/{hermes,archive,records,cache,spoolman}
sudo chown -R 1000:1000 "$data" 2>/dev/null || chown -R 1000:1000 "$data"

spoolman=http://127.0.0.1:7912
wait_http() {
    for _ in $(seq 90); do curl -fs -o /dev/null "$1" && return 0; sleep 2; done
    fail "$1 never answered"
}

if [ "$mode" = external ]; then
    step "start an external Spoolman outside the stack"
    # shellcheck disable=SC2016  # matches the literal ${SPOOLMAN_TAG:-...} in the Compose file
    image=$(sed -n 's#^ *image: \(ghcr.io/donkie/spoolman\):${SPOOLMAN_TAG:-\(.*\)}#\1:\2#p' docker-compose.spoolman.yml)
    [ -n "$image" ] || fail "no Spoolman image in docker-compose.spoolman.yml"
    mkdir -p "$work/external-spoolman" && sudo chown 1000:1000 "$work/external-spoolman" 2>/dev/null || true
    docker run -d --name pb-smoke-external-spoolman -p 7912:8000 \
        -v "$work/external-spoolman:/home/app/.local/share/spoolman" "$image" >/dev/null
    wait_http "$spoolman/api/v1/health"
    done_step
fi

step "config renders"
compose config --quiet
[ "$(compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["print-buddy"]["environment"]["PRINT_BUDDY__SERVICES__SPOOLMAN_URL"])')" = \
  "$([ "$mode" = bundled ] && echo http://spoolman:8000 || echo http://host.docker.internal:7912)" ] || fail "Spoolman URL for $mode"
done_step

up() {
    compose up -d --wait --wait-timeout 240 || fail "stack did not become healthy"
}
check_running() {
    status=$(compose exec -T print-buddy python3 -m print_buddy.healthcheck --json) || fail "health check: $status"
    for _ in $(seq 30); do
        status=$(compose exec -T print-buddy python3 -m print_buddy.healthcheck --json)
        python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1])["heartbeat"]["moonraker_connected"] else 1)' "$status" && break
        sleep 2
    done
    python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1])["heartbeat"]["moonraker_connected"] else 1)' "$status" \
        || fail "listener never connected to the external Moonraker: $status"
    echo "$status"
    doctor=$(compose exec -T print-buddy python3 -m print_buddy.doctor || true)
    echo "$doctor"
    grep -q '^ok    orca cli' <<<"$doctor" || fail "doctor: orca cli"
    grep -q '^ok    moonraker: http://fake-moonraker:7125' <<<"$doctor" || fail "doctor: moonraker"
    grep -q '^ok    spoolman: ' <<<"$doctor" || fail "doctor: spoolman"
    compose exec -T print-buddy sh -c '! command -v hermes' || fail "hermes is installed in the image"
}

step "first start ($mode Spoolman)"
up
[ "$mode" = bundled ] && wait_http "$spoolman/api/v1/health"
check_running
compose exec -T print-buddy sh -c 'echo persisted > /data/archive/smoke-marker && echo persisted > /data/records/smoke-marker'
filament=$(curl -fsS -X POST "$spoolman/api/v1/filament" -H 'Content-Type: application/json' \
    -d '{"name": "Smoke PLA", "material": "PLA", "density": 1.24, "diameter": 1.75}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
spool=$(curl -fsS -X POST "$spoolman/api/v1/spool" -H 'Content-Type: application/json' \
    -d "{\"filament_id\": $filament, \"location\": \"IFS Slot 1\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
before=$(compose ps -q print-buddy)
done_step

check_persisted() {
    # shellcheck disable=SC2016  # expands inside the container
    compose exec -T print-buddy sh -c 'test "$(cat /data/archive/smoke-marker)" = persisted && test "$(cat /data/records/smoke-marker)" = persisted' \
        || fail "Print Buddy data lost after $1"
    curl -fsS "$spoolman/api/v1/spool/$spool" | python3 -c '
import json, sys
spool = json.load(sys.stdin)
assert spool["filament"]["name"] == "Smoke PLA" and spool["location"] == "IFS Slot 1", spool' \
        || fail "spool $spool lost after $1"
}

step "recreate: down, then up again"
compose down
up
[ "$mode" = bundled ] && wait_http "$spoolman/api/v1/health"
[ "$(compose ps -q print-buddy)" != "$before" ] || fail "container was not recreated"
check_running
check_persisted "recreation"
done_step

step "upgrade to a new tag, then roll back"
docker tag "$image_repo:$tag" "$image_repo:$tag-next"
set_tag "$tag-next"
up
[ "$(docker inspect --format '{{.Config.Image}}' "$(compose ps -q print-buddy)")" = "$image_repo:$tag-next" ] \
    || fail "upgrade did not switch the image"
check_running
check_persisted "upgrade"
set_tag "$tag"
up
[ "$(docker inspect --format '{{.Config.Image}}' "$(compose ps -q print-buddy)")" = "$image_repo:$tag" ] \
    || fail "rollback did not switch the image back"
check_running
check_persisted "rollback"
docker rmi "$image_repo:$tag-next" >/dev/null
done_step

echo "ok: $mode Spoolman stack healthy without Hermes; data and spools persisted across recreation, upgrade and rollback"
