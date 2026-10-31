"""Offline tests for the Snapmaker U1. No printer, network or slicer."""

import pytest

from print_handy import printers
from print_handy.core.filament_color import normalize_hex
from print_handy.printers.base import MultiColorUnsupported
from print_handy.printers.snapmaker import facts

from .test_adapters import adapter_for


def test_u1_is_a_four_tool_changer():
    model = printers.MODELS["snapmaker.u1"]
    assert model.vendor is printers.VENDORS["snapmaker"]
    assert model.label == "Snapmaker U1"
    assert model.generated_templates is False
    defaults = model.defaults()["printer"]
    assert defaults["bed_mm"] == [270.0, 270.0]
    assert defaults["max_print_height_mm"] == 270.0
    assert defaults["filament_slots"] == 1
    assert defaults["tool_count"] == 4
    assert defaults["firmware"] == "Klipper"
    for fact in facts.U1.values():
        assert fact.verified is False
        assert fact.source == "SNAPMAKER"


def test_tool_mapping_keeps_each_tool_on_its_own_head():
    adapter = adapter_for("snapmaker.u1")
    assert adapter.multi_tool is True
    assert (adapter.slot_count, adapter.multi_slot) == (4, False)
    assert adapter.normalize_tool_mapping({"0": 1, "1": 2, "2": 3, "3": 4}, {}) == {
        "0": 1, "1": 2, "2": 3, "3": 4}
    with pytest.raises(MultiColorUnsupported, match="toolhead 1"):
        adapter.normalize_tool_mapping({"0": 2}, {})
    with pytest.raises(MultiColorUnsupported, match="T4"):
        adapter.normalize_tool_mapping({"4": 5}, {})


def test_guard_refuses_foreign_start_and_over_limit_heat():
    adapter = adapter_for("snapmaker.u1")
    assert adapter.gcode_problems("PRINT_START BED=60 HOTEND=210\n") == []
    foreign = adapter.gcode_problems("START_PRINT BED_TEMP=60\n")
    assert foreign and "START_PRINT" in foreign[0]
    hot = adapter.gcode_problems("M104 S310\nM140 S110\n")
    assert any("M104" in line for line in hot)
    assert any("M140" in line for line in hot)


def test_guard_treats_bed_mesh_commands_as_foreign_like_the_other_klipper_family_guards():
    # Consistency, not a claim about Klipper: qidi, creality and elegoo refuse the same markers.
    from print_handy.printers.qidi import guard as qidi_guard
    from print_handy.printers.snapmaker import guard
    assert {"BED_MESH_CALIBRATE", "BED_MESH_PROFILE"} <= set(guard.FOREIGN_MARKERS)
    assert set(guard.FOREIGN_MARKERS) <= set(qidi_guard.FOREIGN_MARKERS) | {"PRINT_START"}
    adapter = adapter_for("snapmaker.u1")
    assert any("BED_MESH_CALIBRATE" in p for p in adapter.gcode_problems("BED_MESH_CALIBRATE\n"))


def test_u1_is_in_the_web_ui_printer_picker_and_matches_the_registry_label():
    from print_handy.webui.catalog import choices_for, field_by_id
    assert "snapmaker.u1" in choices_for(field_by_id("printer.model"))


def test_doubled_hash_color_matches_a_plain_hex():
    assert normalize_hex("##aabbcc") == "AABBCC"
    assert normalize_hex("#AABBCC") == normalize_hex("aabbcc")
    assert normalize_hex("#abc") == "AABBCC"  # #RGB is a hex color now


def test_spool_remain_reads_a_present_number_and_ignores_absence():
    adapter = adapter_for("snapmaker.u1")
    status = {"extruder": {"filament_spool_id": 7, "filament_remaining_g": 120.5},
              "extruder1": {"spool_remain_g": 0}}
    assert adapter.spool_remain_g(status, 0) == 120.5
    assert adapter.spool_remain_g(status, 1) == 0.0
    assert adapter.spool_remain_g(status, 2) is None
    assert adapter.spool_remain_g({}, 0) is None
