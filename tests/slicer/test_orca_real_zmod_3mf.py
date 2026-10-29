"""Real-Orca proof for #564 stage 1: the CLI question and the packaged slice.

Skipped unless PRINT_HANDY_REAL_SLICER=1, like the rest of tests/slicer; CI runs these
in the real-slicer legs (both pinned channels are OrcaSlicer v2.5.0-alpha).

The CLI question Stage 1 had to answer: can Print Handy's Orca CLI invocation emit a
sliced .gcode.3mf? Proven here against the real binary: --slice alone writes only
plate_1.gcode (the AD5X machine template's use_3mf key does not change that), while
--slice and --export-3mf in one invocation write the full sliced package — inner G-code
byte-identical to plate_1.gcode, its upper-case MD5, slice_info filaments, plate JSON
with bbox_all, thumbnails — in the layout ZMod 1.7.5's own readers parse (Stage 0 of
#564 ran ghzserg's ThreeMFParser and get_colors over exactly this export shape).
"""
import copy
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

from print_handy import printers, settings
from print_handy.core import delivery
from .test_orca_real import write_cube

REAL = os.environ.get("PRINT_HANDY_REAL_SLICER") == "1"
WORK = settings.ROOT / ".slicer-work"
CASES = Path(__file__).resolve().parents[1] / "corpus" / "cases"

pytestmark = pytest.mark.skipif(not REAL, reason="set PRINT_HANDY_REAL_SLICER=1 to slice with the real Orca CLI")


def _orca_command():
    from print_handy.core import orca_adapter
    return orca_adapter._orca_command()


def _state():
    return {
        "moonraker_url": "http://127.0.0.1:7125",
        "spoolman_url": "http://127.0.0.1:7912",
        "nozzle": {"diameter_mm": 0.4, "type": "hardened_steel"},
        "spool": {"spoolman_id": 1, "material": "PLA", "density": 1.24},
        "temps_c": {"nozzle": 220, "bed": 60},
        "calibration_baseline": {"native_mesh": "auto"},
        "ifs_slots": {
            str(slot): {"slot": slot, "spoolman_id": slot, "material": "PLA", "color": name,
                        "physical_color_verified": True, "hex": hex_code}
            for slot, hex_code, name in ((1, "FFFFFF", "white"), (2, "FF00FF", "pink"),
                                         (3, "000000", "black"), (4, "067749", "dark green"))
        },
    }


def _adapter_3mf():
    config = copy.deepcopy(settings.load(local=False, environ={}))
    config["delivery"]["format"] = "gcode_3mf"
    return printers.get("flashforge.ad5x", config)


