#!/bin/bash
set -euo pipefail
mkdir -p "${HOME:-/data}/hermes/state" "${HOME:-/data}/archive" "${HOME:-/data}/records" "${HOME:-/data}/cache"
channel="${PRINT_BUDDY_ORCA_CHANNEL:-stable}"
case "$channel" in
    stable)
        selected=/usr/local/bin/orca-slicer-stable
        ;;
    alpha)
        selected=/usr/local/bin/orca-slicer-alpha
        ;;
    *)
        echo "PRINT_BUDDY_ORCA_CHANNEL must be 'stable' or 'alpha'; got '$channel'" >&2
        exit 2
        ;;
esac
export PB_ORCA_CMD="$selected"
# xvfb-run owns its display and cleanup; no fixed display or procps dependency.
if [[ ( -x "$selected" || -x /usr/bin/bambu-studio ) && -z "${DISPLAY:-}" ]]; then
    exec xvfb-run -a -s '-screen 0 1024x768x24' "$@"
fi
exec "$@"
