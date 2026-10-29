"""[delivery] format (#564 stage 1): default .gcode everywhere; gcode_3mf is a
Flashforge/ZMod-only opt-in and anything else is refused at load, never ignored.
"""
import pytest

from print_handy import settings


def load(environ):
    return settings.load(local=False, environ=environ)


def test_default_is_gcode():
    assert load({})["delivery"]["format"] == "gcode"


def test_gcode_3mf_accepted_for_the_ad5x():
    config = load({"PRINT_HANDY__DELIVERY__FORMAT": "gcode_3mf"})
    assert config["printer"]["model"] == "flashforge.ad5x"
    assert config["delivery"]["format"] == "gcode_3mf"


def test_gcode_3mf_refused_for_a_non_zmod_vendor():
    with pytest.raises(settings.SettingsError, match="only applies to Flashforge"):
        load({"PRINT_HANDY__PRINTER__MODEL": "bambulab.a1",
              "PRINT_HANDY__DELIVERY__FORMAT": "gcode_3mf"})


def test_unknown_format_refused():
    with pytest.raises(settings.SettingsError, match="\\[delivery\\] format must be one of"):
        load({"PRINT_HANDY__DELIVERY__FORMAT": "zip"})