def _cli_slice(tmp, stl, *extra):
    templates = Path(settings.current()["orca"]["templates"])
    out = tmp / "out"
    out.mkdir()
    command = [*_orca_command(),
               "--load-settings", f"{templates / 'machine.json'};{templates / 'process.json'}",
               "--load-filaments", str(templates / "filament.json"),
               "--arrange", "1", "--orient", "0", "--ensure-on-bed", *extra,
               "--allow-newer-file", "--slice", "0", "--outputdir", str(out), str(stl)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    return out


def _slice_info(package):
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(package) as archive:
        root = ET.fromstring(archive.read("Metadata/slice_info.config"))
    return next(root.iter("plate"))


def test_cli_slice_alone_writes_no_package(tmp_path):
    """The negative half of the CLI answer: --slice by itself never emits a .gcode.3mf,
    even though the AD5X machine template already carries use_3mf."""
    WORK.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        out = _cli_slice(Path(tmp), write_cube(Path(tmp) / "cube.stl", 20))
        assert (out / "plate_1.gcode").is_file()
        assert not list(out.glob("*.3mf"))


def test_cli_slice_with_export_3mf_matches_the_zmod_contract(tmp_path):
    WORK.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        out = _cli_slice(Path(tmp), write_cube(Path(tmp) / "cube.stl", 20),
                         "--export-3mf", "plate_1.gcode.3mf")
        package = out / "plate_1.gcode.3mf"
        assert package.is_file()
        with zipfile.ZipFile(package) as archive:
            inner = archive.read("Metadata/plate_1.gcode")
            plate_json = json.loads(archive.read("Metadata/plate_1.json"))
        assert inner == (out / "plate_1.gcode").read_bytes()
        assert len(plate_json["bbox_all"]) == 4
        plate = _slice_info(package)
        meta = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
        assert float(meta["prediction"]) > 0 and float(meta["weight"]) > 0
        filaments = plate.findall(".//filament")
        assert len(filaments) == 1 and filaments[0].get("type") == "PLA" and filaments[0].get("color")
        model, adapter = printers.MODELS["flashforge.ad5x"], _adapter_3mf()
        assert delivery.zmod_package_problems(package, model, adapter) == []


def test_slice_model_produces_the_recorded_package(tmp_path):
    from print_handy.core import orca_adapter
    WORK.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        folder = Path(tmp) / "slice"
        output, provenance, _configs = orca_adapter.slice_model(
            write_cube(Path(tmp) / "cube.stl", 20), folder, _state(), adapter=_adapter_3mf())
        package = folder / "plate_1.gcode.3mf"
        assert provenance["delivery_format"] == "gcode_3mf"
        assert provenance["delivery_file"] == str(package)
        # Inner bytes are the finalized, guarded G-code itself.
        assert delivery.extract_zmod_plate_gcode(package) == output.read_bytes()
        model = printers.MODELS["flashforge.ad5x"]
        assert delivery.zmod_package_problems(package, model, _adapter_3mf()) == []
        plate = _slice_info(package)
        meta = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
        assert meta["printer_model_id"] == "AD5X"  # the repack fills what Orca leaves empty
        header = next(line for line in output.read_text(errors="replace").splitlines()
                      if line.startswith("; filament_colour"))
        assert plate.find(".//filament").get("color") == header.split("=")[1].strip().split(";")[0]


def test_slice_model_multicolour_package_carries_every_tool(tmp_path):
    """The MakerWorld shape: a multi-colour source whose package must name every tool's
    filament, or instant colour mapping on the printer has nothing to map."""
    from print_handy.core import model_job, orca_adapter, source_colors
    WORK.mkdir(exist_ok=True)
    source = CASES / "four-colors-one-plate" / "model.3mf"
    state = _state()
    manifest = source_colors.inventory(source)
    slots = [1, 2, 3, 4]
    decisions = {"mode": "per_part", "source_sha256": manifest["source_sha256"],
                 "choices": {row["key"]: model_job.resolve_filament_selection(
                     state, dict(state["ifs_slots"][str(slots[row["source_extruder"] - 1])],
                                 slot=slots[row["source_extruder"] - 1]))
                     for row in source_colors.prompts(manifest)}}
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        folder = Path(tmp) / "slice"
        output, provenance, _configs = orca_adapter.slice_model(
            source, folder, state, color_decisions=decisions, adapter=_adapter_3mf())
        package = folder / "plate_1.gcode.3mf"
        assert provenance["delivery_format"] == "gcode_3mf"
        assert delivery.extract_zmod_plate_gcode(package) == output.read_bytes()
        filaments = _slice_info(package).findall(".//filament")
        assert [f.get("color") for f in filaments] == ["#FFFFFF", "#FF00FF", "#000000", "#067749"]
        assert {f.get("type") for f in filaments} == {"PLA"}
        inner = delivery.extract_zmod_plate_gcode(package).decode(errors="replace")
        assert "; zmod_color_data = 0|#FFFFFF|PLA" in inner
        assert "; zmod_color_data = 3|#067749|PLA" in inner
        model = printers.MODELS["flashforge.ad5x"]
        assert delivery.zmod_package_problems(package, model, _adapter_3mf()) == []
