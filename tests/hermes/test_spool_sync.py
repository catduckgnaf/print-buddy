import json
from pathlib import Path
from unittest import mock
import pytest

from print_handy.hermes import spool_sync
from print_handy.printers.flashforge.zmod import screen
from print_handy.hermes.moonraker_event_listener import MidPrintSlotTracker, load_runout_pause
from print_handy.hermes.print_next import NextPlateError


def test_slot_record_strips_repeated_trailing_material_case_insensitively():
    spool = {"id": 14, "filament": {"name": "Pink PLA", "material": "PLA", "color_hex": "F95D73"}}
    record = spool_sync._slot_record(2, spool, None, "test")
    assert record["color"] == "pink"
    assert record["name"] == "Pink PLA"

    distinct = spool_sync._slot_record(2, {"id": 15, "filament": {"name": "Pink", "material": "PLA"}}, None, "test")
    assert distinct["color"] == "pink"
    assert distinct["name"] == "Pink PLA"

    material_only = spool_sync._slot_record(2, {"id": 16, "filament": {"name": "PLA", "material": "PLA"}}, None, "test")
    assert material_only["color"] == ""
    assert material_only["name"] == "PLA"

    plus = spool_sync._slot_record(
        1, {"id": 13, "filament": {"name": "Matte White PLA+", "material": "PLA+"}}, None, "test")
    assert plus["color"] == "matte white"
    assert plus["name"] == "Matte White PLA+"


def test_screen_material_coercion():
    assert screen.screen_type("PLA+") == "PLA"
    assert screen.screen_type("pla") == "PLA"
    assert screen.screen_type("PETG-CF") == "PETG-CF"
    assert screen.screen_type("UnknownType") is None
    assert screen.screen_type("") is None


def test_screen_hex_format():
    assert spool_sync.screen_hex("#ff00aa") == "FF00AA"
    assert spool_sync.screen_hex("112233") == "112233"
    assert spool_sync.screen_hex("bad") is None
    assert spool_sync.screen_hex(None) is None


def test_suspend_and_resume_usage():
    client = mock.MagicMock()
    client.side_effect = [{"result": {"spool_id": 42}}, {}, {"result": {"spool_id": None}}]
    prior = spool_sync.suspend_usage(mr=client)
    assert prior == 42
    client.assert_any_call("POST", "/server/spoolman/spool_id", {})

    client2 = mock.MagicMock()
    client2.side_effect = [{}, {"result": {"spool_id": 99}}]
    spool_sync.resume_usage(99, mr=client2)
    client2.assert_any_call("POST", "/server/spoolman/spool_id", {"spool_id": 99})


def test_mid_print_slot_tracker():
    tracker = MidPrintSlotTracker(stable_samples=2)

    # Initial observations: need 2 stable samples to confirm
    assert tracker.observe({"1": True, "2": True}) == []
    assert tracker.observe({"1": True, "2": True}) == []
    assert tracker.confirmed == {1: True, 2: True}

    # Slot 2 runs out: sample 1 (candidate changes)
    assert tracker.observe({"1": True, "2": False}) == []
    # Sample 2 (stable change -> event fired)
    events = tracker.observe({"1": True, "2": False})
    assert events == [("emptied", 2)]
    assert 2 in tracker.emptied

    # Slot 2 refilled: sample 1
    assert tracker.observe({"1": True, "2": True}) == []
    # Sample 2
    events = tracker.observe({"1": True, "2": True})
    assert events == [("refilled", 2)]
    assert 2 not in tracker.emptied


def test_split_count_copies():
    from print_handy.hermes import print_control as pc
    assert pc.split_count("benchy x3") == ("benchy", 3)
    assert pc.split_count("shelf 5 copies") == ("shelf", 5)
    assert pc.split_count("part 20 times") == ("part", 20)
    # Beyond max copies raises NextPlateError
    with pytest.raises(NextPlateError, match="copies must be 1-20"):
        pc.split_count("part x50")
    # Normal title ending in number is NOT parsed as count
    assert pc.split_count("funko shelf v2") == ("funko shelf v2", 1)


def test_slot_record_missing_color_never_reuses_cached_screen_color():
    record = spool_sync._slot_record(2, {"id": 7, "filament": {"name": "Coffee PLA+", "material": "PLA+", "color_hex": None}}, {"hex": "F95D73"}, "test")
    assert record["spoolman_id"] == 7
    # Never the cached screen colour: the code comes from this spool's own name.
    assert record["hex"] == "6F4E37" and record["hex_source"] == "name"


def test_list_text_shelf_names_the_material_once(tmp_path):
    state = tmp_path / "printer_hardware.json"
    state.write_text(json.dumps({"ifs_slots": {}}))
    client = lambda method, path, body=None: [
        {"id": 21, "remaining_weight": 800, "filament": {"name": "Coffee PLA+", "material": "PLA+"}}]
    text = spool_sync.list_text(client=client, state_path=state)
    assert "#21 Coffee PLA+, 800 g" in text and "PLA+ PLA+" not in text
