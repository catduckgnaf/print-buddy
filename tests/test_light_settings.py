"""Auto light-off settings (#516): defaults, env/file overrides, refusals.

Mirrors the roast_enabled posture tests in test_settings.py: the new
[vision] keys are off-by-default, settable from file or the
PRINT_HANDY__VISION__ environment, and invalid values are refused at
load with the setting named.
"""
import tempfile
from pathlib import Path

import pytest

from print_handy import settings


def load(environ=None, local=None):
    return settings.load(local=local if local is not None else False,
                         environ=environ or {})


def test_auto_light_defaults_off_with_no_target():
    vision = load()["vision"]
    assert vision["auto_light_off_minutes"] == 0
    assert vision["light_object"] == ""


def test_auto_light_minutes_from_env_and_file():
    data = load(environ={"PRINT_HANDY__VISION__AUTO_LIGHT_OFF_MINUTES": "30"})
    assert data["vision"]["auto_light_off_minutes"] == 30
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "local.yaml"
        local.write_text("vision:\n  auto_light_off_minutes: 45\n  light_object: 'led chamber_led'\n")
        vision = load(local=local)["vision"]
        assert vision["auto_light_off_minutes"] == 45
        assert vision["light_object"] == "led chamber_led"


def test_light_object_from_env():
    data = load(environ={"PRINT_HANDY__VISION__LIGHT_OBJECT": "neopixel sb_leds"})
    assert data["vision"]["light_object"] == "neopixel sb_leds"


@pytest.mark.parametrize("raw", ["-1", "-30"])
def test_negative_minutes_are_refused_from_env(raw):
    with pytest.raises(settings.SettingsError, match="auto_light_off_minutes"):
        load(environ={"PRINT_HANDY__VISION__AUTO_LIGHT_OFF_MINUTES": raw})


def test_non_integer_minutes_are_refused():
    with pytest.raises(settings.SettingsError):
        load(environ={"PRINT_HANDY__VISION__AUTO_LIGHT_OFF_MINUTES": "soon"})
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "local.yaml"
        local.write_text("vision:\n  auto_light_off_minutes: 1.5\n")
        with pytest.raises(settings.SettingsError, match="auto_light_off_minutes"):
            load(local=local)
        local.write_text("vision:\n  auto_light_off_minutes: -5\n")
        with pytest.raises(settings.SettingsError, match="auto_light_off_minutes"):
            load(local=local)


def test_non_string_light_object_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "local.yaml"
        local.write_text("vision:\n  light_object: 42\n")
        with pytest.raises(settings.SettingsError, match="light_object"):
            load(local=local)
