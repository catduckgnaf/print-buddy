"""A single-slot plate derived from a multi-filament 3MF slices with the real Orca (v2.5.0-beta).

OrcaSlicer 2.5.0-beta checks that every per-filament array in a project is as long as filament_colour
("filament_is_support's count 1 not equal to filament_colour's size 2", exit -5), which 2.4.2 never did.
A derived plate runs on one logical filament, so its exported project must declare one filament too.
Every other real-slicer test sources a one-filament project and never saw this.

Skipped unless PRINT_HANDY_REAL_SLICER=1 (CI's Slicer test jobs).
"""
import json
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

from print_handy.core import model_job, orca_adapter, source_colors
from print_handy.core.color_geometry import export_single_color_plate
from tests.corpus.make_models import box, write_3mf

from .test_orca_real import WORK

REAL = os.environ.get("PRINT_HANDY_REAL_SLICER") == "1"
pytestmark = pytest.mark.skipif(not REAL, reason="set PRINT_HANDY_REAL_SLICER=1 to slice with the real Orca CLI")
STATE = Path(__file__).resolve().parents[1] / "pipeline" / "fixtures" / "printer_hardware.json"
PALETTE = [("#FFFFFF", "PLA"), ("#067749", "PLA")]


def multi_filament_source(path):
    """Two boxes on filaments 1 and 2, with every per-filament array two entries long like a real project."""
    write_3mf(path, [("Base", 1, box(30, 30, 10), (60, 60)), ("Cap", 2, box(20, 20, 8), (110, 110))],
              [("Plate 1", [0, 1])], PALETTE)
    template = json.loads((Path(orca_adapter.TEMPLATES) / "filament.json").read_text())
    project = {key: [value[0]] * len(PALETTE) for key, value in template.items()
               if isinstance(value, list) and value and not key.endswith("_settings_id")}
    project.update(filament_colour=[c for c, _ in PALETTE], filament_type=[m for _, m in PALETTE],
                   filament_is_support=["0", "0"], filament_settings_id=[template["filament_settings_id"][0]] * 2)
    with zipfile.ZipFile(path) as archive:
        entries = {info.filename: archive.read(info) for info in archive.infolist()}
    entries["Metadata/project_settings.config"] = json.dumps(project, indent=4).encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


@pytest.mark.parametrize("source_extruder", [1, 2])
def test_single_slot_plate_from_a_two_filament_source_slices(source_extruder):
    WORK.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        tmp = Path(tmp)
        source = multi_filament_source(tmp / "source.3mf")
        state = json.loads(STATE.read_text())
        manifest = source_colors.inventory(source)
        white = model_job.resolve_filament_selection(state, dict(state["ifs_slots"]["1"], slot=1))
        decisions = {"schema": "part_slots_v1", "mode": "per_part", "source_sha256": manifest["source_sha256"],
                     "choices": {row["key"]: white for row in source_colors.canonical_prompts(manifest)}}
        keys = [part["key"] for part in manifest["parts"] if part["source_extruder"] == source_extruder]
        assert keys
        plate = tmp / "slot1.3mf"
        export_single_color_plate(source, plate, decisions, keys, slot_colors=state["ifs_slots"])
        out, _provenance, _configs = orca_adapter.slice_model(
            plate, tmp / "slice", state, preserve_layout=True, filament_slot=1)
        assert Path(out).is_file() and Path(out).stat().st_size > 0
        gcode = Path(out).read_text(errors="replace")
        assert "\nT1" not in gcode, "a derived single-slot plate must stay on tool 0"
