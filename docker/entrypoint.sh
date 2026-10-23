#!/bin/sh
# Container entry point: check the data volumes, start a virtual display for the OrcaSlicer CLI,
# then exec the runtime named by the image CMD (or any command given to `docker run`).
set -eu

for dir in /data/hermes /data/archive /data/records /data/cache; do
    mkdir -p "$dir" 2>/dev/null || true
    if ! [ -w "$dir" ]; then
        echo "print-buddy: $dir is not writable by uid $(id -u) gid $(id -g)." >&2
        echo "print-buddy: give the host directory to that user (see docs/DOCKER.md, Volumes), e.g. chown -R $(id -u):$(id -g) <host dir>" >&2
        exit 1
    fi
done
mkdir -p /data/hermes/state /data/hermes/logs "$HOME" "${TMPDIR:-/tmp}" /data/cache/work
# OrcaSlicer writes its log into the working directory: keep the runtime's on the cache volume
# rather than the small /tmp. An explicit `docker run -w` is kept.
if [ "$PWD" = /tmp ]; then
    cd /data/cache/work
fi

# OrcaSlicer expects a display even in CLI mode. /tmp is a tmpfs when the root filesystem is read-only.
display=${DISPLAY:-:99}
if ! [ -e "/tmp/.X11-unix/X${display#:}" ]; then
    Xvfb "$display" -screen 0 1024x768x24 -nolisten tcp >/dev/null 2>&1 &
fi
export DISPLAY="$display"

exec "$@"
