"""#619: the 3MF confirm card names the Spoolman remap gap. G-code does not."""
from types import SimpleNamespace

from print_handy.core.spool_remap import NOTE, confirm_note, note_for


def test_forced_3mf_names_the_gap_and_gcode_does_not():
    assert note_for("3mf", None) == NOTE
    assert note_for("gcode", (1, 7, 5)) == ""
    assert "Spoolman" in NOTE and "remap" in NOTE


def test_auto_needs_a_known_new_enough_version():
    assert note_for("auto", None) == ""
    assert note_for("auto", (1, 7, 4)) == ""
    assert note_for("auto", (1, 7, 5)) == NOTE


def test_confirm_note_follows_the_recorded_format_or_the_setting():
    adapter = SimpleNamespace(
        model=SimpleNamespace(vendor_key="flashforge"),
        config={"printer": {"zmod_delivery_format": "gcode"}},
    )
    assert confirm_note(adapter, {"delivery_format": {"format": "3mf"}}) == NOTE
    assert confirm_note(adapter, {}) == ""
    adapter.config["printer"]["zmod_delivery_format"] = "3mf"
    assert confirm_note(adapter, {}) == NOTE
    other = SimpleNamespace(model=SimpleNamespace(vendor_key="bambulab"), config={})
    assert confirm_note(other, {}) == ""
