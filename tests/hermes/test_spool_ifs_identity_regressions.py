import pytest
from print_buddy.hermes import spool_sync
from print_buddy.core import model_job
from print_buddy.printers.flashforge.zmod import stock


def test_rebinding_slot_does_not_keep_previous_spool_color():
    rec = spool_sync._slot_record(1, {"id": 7, "filament": {"name": "PLA+", "material": "PLA+"}},
                                  {"spoolman_id": 6, "color": "Coffee", "material": "PLA"}, "test")
    assert rec["color"] != "Coffee"


def test_selection_material_and_color_match_configured_slot():
    state = {"ifs_slots": {"1": {"spoolman_id": 7, "color": "Coffee", "material": "PLA+"}}}
    with pytest.raises(ValueError):
        model_job.resolve_filament_selection(state, {"slot": 1, "spoolman_id": 7, "color": "Blue", "material": "PLA+"})


def test_selection_rejects_material_mismatch():
    state = {"ifs_slots": {"1": {"spoolman_id": 7, "color": "Coffee", "material": "PLA+"}}}
    with pytest.raises(ValueError):
        model_job.resolve_filament_selection(state, {"slot": 1, "spoolman_id": 7, "color": "coffee", "material": "PETG"})


def test_partial_stock_detail_is_rejected(monkeypatch):
    monkeypatch.setattr(stock, "_slots", lambda: 4)
    detail = {"hasMatlStation": True, "matlStationInfo": {"slotInfos": [
        {"slotId": 1, "hasFilament": True}, {"slotId": 2, "hasFilament": False}]}}
    with pytest.raises(RuntimeError, match="incomplete"):
        stock.read_stock_ifs_slots_from_detail(detail)


def test_multicolor_spool_is_not_verified_as_single_swatch():
    rec = spool_sync._slot_record(1, {"id": 7, "filament": {"name": "Rainbow PLA", "material": "PLA", "multi_color_hexes": "FF0000,00FF00"}}, None, "test")
    assert rec.get("multi_color") is True
    assert rec["physical_color_verified"] is False
    assert rec["hex"] == ""
    assert spool_sync.screen_hex("FF0000,00FF00") is None


def test_multislot_accounting_does_not_set_global_spool():
    import inspect
    source = inspect.getsource(model_job)
    assert "automatic Spoolman usage deduction disabled" in source
    assert "ACTIVE SPOOL UNCHANGED: multi-slot" not in source
