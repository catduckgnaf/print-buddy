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


def test_a_missing_map_does_not_raise_or_invent_a_sentence():
    bare = SimpleNamespace(model=None, config=None)
    assert confirm_note(bare, None) == ""
    assert confirm_note(bare, {"delivery_format": None}) == ""
    assert confirm_note(bare, "not a job") == ""
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


def test_auto_reads_the_zmod_version_for_the_card(monkeypatch):
    from print_handy.core import model_job
    adapter = SimpleNamespace(
        model=SimpleNamespace(vendor_key="flashforge"),
        config={"printer": {"zmod_delivery_format": "auto"}},
    )
    state = {"moonraker_url": "http://printer"}
    assert confirm_note(adapter, {}) == ""
    monkeypatch.setattr(model_job, "_zmod_version", lambda st: (1, 7, 5))
    assert confirm_note(adapter, {}, state) == NOTE
    monkeypatch.setattr(model_job, "_zmod_version", lambda st: (1, 7, 4))
    assert confirm_note(adapter, {}, state) == ""

    def boom(st):
        raise OSError("down")

    monkeypatch.setattr(model_job, "_zmod_version", boom)
    assert confirm_note(adapter, {}, state) == ""
