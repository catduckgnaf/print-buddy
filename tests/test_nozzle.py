"""Tests for nozzle validation, nozzle types, and abrasive safety guards (Issue #59)."""
import pytest

from print_buddy import settings
from print_buddy.core.nozzle import (
    AbrasiveNozzleError,
    NozzleError,
    check_nozzle_material_safety,
    is_abrasive_material,
    normalize_nozzle_type,
    validate_nozzle_setting,
)


def test_normalize_nozzle_type_canonical():
    assert normalize_nozzle_type("brass") == "brass"
    assert normalize_nozzle_type("hardened_steel") == "hardened_steel"
    assert normalize_nozzle_type("hardened steel") == "hardened_steel"
    assert normalize_nozzle_type("Hardened-Steel") == "hardened_steel"
    assert normalize_nozzle_type("ruby") == "ruby"
    assert normalize_nozzle_type("ruby tipped") == "ruby"
    assert normalize_nozzle_type("tungsten carbide") == "tungsten_carbide"
    assert normalize_nozzle_type("diamond") == "diamond"
    assert normalize_nozzle_type("diamond_pcd") == "diamond"


def test_normalize_nozzle_type_invalid():
    with pytest.raises(NozzleError, match="unknown nozzle type 'plastic'"):
        normalize_nozzle_type("plastic")


def test_is_abrasive_material():
    assert is_abrasive_material("PLA-CF") is True
    assert is_abrasive_material("PETG Carbon Fiber") is True
    assert is_abrasive_material("PA-GF") is True
    assert is_abrasive_material("Glow in the dark PLA") is True
    assert is_abrasive_material("Wood PLA") is True
    assert is_abrasive_material("Metal-fill Bronze") is True
    assert is_abrasive_material("Standard PLA") is False
    assert is_abrasive_material("PETG") is False
    assert is_abrasive_material("ABS") is False
    assert is_abrasive_material(None) is False


def test_check_nozzle_material_safety_abrasive_on_brass_raises():
    with pytest.raises(AbrasiveNozzleError, match="Refusing to slice abrasive material 'PLA-CF' on a brass nozzle"):
        check_nozzle_material_safety("brass", "PLA-CF")

    with pytest.raises(AbrasiveNozzleError):
        check_nozzle_material_safety("brass", "Wood PLA")


def test_check_nozzle_material_safety_abrasive_on_hardened_passes():
    # Hardened steel, ruby, tungsten carbide, diamond can handle abrasive materials
    check_nozzle_material_safety("hardened_steel", "PLA-CF")
    check_nozzle_material_safety("ruby", "PETG-GF")
    check_nozzle_material_safety("tungsten_carbide", "Glow PLA")
    check_nozzle_material_safety("diamond", "Metal-fill PLA")


def test_check_nozzle_material_safety_non_abrasive_on_brass_passes():
    check_nozzle_material_safety("brass", "PLA")
    check_nozzle_material_safety("brass", "PETG")
    check_nozzle_material_safety("brass", None)


def test_validate_nozzle_setting():
    dia, n_type = validate_nozzle_setting(0.4, "brass")
    assert dia == 0.4
    assert n_type == "brass"

    dia, n_type = validate_nozzle_setting("0.6", "hardened steel")
    assert dia == 0.6
    assert n_type == "hardened_steel"

    with pytest.raises(NozzleError, match="not supported"):
        validate_nozzle_setting(0.3, "brass", supported_sizes=(0.2, 0.4, 0.6))

    with pytest.raises(NozzleError, match="not supported"):
        validate_nozzle_setting(0.4, "brass", supported_types=("hardened_steel", "stainless_steel"))


def test_settings_validation_nozzle_size_and_type(monkeypatch):
    # Valid nozzle size & type for ad5x
    monkeypatch.setenv("PRINT_BUDDY__PRINTER__MODEL", "flashforge.ad5x")
    monkeypatch.setenv("PRINT_BUDDY__PRINTER__NOZZLE_DIAMETER_MM", "0.6")
    monkeypatch.setenv("PRINT_BUDDY__PRINTER__NOZZLE_TYPE", "hardened_steel")
    cfg = settings.load(local=False)
    assert cfg["printer"]["nozzle_diameter_mm"] == 0.6
    assert cfg["printer"]["nozzle_type"] == "hardened_steel"

    # Unsupported nozzle size for ad5x (0.2 is not in supported (0.25, 0.4, 0.6, 0.8))
    monkeypatch.setenv("PRINT_BUDDY__PRINTER__NOZZLE_DIAMETER_MM", "0.2")
    with pytest.raises(settings.SettingsError, match="nozzle_diameter_mm 0.2 is not supported by model 'flashforge.ad5x'"):
        settings.load(local=False)

    # Unsupported nozzle type for ad5x (brass is not in supported (stainless_steel, hardened_steel))
    monkeypatch.setenv("PRINT_BUDDY__PRINTER__NOZZLE_DIAMETER_MM", "0.4")
    monkeypatch.setenv("PRINT_BUDDY__PRINTER__NOZZLE_TYPE", "brass")
    with pytest.raises(settings.SettingsError, match="nozzle_type 'brass' is not supported by model 'flashforge.ad5x'"):
        settings.load(local=False)


def test_pre_slice_guard_abrasive_material_on_brass():
    from print_buddy.core.slice_guard import pre_slice
    res = pre_slice(nozzle_type="brass", materials=["PLA-CF"], bed=(220, 220), ifs_slots=1)
    assert res.status == "blocked"
    assert any("Refusing to slice abrasive material 'PLA-CF' on a brass nozzle" in msg for msg in res.blocked)

    # Hardened steel should not be blocked
    res_ok = pre_slice(nozzle_type="hardened_steel", materials=["PLA-CF"], bed=(220, 220), ifs_slots=1)
    assert res_ok.status != "blocked"


def test_untuned_nozzle_profile_refusal(tmp_path):
    from print_buddy.core import orca_adapter
    from print_buddy.core.nozzle import UntunedNozzleError
    # State specifying 0.6mm nozzle when only 0.4mm templates are provided
    mock_state = {
        "nozzle": {"diameter_mm": 0.6, "type": "hardened_steel"},
        "spool": {"material": "PLA", "density": 1.24},
        "temps_c": {"nozzle": 220, "bed": 60},
    }
    dummy_stl = tmp_path / "cube.stl"
    dummy_stl.write_text("solid test\nendsolid test\n")
    with pytest.raises(UntunedNozzleError, match="no tuned profile exists for 0.6 mm"):
        orca_adapter.slice_model(dummy_stl, tmp_path / "out", mock_state)

