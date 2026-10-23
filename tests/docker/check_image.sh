#!/bin/sh
# Check a built Print Buddy image's metadata and contents.
#   tests/docker/check_image.sh <image> <amd64|arm64> [channel]
set -eu
image=$1 arch=$2 channel=${3:-}
here=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=docker/orcaslicer.lock
. "$here/docker/orcaslicer.lock"
channel=${channel:-$ORCA_DEFAULT_CHANNEL}
version='' sha=''
prefix=$(echo "ORCA_${channel}" | tr '[:lower:]' '[:upper:]')
eval "version=\${${prefix}_VERSION}"
eval "sha=\${${prefix}_$(echo "$arch" | tr '[:lower:]' '[:upper:]')_SHA256}"

fail() { echo "FAIL: $*" >&2; exit 1; }
field() { docker image inspect "$image" --format "$1"; }

[ "$(field '{{.Os}}/{{.Architecture}}')" = "linux/$arch" ] || fail "platform is $(field '{{.Os}}/{{.Architecture}}')"
[ "$(field '{{.Config.User}}')" = "1000:1000" ] || fail "image user is $(field '{{.Config.User}}')"
[ "$(field '{{json .Config.Healthcheck.Test}}')" = '["CMD","python3","-m","print_buddy.healthcheck"]' ] || fail "healthcheck"
[ "$(field '{{json .Config.Cmd}}')" = '["python3","-m","print_buddy.hermes.moonraker_event_listener"]' ] || fail "CMD"
[ "$(field '{{index .Config.Labels "io.print-buddy.orcaslicer.channel"}}')" = "$channel" ] || fail "channel label"
label=$(field '{{index .Config.Labels "io.print-buddy.orcaslicer.version"}}')
[ -z "$label" ] || [ "$label" = "$version" ] || fail "orcaslicer version label $label, lock pins $version"
[ "$(field '{{index .Config.Labels "org.opencontainers.image.licenses"}}')" = "MIT" ] || fail "license label"
[ "$(field '{{.Config.Volumes}}')" = "map[]" ] || fail "image declares anonymous volumes"

docker run --rm --entrypoint sh "$image" -c '
    set -eu
    . /opt/orcaslicer/PRINT_BUDDY_ORCA_PIN
    [ "$ORCA_VERSION" = "'"$version"'" ] && [ "$ORCA_SHA256" = "'"$sha"'" ] || { echo "pin: $ORCA_VERSION $ORCA_SHA256"; exit 1; }
    ! command -v hermes >/dev/null
    ! [ -e /app/hermes ] && ! [ -e /app/plugins ] && ! [ -e /app/tests ] && ! [ -e /app/.git ]
    test -x /opt/orcaslicer/AppRun
' || fail "image contents"

# OrcaSlicer runs as the unprivileged user on a read-only root, as Compose runs it.
data=$(mktemp -d)
mkdir -p "$data/hermes" "$data/archive" "$data/records" "$data/cache"
chmod -R 0777 "$data"
docker run --rm --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true \
    -v "$data/hermes:/data/hermes" -v "$data/archive:/data/archive" \
    -v "$data/records:/data/records" -v "$data/cache:/data/cache" \
    "$image" sh -c 'sleep 1; orca-slicer --help | head -1' | grep -F "OrcaSlicer-$version" || fail "orca-slicer --help"
rm -rf "$data" 2>/dev/null || sudo rm -rf "$data"
echo "ok: $image ($arch) bundles OrcaSlicer $version ($channel)"
