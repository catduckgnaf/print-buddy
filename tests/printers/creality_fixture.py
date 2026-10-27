"""Invented Creality Orca resources for tests only; no Creality/Orca profile content.

Builds a minimal Creality-shaped resources tree (profiles/Creality.json + Creality/) whose
machine profile matches one model's facts, with a START_PRINT-led start as most of the real
Creality Klipper-line profiles use. The identity it produces is deliberately NOT the model's
recorded identity; tests swap it in via trust().
"""
import json
import tempfile
from pathlib import Path

from print_handy.printers.bambulab import profiles as _shared
from print_handy.printers.creality import profiles

HERMES = Path(tempfile.mkdtemp(prefix="creality-test-profile-"))


def resources(root, facts):
    root = Path(root)
    names = facts["orca_profiles"].value
    bed = facts["bed_mm"].value
    height = facts["max_print_height_mm"].value
    nozzle_diameter, _nozzle_type = facts["stock_nozzle"].value
    vendor_dir = root / "profiles" / "Creality"
    for folder in (vendor_dir / "machine", vendor_dir / "process", vendor_dir / "filament"):
        folder.mkdir(parents=True, exist_ok=True)
    index = {"name": "Print Handy invented Creality test data", "version": "00.00.00.00"}
    for kind in ("machine", "process", "filament"):
        index[f"{kind}_list"] = [{"name": names[kind], "sub_path": f"{kind}/{kind}.json"}]
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "profiles" / "Creality.json").write_text(json.dumps(index))
    w, d = bed
    exclusion = [f"{x:g}x{y:g}" for x, y in facts["bed_exclude_area"].value]
    machine = {
        "type": "machine", "name": names["machine"], "from": "system", "instantiation": "true",
        "printer_model": facts["printer_model"].value, "printer_variant": "0.4",
        "nozzle_diameter": [f"{nozzle_diameter:g}"],
        "printable_area": ["0x0", f"{w:g}x0", f"{w:g}x{d:g}", f"0x{d:g}"],
        "printable_height": f"{height:g}", "bed_exclude_area": exclusion,
        "machine_start_gcode": "START_PRINT EXTRUDER_TEMP=215 BED_TEMP=60\nM104 S215\nG28",
        "machine_end_gcode": "END_PRINT",
        "default_print_profile": names["process"], "default_filament_profile": [names["filament"]],
    }
    process = {"type": "process", "name": names["process"], "from": "system", "instantiation": "true",
               "layer_height": "0.2", "compatible_printers": [names["machine"]]}
    filament = {"type": "filament", "name": names["filament"], "from": "system", "instantiation": "true",
                "filament_type": ["PLA"], "nozzle_temperature": ["215", "215"],
                "filament_start_gcode": ["; fixture filament start\\n"],
                "filament_end_gcode": ["; fixture filament end\\n"],
                "compatible_printers": [names["machine"]]}
    for kind, data in (("machine", machine), ("process", process), ("filament", filament)):
        (vendor_dir / kind / f"{kind}.json").write_text(json.dumps(data))
    return root


def identity(facts, root=None):
    root = resources(root or Path(tempfile.mkdtemp(prefix="creality-resources-")), facts)
    upstream, version = _shared.flatten(root, facts["orca_profiles"].value, vendor=profiles.VENDOR)
    return {"label": "Print Handy invented Creality fixture (not OrcaSlicer)", "vendor_version": version,
            "sha256": {kind: profiles.sha256(upstream[kind]) for kind in profiles.KINDS}}


def fixture_facts(facts):
    from print_handy.printers.creality.facts import Fact
    return {**facts, "orca_identity": Fact((identity(facts),), "TEST", False)}


def trust(adapter_cls, facts, setattr):
    setattr(adapter_cls, "facts", fixture_facts(facts))


def install(adapter, facts, root=None):
    root = resources(root or Path(tempfile.mkdtemp(prefix="creality-resources-")), facts)
    profiles.install(adapter, root)
    return adapter.pinned_templates_folder()
