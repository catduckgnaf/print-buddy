"""Runs the offline shell suites for bin/moonrakerctl and bin/mesh-routine.sh."""
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
needs_tools = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="bash and jq are required")


def run(script):
    result = subprocess.run(["bash", str(HERE / script)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@needs_tools
def test_mesh_routine_offline_cases():
    assert "PASS: 23 offline cases" in run("test-mesh-routine.sh")


@needs_tools
def test_moonrakerctl_gates_and_transport():
    assert "PASS:" in run("test_moonrakerctl.sh")


FAKE_CURL = """#!/usr/bin/env bash
out=''
while (($#)); do
  case "$1" in -o) out="$2"; shift 2 ;; *) last="$1"; shift ;; esac
done
printf '%s' "$last" >"$CAPTURE"
printf '{}' >"$out"
printf '200'
"""


@needs_tools
@pytest.mark.parametrize("env,expected", [
    ({"PRINT_HANDY__SERVICES__MOONRAKER_URL": "http://settings.test:7125"}, "http://settings.test:7125/printer/print/pause"),
    ({"PRINT_HANDY__SERVICES__MOONRAKER_URL": "http://settings.test:7125", "MOONRAKER_URL": "http://env.test:7125"},
     "http://env.test:7125/printer/print/pause"),
])
def test_moonrakerctl_url_comes_from_settings_and_env_overrides(tmp_path, env, expected):
    import os
    from print_handy import settings
    (tmp_path / "curl").write_text(FAKE_CURL)
    (tmp_path / "curl").chmod(0o755)
    capture = tmp_path / "url"
    base = {k: v for k, v in os.environ.items() if k != "MOONRAKER_URL"}
    result = subprocess.run([str(settings.ROOT / "bin" / "moonrakerctl"), "pause"], capture_output=True, text=True, timeout=60,
                            env={**base, **env, "CAPTURE": str(capture), "PATH": f"{tmp_path}:{os.environ['PATH']}"})
    assert result.returncode == 0, result.stderr
    assert capture.read_text() == expected
