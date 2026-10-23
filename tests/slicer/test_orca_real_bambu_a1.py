"""Bambu Lab A1 with the real Orca CLI: the A1 templates slice, and the A1 guards hold on real output.

Skipped unless PRINT_BUDDY_REAL_SLICER=1; CI's real-slicer jobs run tests/slicer with the Flathub Orca.
Locally: PRINT_BUDDY_REAL_SLICER=1 python3 -m pytest -s tests/slicer/test_orca_real_bambu_a1.py
(PB_ORCA_CMD can point at an extracted Orca AppImage's AppRun, run under xvfb-run).
"""
import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from print_buddy import printers, settings
from print_buddy.core import orca_adapter, slice_guard as sg
from print_buddy.printers.bambulab import guard
from print_buddy.printers.bambulab.capabilities import A1

from .test_orca_real import WORK, _orca_command, write_cube

REAL = os.environ.get("PRINT_BUDDY_REAL_SLICER") == "1"
pytestmark = pytest.mark.skipif(not REAL, reason="set PRINT_BUDDY_REAL_SLICER=1 to slice with the real Orca CLI")
ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "tests" / "pipeline" / "fixtures" / "printer_hardware.json"


def adapter_for(key):
    return printers.get(key, settings.load(local=False, environ={"PRINT_BUDDY__PRINTER__MODEL": key}))


def a1_state():
    st = copy.deepcopy(json.loads(STATE.read_text()))
    st.update(moonraker_url="", ifs_slots={}, bed_mm=[256, 256], max_print_height_mm=256)
    st["nozzle"]["type"] = "stainless_steel"
    return st


@pytest.fixture
def work():
    WORK.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        yield Path(tmp)


def orca_cli(templates, stl, out):
    """Plain Orca CLI with a template folder, the flags the adapter uses for a single-color STL."""
    out.mkdir()
    command = [*_orca_command(), "--load-settings", f"{templates / 'machine.json'};{templates / 'process.json'}",
               "--load-filaments", str(templates / "filament.json"), "--arrange", "1", "--orient", "0",
               "--ensure-on-bed", "--allow-newer-file", "--slice", "0", "--outputdir", str(out), str(stl)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    print(f"\n$ {' '.join(command)}\nexit {result.returncode}\n{(result.stdout + result.stderr)[-2000:]}")
    return result, out / "plate_1.gcode"


def test_a1_slices_through_print_buddy_and_passes_every_guard(work):
    a1 = adapter_for("bambulab.a1")
    gcode, provenance, _configs = orca_adapter.slice_model(write_cube(work / "cube.stl", 20), work / "out",
                                                           a1_state(), adapter=a1)
    text = gcode.read_text(errors="replace")
    print(f"slice_guard: {provenance['slice_guard']}")
    assert "; printer_model = Bambu Lab A1" in text
    assert guard.VENDOR_START in text
    assert guard.foreign_commands(text) == []
    assert sg.toolpath(text), "Orca's toolpath could not be located in real A1 output"
    assert a1.gcode_problems(text, a1_state()) == []
    assert sg.TIME_HEADER.search(text), "no print-time header in real A1 output"


def test_a1_oversized_model_is_never_accepted(work):
    a1 = adapter_for("bambulab.a1")
    bed = A1["bed_mm"].value
    result, gcode = orca_cli(a1.templates_dir(), write_cube(work / "huge.stl", bed[0] + 10), work / "out")
    accepted = (result.returncode == 0 and gcode.is_file()
                and sg.post_slice(gcode, tool_slots={0: 1}, ifs_slots=1, bed=bed, templates=a1.templates_dir(),
                                  envelope=a1.motion_envelope_mm).status != "blocked"
                and not a1.gcode_problems(gcode.read_text(errors="replace")))
    assert not accepted, "an oversized model produced A1 G-code the guards accepted"


def test_ad5x_output_is_refused_by_the_a1_guard(work):
    ad5x = adapter_for("flashforge.ad5x")
    result, gcode = orca_cli(ad5x.templates_dir(), write_cube(work / "cube.stl", 20), work / "out")
    assert result.returncode == 0
    problems = " ".join(adapter_for("bambulab.a1").gcode_problems(gcode.read_text(errors="replace")))
    assert "Klipper/ZMod code (START_PRINT" in problems
    assert "not 'Bambu Lab A1'" in problems


def test_a1_protected_settings_baseline_round_trips(work):
    a1 = adapter_for("bambulab.a1")
    result, gcode = orca_cli(a1.templates_dir(), write_cube(work / "cube.stl", 20), work / "out")
    assert result.returncode == 0
    found = sg._effective_config(gcode)
    assert found.get("machine_start_gcode", "").startswith(guard.VENDOR_START)
    baseline = work / "baseline.json"
    sg.approve_baseline(gcode, path=baseline)
    assert sg.enforce_approved_baseline(gcode, path=baseline).ok
