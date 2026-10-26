"""Invented Orca resources for the #127 Stage 1 Bambu models; no Bambu/Orca profile content.

Generalizes p1s_fixture.py: builds a minimal BBL-shaped resources tree whose machine profile
matches one model's facts (printer_model, bed, Orca height, exclusion, stock nozzle), so
profiles.install can be exercised offline for every Stage 1 model. The identity the fixture
produces is deliberately NOT the model's recorded identity; tests swap it in via trust().
"""
import json
import tempfile
from pathlib import Path

from print_buddy.printers.bambulab import profiles

HERMES = Path(tempfile.mkdtemp(prefix="bambu-family-test-profile-"))


def _area(bed):
    w, d = bed
    return ["0x0", f"{w:g}x0", f"{w:g}x{d:g}", f"0x{d:g}"]


def resources(root, facts):
    root = Path(root)
    names = facts["orca_profiles"].value
    bed = facts["bed_mm"].value
    height = facts["orca_profile_height_mm"].value if "orca_profile_height_mm" in facts \
        else facts["max_print_height_mm"].value
    exclusion = facts["bed_exclude_area"].value if "bed_exclude_area" in facts else ()
    nozzle_diameter, nozzle_type = facts["stock_nozzle"].value
    bbl = root / "profiles" / "BBL"
    for folder in (bbl / "machine", bbl / "process", bbl / "filament"):
        folder.mkdir(parents=True, exist_ok=True)
    index = {"name": "Print Buddy invented family test data", "version": "00.00.00.00"}
    for kind in ("machine", "process", "filament"):
        index[f"{kind}_list"] = [{"name": names[kind], "sub_path": f"{kind}/{kind}.json"}]
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "profiles" / "BBL.json").write_text(json.dumps(index))
    machine = {
        "type": "machine", "name": names["machine"], "from": "system", "instantiation": "true",
        "printer_model": facts["printer_model"].value, "printer_variant": "0.4",
        "nozzle_diameter": [f"{nozzle_diameter:g}"], "nozzle_type": [nozzle_type, nozzle_type],
        "printable_area": _area(bed), "printable_height": f"{height:g}",
        "bed_exclude_area": [f"{x:g}x{y:g}" for x, y in exclusion],
        "machine_start_gcode": "G90\nM140 S[bed_temperature_initial_layer_single]\n"
                               "M104 S[nozzle_temperature_initial_layer]\nG1 X20 Y20 F6000\nG28\n"
                               "M109 S[nozzle_temperature_initial_layer]\n",
        "machine_end_gcode": "G91\nG1 Z2 F600\nG90\nG1 X20 Y20 F6000\nM104 S0\nM140 S0\n",
        "time_lapse_gcode": "M73 P50\n", "change_filament_gcode": "M400\n",
        "default_print_profile": names["process"], "default_filament_profile": [names["filament"]],
    }
    process = {"type": "process", "name": names["process"], "from": "system", "instantiation": "true",
               "layer_height": "0.2", "compatible_printers": [names["machine"]]}
    filament = {"type": "filament", "name": names["filament"], "from": "system", "instantiation": "true",
                "filament_type": ["PLA"], "nozzle_temperature": ["220", "220"],
                "nozzle_temperature_initial_layer": ["220", "220"],
                "filament_start_gcode": ["; fixture filament start\\n"],
                "filament_end_gcode": ["; fixture filament end\\n"],
                "compatible_printers": [names["machine"]]}
    for kind, data in (("machine", machine), ("process", process), ("filament", filament)):
        (bbl / kind / f"{kind}.json").write_text(json.dumps(data))
    return root


def identity(facts, root=None):
    root = resources(root or Path(tempfile.mkdtemp(prefix="bambu-family-resources-")), facts)
    upstream, version = profiles.flatten(root, facts["orca_profiles"].value)
    return {"label": "Print Buddy invented family fixture (not OrcaSlicer)", "vendor_version": version,
            "sha256": {kind: profiles.sha256(upstream[kind]) for kind in profiles.KINDS}}


def fixture_facts(facts):
    from print_buddy.printers.bambulab.facts import Fact
    return {**facts, "orca_identity": Fact((identity(facts),), "TEST", False)}


def trust(adapter_cls, facts, setattr):
    setattr(adapter_cls, "facts", fixture_facts(facts))


def install(adapter, facts, root=None):
    root = resources(root or Path(tempfile.mkdtemp(prefix="bambu-family-resources-")), facts)
    profiles.install(adapter, root)
    return adapter.pinned_templates_folder()
