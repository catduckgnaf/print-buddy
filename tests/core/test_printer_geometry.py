"""#623: show Moonraker nozzle, bed, and Z, and warn when they disagree."""
from types import SimpleNamespace

from print_handy.core.printer_geometry import from_configfile, warning_for

PAYLOAD = {"result": {"status": {"configfile": {"config": {
    "extruder": {"nozzle_diameter": "0.4"},
    "stepper_x": {"position_max": "220"},
    "stepper_y": {"position_max": "220"},
    "stepper_z": {"position_max": "250"},
}}}}}


def test_a_known_config_is_shown_and_a_useless_payload_is_named():
    found = from_configfile(PAYLOAD)
    assert found["nozzle_mm"] == 0.4
    assert found["bed_mm"] == [220.0, 220.0]
    assert found["max_z_mm"] == 250.0
    assert "error" in from_configfile({"result": {"hostname": "ad5x"}})


def test_a_mismatch_warns_and_does_not_rewrite():
    model = SimpleNamespace(bed_mm=(300, 300), max_print_height_mm=300,
                            supported_nozzle_sizes=(0.4,))
    text = warning_for(model, {"nozzle_mm": 0.6, "bed_mm": [220, 220], "max_z_mm": 250})
    assert "nozzle 0.6" in text and "generic Klipper" in text and "Apply still uses" in text
    assert warning_for(model, {"nozzle_mm": 0.4, "bed_mm": [300, 300], "max_z_mm": 300}) == ""
    # Registry models keep bed and height under settings["printer"], not attributes.
    nested = SimpleNamespace(supported_nozzle_sizes=(0.4, 0.6),
                             settings={"printer": {"bed_mm": [220, 220], "max_print_height_mm": 220}})
    nested_text = warning_for(nested, {"nozzle_mm": 0.4, "bed_mm": [100, 100], "max_z_mm": 80})
    assert "bed is smaller" in nested_text and "max Z is lower" in nested_text
    assert "nozzle" not in nested_text.split(".", 1)[0]
    assert warning_for(nested, {"nozzle_mm": 0.6, "bed_mm": [220, 220], "max_z_mm": 220}) == ""
