"""Marlin Anycubic presets of the OctoPrint support (#552): sourced facts, shared adapter.

Facts come from the pinned OrcaSlicer tree (v2.5.0-alpha, commit
3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2), Anycubic vendor profiles 02.04.00.09:
printable area / height per model and the gcode flavour that puts each model on the
Marlin/OctoPrint route — the Mega/Vyper-era machines and the first Kobra line, which
predate the Kobra 2 family's Klipper-derived firmware and have no Moonraker endpoint.
The Klipper-line models live in the anycubic vendor package (test_anycubic.py); these
presets are the same OctoPrint adapter with real per-model dimensions instead of the
octoprint.marlin placeholders. Upstream ships only a 0.4 mm nozzle machine profile for
every one of these models, so each preset accepts only 0.4 mm.
"""
import json

from print_handy import printers, settings

# key: (bed_mm, height_mm, gcode_flavor the pinned profile declares)
ANYCUBIC_PRESETS = {
    "octoprint.i3megas": ((210.0, 210.0), 205.0, "marlin"),
    "octoprint.vyper": ((250.0, 255.0), 265.0, "marlin"),
    "octoprint.chiron": ((400.0, 400.0), 450.0, "marlin"),
    "octoprint.maxpro2": ((270.0, 210.0), 190.0, "marlin"),
    "octoprint.kobra": ((220.0, 220.0), 250.0, "marlin"),
    "octoprint.kobraneo": ((220.0, 220.0), 250.0, "marlin2"),
    "octoprint.kobraplus": ((300.0, 300.0), 350.0, "marlin"),
    "octoprint.kobramax": ((400.0, 400.0), 450.0, "marlin"),
}


def config_for(key):
    return settings.load(local=False, environ={"PRINT_HANDY__PRINTER__MODEL": key})


def test_anycubic_presets_are_registered_and_selectable():
    for key in ANYCUBIC_PRESETS:
        assert key in printers.MODELS
        assert printers.current(config_for(key)).key == key


def test_anycubic_presets_ride_the_octoprint_adapter_with_real_dimensions():
    for key, (bed, height, _flavor) in ANYCUBIC_PRESETS.items():
        a = printers.get(key, config_for(key))
        assert a.connection == "octoprint", key
        vol = a.build_volume()
        assert (vol.bed_mm, vol.max_height_mm) == (bed, height), key
        assert a.start_plan(60, 215) == ["M190 S60", "M109 S215"], key


def test_anycubic_template_geometry_matches_the_model_facts():
    for key, ((w, d), height, flavor) in ANYCUBIC_PRESETS.items():
        a = printers.get(key, config_for(key))
        machine = json.loads((a.templates_dir() / "machine.json").read_text())
        assert machine["printable_area"] == ["0x0", f"{w:g}x0", f"{w:g}x{d:g}", f"0x{d:g}"], key
        assert machine["printable_height"] == f"{height:g}", key
        assert machine["gcode_flavor"] == flavor, key
        assert machine["printer_model"] in machine["name"], key


def test_anycubic_presets_accept_only_the_nozzle_upstream_profiles():
    # OrcaSlicer ships exactly one machine profile per model here: 0.4 mm.
    for key in ANYCUBIC_PRESETS:
        assert printers.MODELS[key].supported_nozzle_sizes == (0.4,), key
