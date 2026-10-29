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
