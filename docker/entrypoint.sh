#!/bin/bash
set -euo pipefail

# Ensure virtual framebuffer for OrcaSlicer CLI (it expects a display even headless)
if ! pgrep -x Xvfb >/dev/null 2>&1; then
    Xvfb :99 -screen 0 1024x768x24 >/dev/null 2>&1 &
    export DISPLAY=:99
    sleep 0.5
fi

# Create expected state dirs if volumes are empty
mkdir -p /data/hermes/state /data/archive /data/records /data/cache

exec "$@"
