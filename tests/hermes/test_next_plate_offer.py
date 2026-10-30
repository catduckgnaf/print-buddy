"""#621: offer the next plate only when the bed looks clear. Never start it."""
from print_handy.hermes.next_plate_offer import confirm_components, decide


def test_empty_bed_offers_once_and_names_the_existing_command():
    first = decide("Plate 2", "empty_idle", said=set(), plan_id="plan-a")
    assert first["action"] == "offer"
    assert "Bed looks clear" in first["text"]
    assert "/print-next plan-a" in first["text"]
    assert "Nothing starts" in first["text"]
    again = decide("Plate 2", "empty_idle", said={"offer"}, plan_id="plan-a")
    assert again["action"] == "none"


def test_occupied_bed_says_so_once_and_no_camera_says_nothing():
    occupied = decide("Plate 2", "ok", said=set(), plan_id="plan-a")
    assert occupied["action"] == "not_clear"
    assert "does not look clear" in occupied["text"]
    assert decide("Plate 2", "ok", said={"not_clear"}, plan_id="plan-a")["action"] == "none"
    assert decide("Plate 2", None, said=set(), plan_id="plan-a")["action"] == "none"
    assert decide("", "empty_idle", said=set(), plan_id="plan-a")["action"] == "none"


def test_offer_button_is_the_existing_confirm_and_dismiss_does_not_start():
    rows = confirm_components("abc", confirm_label="Start next plate · bed is clear", cancel_label="Cancel")
    go, drop = rows[0]["components"]
    assert go["custom_id"] == "pbplate:go:abc"
    assert go["label"] == "Start next plate · bed is clear"
    assert drop["custom_id"] == "pbplate:drop:abc"
    assert "start(" not in str(rows)


def test_dismiss_handler_does_not_start_and_go_still_uses_print_next():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "plugins/print-feedback/__init__.py").read_text(encoding="utf-8")
    drop = text[text.index("async def handle_plate_drop"):text.index("async def handle_plate_go")]
    go = text[text.index("async def handle_plate_go"):text.index("async def run_plate_start")]
    assert "print_next.start" not in drop
    assert "Nothing started" in drop
    assert "print_next.start" in go


def test_each_plate_of_the_same_plan_gets_its_own_offer(tmp_path, monkeypatch):
    from print_handy.hermes import next_plate_offer as npo
    monkeypatch.setenv("PRINT_HANDY_NEXT_PLATE_OFFER", str(tmp_path / "offer.json"))
    npo.remember("plan-a")
    data = npo._load()
    data["said"] = ["offer"]
    npo._save(data)
    npo.remember("plan-a")
    assert npo._load()["said"] == []
    npo.clear()
    assert npo.due() is False


def test_dismiss_clears_the_offer_state():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "plugins/print-feedback/__init__.py").read_text(encoding="utf-8")
    drop = text[text.index("async def handle_plate_drop"):text.index("async def handle_plate_go")]
    assert "next_plate_offer" in drop and "clear" in drop


def test_bed_check_does_not_run_during_a_print(tmp_path, monkeypatch):
    import asyncio
    from print_handy.hermes import moonraker_event_listener as mel
    from print_handy.hermes import next_plate_offer as npo
    monkeypatch.setenv("PRINT_HANDY_NEXT_PLATE_OFFER", str(tmp_path / "offer.json"))
    npo.remember("plan-a")
    looked = []
    monkeypatch.setattr(mel, "_vision_ready", lambda: looked.append(1) or False)
    listener = mel.Listener()
    listener.state = "printing"
    asyncio.run(listener.offer_next_plate_if_clear())
    assert looked == []
    assert npo._load()["checked_at"] == 0
    listener.state = "complete"
    asyncio.run(listener.offer_next_plate_if_clear())
    assert looked == [1]
