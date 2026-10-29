"""#621: offer the next plate only when the bed looks clear. Never start it."""
from print_handy.hermes.next_plate_offer import decide


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
