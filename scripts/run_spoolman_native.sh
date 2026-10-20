#!/usr/bin/env bash
# Launch isolated Spoolman 0.27.0 natively for Print Buddy service tests.
set -euo pipefail
python_bin="${PYTHON:-python3}"
cache_dir="${SPOOLMAN_CACHE_DIR:-${TMPDIR:-${HOME}/.cache}/print-buddy-spoolman-0.27.0}"
archive="$cache_dir/spoolman-v0.27.0.zip"
app_dir="$cache_dir/Spoolman-0.27.0"
venv_dir="$cache_dir/venv"
data_dir="${SPOOLMAN_DIR_DATA:-${TMPDIR:-${HOME}/.cache}/print-buddy-spoolman-data}"
port="${SPOOLMAN_PORT:-7912}"
mkdir -p "$cache_dir" "$data_dir"
if [[ ! -f "$archive" ]]; then curl -fL --retry 3 https://codeload.github.com/Donkie/Spoolman/zip/refs/tags/v0.27.0 -o "$archive"; fi
echo '9ceead75734683b8d5f92cb6f7b9cc0d83acaf2418f72d48736d7f995d583f42  '"$archive" | sha256sum -c -
if [[ ! -d "$app_dir" ]]; then unzip -q "$archive" -d "$cache_dir"; fi
if [[ ! -x "$venv_dir/bin/python" ]]; then "$python_bin" -m venv "$venv_dir"; "$venv_dir/bin/python" -m pip install -r "$app_dir/requirements.txt"; fi
export SPOOLMAN_DIR_DATA="$data_dir" SPOOLMAN_PORT="$port" SPOOLMAN_HOST=127.0.0.1
cd "$app_dir"
exec "$venv_dir/bin/python" -m uvicorn spoolman.main:app --host 127.0.0.1 --port "$port"
