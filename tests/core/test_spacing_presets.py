"""layout.spacing presets: every preset resolves, explicit keys win, bad names are refused."""
import pytest

from print_handy import settings


def _load(env=None, local=None):
    return settings.load(local=local or False, environ=env or {})


def _values(data):
    return {(section, key): data[section][key] for section, key in settings.SPACING_KEYS}


@pytest.mark.parametrize("preset", sorted(settings.SPACING_PRESETS))
def test_each_preset_resolves_every_spacing_key(preset):
    data = _load({"PRINT_HANDY__LAYOUT__SPACING": preset})
    assert data["layout"]["spacing"] == preset
    assert _values(data) == settings.SPACING_PRESETS[preset]
    summary = settings.spacing_summary(data)
    assert summary["preset"] == preset and summary["overridden"] == []


def test_default_is_the_measured_minimum():
    data = _load()
    assert data["layout"]["spacing"] == "minimum"
    assert _values(data) == settings.SPACING_PRESETS["minimum"]
    assert data["layout"]["arrange_gap_mm"] == 2.0 and data["prime_tower"]["part_clearance_mm"] == 3.5


def test_presets_are_ordered_and_medium_is_the_old_standard():
    order = ["minimum", "low", "medium", "high"]
    for key in settings.SPACING_KEYS:
        values = [settings.SPACING_PRESETS[name][key] for name in order]
        assert values == sorted(values), key
    assert settings.SPACING_PRESETS["medium"] == {
        ("layout", "arrange_gap_mm"): 5.0, ("layout", "arrange_edge_mm"): 5.0,
        ("layout", "merge_spacing_mm"): 10.0, ("layout", "merge_edge_margin_mm"): 8.0,
        ("prime_tower", "part_clearance_mm"): 8.0, ("prime_tower", "edge_mm"): 10.0,
        ("prime_tower", "merge_slack_mm"): 5.0}
    assert settings.SPACING_LABELS["medium"] == "Medium (Standard)"


def test_an_explicit_key_wins_over_the_preset(tmp_path):
    data = _load({"PRINT_HANDY__LAYOUT__SPACING": "high", "PRINT_HANDY__LAYOUT__MERGE_SPACING_MM": "3"})
    assert data["layout"]["merge_spacing_mm"] == 3.0
    assert data["layout"]["arrange_gap_mm"] == settings.SPACING_PRESETS["high"][("layout", "arrange_gap_mm")]
    assert settings.spacing_summary(data)["overridden"] == ["layout.merge_spacing_mm"]
    local = tmp_path / "local.yaml"
    local.write_text("layout:\n  spacing: medium\nprime_tower:\n  edge_mm: 6.0\n")
    data = _load(local=local)
    assert data["prime_tower"]["edge_mm"] == 6.0
    assert data["prime_tower"]["part_clearance_mm"] == 8.0


def test_an_unknown_preset_is_refused():
    with pytest.raises(settings.SettingsError, match="spacing must be one of"):
        _load({"PRINT_HANDY__LAYOUT__SPACING": "tiny"})
