"""Tests for #513: per-type nozzle temperature offsets for ALL filaments,
the guided nozzle-change procedure's safety gates, the state record, and
the post-change calibration prompts.

All printer contact is faked: sender/reader callables capture every G-code
script, and no test contacts a printer.
"""
import time

import pytest

from print_handy import settings
from print_handy.core import printer_state
from print_handy.core.nozzle import (
    NozzleError,
    effective_nozzle_temperature,
    get_nozzle_type_adjustments,
    normalize_nozzle_type,
)
from print_handy.hermes import nozzle_change as nc


@pytest.fixture(autouse=True)
def _no_offset_overrides(monkeypatch):
    monkeypatch.setattr(settings, "current", lambda: {"nozzle_temp_offsets": {}})


# ---------------------------------------------------------------- §2 offsets

def test_offsets_per_material_type():
    expected = {"brass": 0.0, "hardened_steel": 5.0, "stainless_steel": 5.0,
                "ruby": 0.0, "tungsten_carbide": 0.0, "diamond": 0.0}
    for nozzle_type, offset in expected.items():
        assert get_nozzle_type_adjustments(nozzle_type)["temp_offset_c"] == offset
    # Plated copper is the brass baseline (#513: brass / plated copper +0).
    assert normalize_nozzle_type("plated copper") == "brass"
    assert effective_nozzle_temperature("plated_copper", 210) == 210.0


def test_offset_applies_generically_to_every_filament_baseline():
    """catduck's direction: the offset composes on ANY filament baseline,
    not just Silk PLA — every material family in DEFAULT_MATERIAL_TEMPS."""
    for material, temps in printer_state.DEFAULT_MATERIAL_TEMPS.items():
        base = temps["nozzle"]
        assert effective_nozzle_temperature("hardened_steel", base) == base + 5.0, material
        assert effective_nozzle_temperature("stainless_steel", base) == base + 5.0, material
        assert effective_nozzle_temperature("brass", base) == float(base), material
        assert effective_nozzle_temperature("tungsten_carbide", base) == float(base), material
        assert effective_nozzle_temperature("diamond", base) == float(base), material
    # Named variants / composites resolve to the same families and get the
    # same treatment through their baselines (Silk PLA, PLA+, PLA-CF, PETG-CF).
    for label in ("Silk PLA", "PLA+", "Matte PLA", "PLA-CF", "PETG-CF", "Nylon", "Flexible"):
        family = printer_state.material_family(label)
        base_family = family.split("-", 1)[0]
        base = printer_state.DEFAULT_MATERIAL_TEMPS[base_family]["nozzle"]
        assert effective_nozzle_temperature("hardened_steel", base) == base + 5.0, label


def test_offset_override_still_wins_and_is_bounded():
    from print_handy import settings as _s
    # An operator override replaces the data-file default (e.g. +10 top of band).
    import print_handy.core.nozzle as nozzle_mod
    orig = _s.current
    try:
        _s.current = lambda: {"nozzle_temp_offsets": {"hardened_steel": 10}}
        assert effective_nozzle_temperature("hardened_steel", 220) == 230.0
        _s.current = lambda: {"nozzle_temp_offsets": {"hardened_steel": 16}}
        with pytest.raises(NozzleError):
            effective_nozzle_temperature("hardened_steel", 220)
    finally:
        _s.current = orig


# ---------------------------------------------------------------- §1 record

def _state():
    return {"nozzle": {"diameter_mm": 0.4, "type": "brass", "installed": "2026-01-01"},
            "z_offset_mm": 1.23, "z_offset_verified": True,
            "pressure_advance": {"value": 0.04, "nozzle_installed": "2026-01-01"},
            "temps_c": {"nozzle": 210, "bed": 60}}


