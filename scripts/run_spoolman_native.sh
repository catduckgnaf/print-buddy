#!/usr/bin/env bash
# Launch an isolated local Spoolman 0.27.0 server for Print Buddy service tests.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON:-python3}"
data_dir="${SPOOLMAN_DIR_DATA:-${TMPDIR:-/tmp}/print-buddy-spoolman-data}"
port="${SPOOLMAN_PORT:-7912}"
mkdir -p "$data_dir"
"$python_bin" -m pip install "$root/vendor/spoolman-0.27.0.tar.gz"
export SPOOLMAN_DIR_DATA="$data_dir" SPOOLMAN_PORT="$port"
exec "$python_bin" -m uvicorn spoolman.main:app --host 127.0.0.1 --port "$port"
