"""Test settings for the Hermes helpers, installed before any test module imports them.

print_handy.hermes reads its hosts and paths through print_handy.hermes._config. Here that is replaced by
a copy of the checked-in home config with fake `.test` hosts and temp directories, so no suite (hermes or pipeline)
can read a live profile or reach a live service through those modules.
"""
import os
import tempfile
from pathlib import Path

import pytest

# The geometry fixtures across the suites were authored against the Standard part
# gaps (merge spacing 10 mm, edge 8 mm, tower clearance 8/10 mm), which are now
# the "medium" preset; the shipped default is "minimum". Pin the suites to
# medium so those fixtures keep testing the algorithms they were written for.
# The presets themselves are covered by tests/core/test_spacing_presets.py, the
# minimum values by tests/slicer/test_spacing_minimums_real.py (real Orca), and
# fit behavior at the minimum preset by tests/pipeline/test_fit_auto_rearrange.py.
os.environ.setdefault("PRINT_HANDY__LAYOUT__SPACING", "medium")

from print_handy import settings  # noqa: E402
from print_handy.hermes import _config

_tmp = Path(tempfile.mkdtemp(prefix="3dp-test-state-"))
os.environ.setdefault("PRINT_BOT_CANCEL_MARKER", str(_tmp / "last_bot_cancel.json"))
os.environ.setdefault("PRINT_ALERT_STATE", str(_tmp / "print_alert_buttons.json"))
os.environ.setdefault("PRINT_WATCH_FRAME_DIR", str(_tmp / "print-watch"))


def _test_settings():
    data = settings.load(local=Path(os.devnull), environ={})
    data["paths"].update(hermes_home=_tmp / "profile", archive=_tmp / "archive", records_vault=_tmp / "vault",
                         cache=_tmp / "cache")
    data["services"].update(
        moonraker_url="http://printer.test:7125", moonraker_ws_url="ws://printer.test:7125/websocket",
        camera_snapshot_url="http://printer.test/webcam/?action=snapshot", spoolman_url="http://spoolman.test:7912",
        openviking_url="http://viking.test:1933", vision_chat_url="http://vision.test:8317/v1/chat/completions")
    data["discord"]["chat_id"] = "100000000000000001"
    data["timelapse"].update(archive_host="archive.test", archive_dir="/archive/timelapses")
    return data


TEST_SETTINGS = _test_settings()
_config.set_override(TEST_SETTINGS)



@pytest.fixture(autouse=True)
def _isolated_launch_state(tmp_path, monkeypatch):
    """Printer leases and consumed approvals live in a per-test database, never the profile's."""
    monkeypatch.setenv("PRINT_HANDY_LAUNCH_DB", str(tmp_path / "print_handy_launches.sqlite3"))