def test_record_nozzle_change_updates_state_and_invalidates_calibration():
    st = _state()
    nc.record_nozzle_change(st, 0.6, "hardened steel", today="2026-10-28")
    assert st["nozzle"] == {"diameter_mm": 0.6, "type": "hardened_steel", "installed": "2026-10-28"}
    assert st["z_offset_verified"] is False
    assert st["z_offset_mm"] is None
    assert st["calibration_authority"]["reason"] == \
        "Nozzle changed; previous calibration is historical only"
    assert st["pressure_advance"]["stale"] is True
    assert st["calibration_pending"] == ["z_offset", "bed_mesh", "pressure_advance_flow"]
    assert st["bed_mesh_stale"] is True
    assert st["nozzle_change"]["previous"] == {"diameter_mm": 0.4, "type": "brass"}
    assert st["nozzle_change"]["new"] == {"diameter_mm": 0.6, "type": "hardened_steel"}


def test_record_nozzle_change_rejects_unsupported_without_mutating():
    st = _state()
    with pytest.raises(NozzleError):
        nc.record_nozzle_change(st, 0.3, "brass")
    with pytest.raises(NozzleError):
        nc.record_nozzle_change(st, 0.4, "unobtanium")
    assert st["nozzle"]["type"] == "brass"
    assert "calibration_pending" not in st


def test_finish_change_persists_via_printer_state(tmp_path, monkeypatch):
    state_file = tmp_path / "printer_hardware.json"
    import json
    state_file.write_text(json.dumps(_state()))
    monkeypatch.setattr(printer_state, "STATE", str(state_file))
    text = nc.finish_change({}, 0.8, "diamond", today="2026-10-28")
    saved = json.loads(state_file.read_text())
    assert saved["nozzle"] == {"diameter_mm": 0.8, "type": "diamond", "installed": "2026-10-28"}
    assert "Bed Mesh Leveling" in text


# ---------------------------------------------------------------- §1 steps

def test_guide_steps_cover_the_issue_procedure_in_order():
    keys = [s["key"] for s in nc.GUIDE_STEPS]
    assert keys == ["select", "confirm_heat", "heat_loosen", "removed_threaded",
                    "hot_torque", "cooldown", "record", "calibration"]
    assert nc.GUIDED_DIAMETERS_MM == (0.2, 0.4, 0.6, 0.8)
    assert nc.GUIDED_TYPES == ("brass", "hardened_steel", "stainless_steel",
                               "tungsten_carbide", "diamond")
    assert nc.LOOSEN_TEMP_C == 250 and nc.SAFE_TEMP_C == 50
    # Exactly one step may heat, and it is not the selection or record step.
    assert [s["key"] for s in nc.GUIDE_STEPS if s["heats"]] == ["heat_loosen"]
    assert nc.REMOVED_LABEL == "Old Nozzle Removed & New Nozzle Threaded"


def test_live_heat_only_on_moonraker_and_manual_fallback_text():
    assert nc.supports_live_heat("moonraker") is True
    for other in ("bambulab_lan", "prusalink", "elegoo_sdcp", "flashforge_stock",
                  "octoprint", "offline", None, ""):
        assert nc.supports_live_heat(other) is False
    text = nc.manual_heat_instructions()
    assert "250 °C" in text and "screen" in text and "50 °C" in text


def _idle_reader(temp=25.0, target=0.0, state="standby"):
    box = {"temp": temp, "target": target}
    def reader():
        return {"print_stats": {"state": state},
                "extruder": {"temperature": box["temp"], "target": box["target"]},
                "webhooks": {"state": "ready"}}
    return box, reader


def test_heat_for_loosen_sends_m104_and_waits_for_readback():
    box, reader = _idle_reader()
    sent = []
    def sender(script):
        sent.append(script)
        if script.startswith("M104 S250"):
            box["temp"], box["target"] = 252.0, 250.0
    ok, detail = nc.heat_for_loosen(confirmed_at=time.time(), gcode_sender=sender,
                                    reader=reader, wait_timeout_s=5, poll_s=0.01)
    assert ok and "252" in detail
    assert sent == ["M104 S250"]


