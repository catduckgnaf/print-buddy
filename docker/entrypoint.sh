#!/bin/bash
set -euo pipefail
mkdir -p "${HOME:-/data}/hermes/state" "${HOME:-/data}/archive" "${HOME:-/data}/records" "${HOME:-/data}/cache"
channel="${PRINT_HANDY_ORCA_CHANNEL:-stable}"
# 'alpha' was the preview channel's name until #600 renamed it to describe the
# role instead of the upstream stage. It stays an accepted alias for at least
# one release, with a startup notice; installs should switch to 'preview'.
if [ "$channel" = alpha ]; then
    echo "PRINT_HANDY_ORCA_CHANNEL=alpha is the old name for the 'preview' channel; it still works in this release but will be removed in a later one - set PRINT_HANDY_ORCA_CHANNEL=preview instead." >&2
    channel=preview
fi
export PRINT_HANDY_ORCA_CHANNEL="$channel"
case "$channel" in
    stable)
        selected=/usr/local/bin/orca-slicer-stable
        ;;
    preview)
        selected=/usr/local/bin/orca-slicer-preview
        ;;
    *)
        echo "PRINT_HANDY_ORCA_CHANNEL must be 'stable' or 'preview'; got '$channel'" >&2
        exit 2
        ;;
esac
export PRINT_HANDY_ORCA_CMD="$selected"
# xvfb-run owns its display and cleanup; no fixed display or procps dependency.
if [[ ( -x "$selected" || -x /usr/bin/bambu-studio ) && -z "${DISPLAY:-}" ]]; then
    exec xvfb-run -a -s '-screen 0 1024x768x24' "$@"
fi
exec "$@"
