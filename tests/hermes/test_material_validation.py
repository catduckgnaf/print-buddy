"""Material target safety checks at slicing and print-start boundaries."""
from copy import deepcopy

import pytest

from print_handy.core import model_job, orca_adapter, printer_state


@pytest.mark.parametrize("material,match", [("mystery blend", "no PLA fallback"), ("", "no material")])
def test_slice_refuses_unknown_material_before_creating_slicer_configs(monkeypatch, tmp_path, material, match):
    state = {"spool": {"spoolman_id": 1, "material": material},
             "nozzle": {"diameter_mm": 0.4, "type": "brass"},
             "temps_c": {"nozzle": 210, "bed": 60}}
    monkeypatch.setattr(printer_state.settings, "current", lambda: {"material_temps": printer_state.DEFAULT_MATERIAL_TEMPS})
    with pytest.raises(RuntimeError, match=match):
        printer_state._material_temperature_contract(state)


def test_slice_refuses_mismatched_temperature_provenance():
    state = {"spool": {"material": "PETG"}, "temperature_resolution": {"material_family": "PLA"}}
    with pytest.raises(RuntimeError, match="does not match selected spool"):
        printer_state._material_temperature_contract(state)


def test_legacy_known_material_explicit_targets_remain_allowed(monkeypatch):
    state = {"spool": {"material": "PETG"}, "temps_c": {"nozzle": 235, "bed": 80}}
    monkeypatch.setattr(printer_state.settings, "current", lambda: {"material_temps": printer_state.DEFAULT_MATERIAL_TEMPS})
    assert printer_state._material_temperature_contract(state) is None
