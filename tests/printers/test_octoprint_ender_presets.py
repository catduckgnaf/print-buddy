"""Marlin Ender presets of the OctoPrint support (#461): sourced facts, shared adapter.

Facts come from the pinned OrcaSlicer tree (v2.5.0-alpha, commit
3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2), Creality vendor profiles 02.03.02.87:
printable area / height per model and the gcode flavour that puts each model on the
Marlin/OctoPrint route — including the Ender-3 V3 SE, whose profile declares marlin2
despite the V3 name. The Klipper-line Creality models live in the creality vendor
package (test_creality.py); these presets are the same OctoPrint adapter with real
per-model dimensions instead of the octoprint.marlin placeholders.
"""
import json

from print_handy import printers, settings

ENDER_PRESETS = ("octoprint.ender3", "octoprint.ender3pro", "octoprint.ender3v2",
                 "octoprint.ender3v3se")


def config_for(key):
    return settings.load(local=False, environ={"PRINT_HANDY__PRINTER__MODEL": key})


def test_ender_presets_are_registered_and_selectable():
    for key in ENDER_PRESETS:
        assert key in printers.MODELS
        assert printers.current(config_for(key)).key == key


def test_ender_presets_ride_the_octoprint_adapter_with_real_dimensions():
    for key in ENDER_PRESETS:
        a = printers.get(key, config_for(key))
        assert a.connection == "octoprint", key
        vol = a.build_volume()
        assert (vol.bed_mm, vol.max_height_mm) == ((220.0, 220.0), 250.0), key
        assert a.start_plan(60, 215) == ["M190 S60", "M109 S215"], key


def test_ender_template_geometry_matches_the_model_facts():
    for key in ENDER_PRESETS:
        a = printers.get(key, config_for(key))
        machine = json.loads((a.templates_dir() / "machine.json").read_text())
        assert machine["printable_area"] == ["0x0", "220x0", "220x220", "0x220"], key
        assert machine["printable_height"] == "250", key
        assert machine["gcode_flavor"] in ("marlin", "marlin2"), key
        assert machine["printer_model"] in machine["name"], key


def test_ender3v2_accepts_only_the_nozzle_upstream_profiles():
    # OrcaSlicer ships exactly one machine profile for the Ender-3 V2: 0.4 mm.
    assert printers.MODELS["octoprint.ender3v2"].supported_nozzle_sizes == (0.4,)
