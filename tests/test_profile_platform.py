"""#384: reading the gateway platform switch in the Hermes profile config.

The incident: platforms.discord.enabled was false in the profile config, so
the Hermes gateway never connected Discord and attachment intake was silently
absent — credentials do not override an explicit platform disable, and the
gateway only logged a warning. Print Buddy never writes this file; these
tests pin the reader the check surfaces (bot check, doctor) rely on.
"""
import copy

import pytest

from print_buddy.hermes import _config


@pytest.fixture
def profile(tmp_path):
    previous = copy.deepcopy(_config.cfg())
    data = copy.deepcopy(previous)
    data["paths"]["hermes_home"] = tmp_path
    _config.set_override(data)
    yield tmp_path
    _config.set_override(previous)


def _write(profile, text):
    (profile / "config.yaml").write_text(text)


def test_missing_profile_config(profile):
    state, path = _config.profile_platform_state("discord")
    assert state == "missing"
    assert path == profile / "config.yaml"


def test_enabled_true(profile):
    _write(profile, "platforms:\n  discord:\n    enabled: true\n")
    assert _config.profile_platform_state("discord")[0] == "enabled"


def test_explicit_false_is_disabled(profile):
    _write(profile, "platforms:\n  discord:\n    enabled: false\n")
    assert _config.profile_platform_state("discord")[0] == "disabled"


def test_quoted_false_is_disabled(profile):
    _write(profile, 'platforms:\n  discord:\n    enabled: "false"\n')
    assert _config.profile_platform_state("discord")[0] == "disabled"


def test_no_platforms_section_is_unset(profile):
    _write(profile, "model:\n  default: test\n")
    assert _config.profile_platform_state("discord")[0] == "unset"


def test_platform_without_enabled_key_is_unset(profile):
    _write(profile, "platforms:\n  discord:\n    gateway_restart_notification: false\n")
    assert _config.profile_platform_state("discord")[0] == "unset"


def test_unparseable_config_is_unreadable(profile):
    _write(profile, "platforms: [unclosed\n")
    assert _config.profile_platform_state("discord")[0] == "unreadable"


def test_non_mapping_config_is_unreadable(profile):
    _write(profile, "- just\n- a\n- list\n")
    assert _config.profile_platform_state("discord")[0] == "unreadable"


def test_shipped_template_enables_the_platform():
    """Root-cause guard: the template the installer renders can only ever
    create the profile with the Discord platform on."""
    import yaml
    from pathlib import Path
    text = (Path(__file__).parents[1] / "hermes" / "profile" / "config.yaml.template").read_text()
    data = yaml.safe_load(text)
    assert data["platforms"]["discord"]["enabled"] is True
