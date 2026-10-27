import pytest

from print_handy.core import printer_state


@pytest.mark.parametrize("material,expected", [
    ("PLA", {"nozzle": 210, "bed": 60}),
    ("PLA+", {"nozzle": 210, "bed": 60}),
    ("PLA Tough", {"nozzle": 210, "bed": 60}),
    ("PLA-CF", {"nozzle": 210, "bed": 60}),
    ("PETG", {"nozzle": 240, "bed": 85}),
    ("ABS", {"nozzle": 245, "bed": 100}),
    ("ASA", {"nozzle": 260, "bed": 105}),
    ("TPU", {"nozzle": 230, "bed": 50}),
    ("PA", {"nozzle": 260, "bed": 90}),
    ("PC", {"nozzle": 275, "bed": 110}),
])
def test_material_fallbacks(material, expected):
    family, temps, sources = printer_state.resolve_material_temperatures(material, {}, config={})
    assert temps == expected
    assert set(sources.values()) == {"material default"}


def test_spoolman_temperatures_override_defaults_independently():
    family, temps, sources = printer_state.resolve_material_temperatures(
        "PETG", {"settings_extruder_temp": 235, "settings_bed_temp": None}, config={})
    assert temps == {"nozzle": 235, "bed": 85}
    assert sources == {"nozzle": "Spoolman filament", "bed": "material default"}


def test_unknown_and_missing_material_fail_closed():
    for material in ("mystery blend", None):
        with pytest.raises(ValueError, match="no PLA fallback"):
            printer_state.resolve_material_temperatures(material, {}, config={})


def test_invalid_spoolman_target_rejected():
    with pytest.raises(ValueError, match="Invalid nozzle temperature"):
        printer_state.resolve_material_temperatures("PLA", {"settings_extruder_temp": 0}, config={})