def test_heat_for_loosen_refuses_expired_confirmation_and_busy_printer():
    sent = []
    ok, detail = nc.heat_for_loosen(confirmed_at=time.time() - 10_000,
                                    gcode_sender=sent.append, reader=_idle_reader()[1])
    assert not ok and "expired" in detail and sent == []
    _box, reader = _idle_reader(state="printing")
    ok, detail = nc.heat_for_loosen(confirmed_at=time.time(), gcode_sender=sent.append,
                                    reader=reader)
    assert not ok and "printing" in detail and sent == []
    # Unreadable printer state fails closed too.
    def broken():
        raise RuntimeError("offline")
    ok, detail = nc.heat_for_loosen(confirmed_at=time.time(), gcode_sender=sent.append,
                                    reader=broken)
    assert not ok and sent == []


def test_heat_for_loosen_timeout_turns_heater_off():
    _box, reader = _idle_reader(temp=20.0)  # never heats
    sent = []
    ok, detail = nc.heat_for_loosen(confirmed_at=time.time(), gcode_sender=sent.append,
                                    reader=reader, wait_timeout_s=0.05, poll_s=0.01)
    assert not ok and "did not reach" in detail
    assert sent == ["M104 S250", "M104 S0"]


def test_cooldown_requires_live_readback_below_50():
    box, reader = _idle_reader(temp=240.0, target=250.0)
    sent = []
    def sender(script):
        sent.append(script)
        if script == "M104 S0":
            box["temp"], box["target"] = 41.0, 0.0
    ok, detail = nc.cooldown(gcode_sender=sender, reader=reader, timeout_s=5, poll_s=0.01)
    assert ok and "41" in detail and sent == ["M104 S0"]
    # Still hot at timeout: failure, never a silent success.
    _b2, hot_reader = _idle_reader(temp=180.0, target=0.0)
    ok, detail = nc.cooldown(gcode_sender=lambda s: None, reader=hot_reader,
                             timeout_s=0.05, poll_s=0.01)
    assert not ok and "still" in detail


def test_run_bed_mesh_gated_like_heating():
    sent = []
    ok, detail = nc.run_bed_mesh(confirmed_at=time.time() - 10_000,
                                 gcode_sender=sent.append, reader=_idle_reader()[1])
    assert not ok and sent == []
    ok, detail = nc.run_bed_mesh(confirmed_at=time.time(), gcode_sender=sent.append,
                                 reader=_idle_reader()[1])
    assert ok and sent == ["BED_MESH_CALIBRATE"]


# ---------------------------------------------------------------- §3 prompts

def test_calibration_prompts_cover_z_mesh_and_pressure_advance():
    st = _state()
    nc.record_nozzle_change(st, 0.6, "tungsten_carbide", today="2026-10-28")
    prompts = {p["key"]: p for p in nc.calibration_prompts(st)}
    assert set(prompts) == {"z_offset", "bed_mesh", "pressure_advance_flow"}
    assert prompts["z_offset"]["command"] == "--sync-z"
    assert prompts["bed_mesh"]["label"] == "Run Bed Mesh Leveling"
    assert prompts["bed_mesh"]["command"] == "BED_MESH_CALIBRATE"
    assert prompts["bed_mesh"]["moves_printer"] is True
    # Non-0.4 diameter: PA/flow is escalated from offer to strong recommendation.
    assert "strongly recommended" in prompts["pressure_advance_flow"]["detail"]
    text = nc.calibration_text(st)
    assert "historical only" in text and "Bed Mesh Leveling" in text


def test_commands_table_registers_nozzle():
    from print_handy.bot import commands, llm
    cmd = commands.by_name("nozzle")
    assert cmd is not None and cmd.usage == "/nozzle change"
    assert llm.allowed_command("/nozzle change") == "/nozzle change"
    assert "/nozzle change" in commands.help_text()
