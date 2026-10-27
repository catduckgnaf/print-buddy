"""spool_sync against a real Spoolman server. CI runs Spoolman as a service container.

Skipped unless PRINT_HANDY_SPOOLMAN_TEST_URL points at a throwaway Spoolman; never aim it at the home server.
"""
import json
import os

import pytest

from print_handy.hermes import spool_sync

URL = os.environ.get("PRINT_HANDY_SPOOLMAN_TEST_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="set PRINT_HANDY_SPOOLMAN_TEST_URL to a throwaway Spoolman")


def client(method, path, body=None):
    return spool_sync._http(URL, method, path, body)


def printer(method, path, body=None):
    """Moonraker stand-in: idle printer, no active usage spool."""
    return {"result": {"spool_id": None, "status": {"print_stats": {"state": "standby"}}}}


def new_spool(text):
    return spool_sync.create_spool(spool_sync.parse_new(text), client=client)


def test_new_spool_lands_on_the_shelf_and_reuses_its_filament_type():
    first = new_spool("Testbrand, PLA, Sea Green, 1000, 2E8B57")
    second = new_spool("Testbrand, PLA, Sea Green, 750")
    assert not first["reused_filament"] and second["reused_filament"]
    assert first["filament_id"] == second["filament_id"]
    spool = client("GET", f"/api/v1/spool/{second['spool_id']}")
    assert spool["location"] == spool_sync.SHELF
    assert spool["remaining_weight"] == pytest.approx(750)
    assert spool["filament"]["color_hex"].upper() == "2E8B57"


def hardware_record(tmp_path):
    """Every working install has this record; printer_state owns it and spool_sync updates slots in it."""
    path = tmp_path / "printer_hardware.json"
    path.write_text(json.dumps({"ifs_slots": {}}))
    return path


def test_binding_a_slot_moves_the_old_spool_back_to_the_shelf(tmp_path):
    state = hardware_record(tmp_path)
    old = new_spool("Testbrand, PETG, Night Black, 1000, 111111")["spool_id"]
    new = new_spool("Testbrand, PETG, Snow White, 1000, FFFFFF")["spool_id"]
    spool_sync.bind_slot(3, old, client=client, mr=printer, state_path=state, push_screen_update=False)
    result = spool_sync.bind_slot(3, new, client=client, mr=printer, state_path=state, push_screen_update=False)
    assert result["prior_spool_id"] == old
    assert client("GET", f"/api/v1/spool/{new}")["location"] == "IFS Slot 3"
    assert client("GET", f"/api/v1/spool/{old}")["location"] == spool_sync.SHELF
    assert result["record"]["name"] == "Snow White PETG"
    listing = spool_sync.list_text(client=client, state_path=state)
    assert f"Slot 3: #{new} Snow White PETG" in listing
    assert f"#{old} Night Black PETG" in listing.split("**Shelf**")[1]


def test_archived_spool_is_refused(tmp_path):
    sid = new_spool("Testbrand, PLA, Used Up, 1000")["spool_id"]
    client("PATCH", f"/api/v1/spool/{sid}", {"archived": True})
    with pytest.raises(spool_sync.SpoolError, match="archived"):
        spool_sync.bind_slot(1, sid, client=client, mr=printer, state_path=hardware_record(tmp_path),
                             push_screen_update=False)
