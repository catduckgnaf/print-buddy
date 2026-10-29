"""#574: the plugin's hosting-profile identity is derived, not the literal '3dprinting'.

Hermes mode keeps the dedicated profile (#566 verdict (d)): unmatched and
natural-language messages reach the hosting profile's agent by design, and
the profile bounds that agent. But the name is the operator's choice, so
the gates compare events and sessions against the identity derived from
the install (paths.hermes_home in a profiles layout, or the profile the
plugin symlink lives in). These tests pin: derivation, identical behaviour
for an existing '3dprinting' install, end-to-end gates under a differently
named dedicated profile, the preserved "other profiles are not conflated"
property, named (never silent) guard stand-down, and the bot check row.
"""
import asyncio
import copy
import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace as S
from unittest import mock

import pytest

from print_handy import settings
from print_handy.hermes import _config

SPEC = importlib.util.spec_from_file_location(
    "print_feedback_hosting", Path(__file__).parents[2] / "plugins/print-feedback/__init__.py")
assert SPEC is not None and SPEC.loader is not None
plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin)


def setup_function():
    plugin._identity_warnings.clear()
    plugin._tool_turns.clear()


@pytest.fixture
def hosting(tmp_path):
    """Install a settings copy whose hermes_home is <tmp>/profiles/printshop; restore after."""
    previous = copy.deepcopy(_config.cfg())
    data = copy.deepcopy(previous)
    home = tmp_path / "profiles" / "printshop"
    data["paths"]["hermes_home"] = home
    data["bot"]["mode"] = "hermes"
    _config.set_override(data)
    yield home
    _config.set_override(previous)


def event_for(profile, text="hello"):
    source = S(platform=S(value="discord"), profile=profile, user_id="u", chat_id="c",
               thread_id=None, is_bot=False, profile_route_rejected=False)
    return S(source=source, text=text, internal=False, message_id="m1", metadata={})


GATEWAY = S(_is_user_authorized_for_source=lambda _s: True,
            _delivery_adapter_for=lambda _s: object(),
            _session_key_for_source=lambda _s: "discord:c::u")


# ---------------------------------------------------------------- derivation

def test_derives_the_profile_name_from_a_profiles_layout_home(tmp_path):
    home = tmp_path / "profiles" / "printshop"
    assert _config.hosting_profile(home=home, mode="hermes") == ("printshop", True)
    default = tmp_path / ".hermes" / "profiles" / "3dprinting"
    assert _config.hosting_profile(home=default, mode="hermes") == ("3dprinting", True)


def test_a_data_root_home_derives_nothing(tmp_path):
    # Docker's /data/hermes shape: a data root, not a profile directory.
    assert _config.hosting_profile(home=tmp_path / "hermes", mode="hermes") == (_config.DEFAULT_PROFILE, False)
    assert _config.hosting_profile(home=tmp_path / "profiles", mode="hermes") == (_config.DEFAULT_PROFILE, False)


def test_derives_from_the_plugin_install_symlink(tmp_path):
    real = tmp_path / "repo" / "plugins" / "print-feedback"
    real.mkdir(parents=True)
    (real / "__init__.py").write_text("")
    profile = tmp_path / "profiles" / "workshop"
    link = profile / "plugins" / "print-feedback"
    link.parent.mkdir(parents=True)
    link.symlink_to(real, target_is_directory=True)
    name, derived = _config.hosting_profile(
        plugin_file=link / "__init__.py", home=tmp_path / "hermes", mode="hermes")
    assert (name, derived) == ("workshop", True)


def test_a_real_plugin_folder_is_not_an_install_location(tmp_path):
    folder = tmp_path / "profiles" / "workshop" / "plugins" / "print-feedback"
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text("")
    assert _config.hosting_profile(
        plugin_file=folder / "__init__.py", home=tmp_path / "hermes", mode="hermes") == (_config.DEFAULT_PROFILE, False)


def test_settings_home_wins_over_the_plugin_location(tmp_path):
    real = tmp_path / "repo" / "plugins" / "print-feedback"
    real.mkdir(parents=True)
    (real / "__init__.py").write_text("")
    profile = tmp_path / "profiles" / "workshop"
    link = profile / "plugins" / "print-feedback"
    link.parent.mkdir(parents=True)
    link.symlink_to(real, target_is_directory=True)
    assert _config.hosting_profile(
        plugin_file=link / "__init__.py",
        home=tmp_path / "profiles" / "printshop", mode="hermes") == ("printshop", True)


def test_standalone_mode_never_derives(tmp_path):
    # A standalone runtime stamps every event DEFAULT_PROFILE (bot.runtime.PROFILE);
    # deriving "printshop" from its hermes_home made every command unmatched.
    home = tmp_path / "profiles" / "printshop"
    assert _config.hosting_profile(home=home, mode="standalone") == (_config.DEFAULT_PROFILE, False)


def test_standalone_install_in_a_profiles_layout_answers_the_runtime_stamp(tmp_path):
    from print_handy.bot import runtime
    previous = copy.deepcopy(_config.cfg())
    data = copy.deepcopy(previous)
    data["paths"]["hermes_home"] = tmp_path / "profiles" / "printshop"
    data["bot"]["mode"] = "standalone"
    _config.set_override(data)
    try:
        assert plugin._hosting_profile() == runtime.PROFILE
        assert plugin._is_print_discord_event(event_for(runtime.PROFILE)) is True
    finally:
        _config.set_override(previous)


# ------------------------------------------------- identical for '3dprinting'

def test_default_install_gates_behave_as_the_literal_did():
    # Under the stock test settings nothing derives, so the fallback
    # identity is the shipped default — the old comparison's outcome.
    assert plugin._hosting_profile() == "3dprinting"
    assert plugin._is_print_discord_event(event_for("3dprinting")) is True
    assert plugin._is_print_discord_event(event_for("default")) is False
    assert plugin._is_print_discord_event(event_for(None)) is False
    assert plugin._discord_operator(event_for("3dprinting"), GATEWAY) is not None
    assert plugin._discord_operator(event_for("default"), GATEWAY) is None


# -------------------------------------------- a differently named profile

def test_gates_answer_the_renamed_hosting_profile(hosting):
    assert plugin._hosting_profile() == "printshop"
    assert plugin._is_print_discord_event(event_for("printshop")) is True
    assert plugin._discord_operator(event_for("printshop"), GATEWAY) is not None


def test_other_profiles_are_not_conflated_under_the_derived_identity(hosting):
    # The guard tests' property, against the derived identity: the old
    # literal name is now just another profile, and is refused.
    assert plugin._is_print_discord_event(event_for("3dprinting")) is False
    assert plugin._is_print_discord_event(event_for("default")) is False
    assert plugin._discord_operator(event_for("3dprinting"), GATEWAY) is None


def _session_as(profile, platform="discord"):
    return mock.patch.object(plugin, "_session", side_effect=lambda key: {
        "HERMES_SESSION_PLATFORM": platform,
        "HERMES_SESSION_PROFILE": profile}.get(key, ""))


def test_guards_are_active_under_the_renamed_profile(hosting):
    args = {"command": "status"}
    with _session_as("printshop"):
        assert plugin.guard_terminal_loop(
            tool_name="terminal", args=args, session_id="s", turn_id="t") is None
        assert plugin.guard_terminal_loop(
            tool_name="terminal", args=args, session_id="s", turn_id="t") is None
        blocked = plugin.guard_terminal_loop(
            tool_name="terminal", args=args, session_id="s", turn_id="t")
    assert blocked is not None and "repeat" in blocked["message"]
    with _session_as("printshop"):
        result = plugin.cap_discord_clarifications(tool_name="clarify", args={
            "questions": [{"question": "Pick", "choices": list("abcdef")}]})
    assert result["action"] == "modify"
    assert result["args"]["questions"][0]["choices"] == list("abcd")


def test_guard_stand_down_for_another_profile_is_named(hosting, caplog):
    args = {"command": "status"}
    with _session_as("3dprinting"), caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert plugin.guard_terminal_loop(
                tool_name="terminal", args=args, session_id="s", turn_id="t") is None
    warnings = [r for r in caplog.records if "standing down" in r.getMessage()]
    assert len(warnings) == 1  # once per process, not per call
    assert "'3dprinting'" in warnings[0].getMessage()
    assert "'printshop'" in warnings[0].getMessage()


def test_clarify_cap_stand_down_is_named(hosting, caplog):
    with _session_as("default"), caplog.at_level(logging.WARNING):
        assert plugin.cap_discord_clarifications(tool_name="clarify", args={
            "questions": [{"question": "Pick", "choices": list("abcdef")}]}) is None
    warnings = [r for r in caplog.records if "standing down" in r.getMessage()]
    assert len(warnings) == 1
    assert "cap_discord_clarifications" in warnings[0].getMessage()


# ---------------------------------------------------------------- bot check

def _check_output(monkeypatch, capsys, tmp_path, hermes_home):
    from print_handy.bot import __main__ as bot_main
    cfg = settings.load(local=Path("/dev/null"), environ={})
    cfg["bot"]["mode"] = "hermes"
    cfg["paths"]["hermes_home"] = hermes_home
    monkeypatch.setattr(settings, "current", lambda: cfg)
    monkeypatch.setattr(_config, "cfg", lambda: cfg)
    monkeypatch.setattr(_config, "profile_env_value",
                        lambda name, **kw: "token-present" if name == "DISCORD_BOT_TOKEN" else "")
    bot_main.check()
    return capsys.readouterr().out


def test_bot_check_names_the_derived_hosting_profile(monkeypatch, capsys, tmp_path):
    out = _check_output(monkeypatch, capsys, tmp_path, tmp_path / "profiles" / "printshop")
    assert "ok    hosting profile" in out
    assert "printshop" in out


def test_bot_check_fails_when_the_hosting_profile_cannot_be_derived(monkeypatch, capsys, tmp_path):
    out = _check_output(monkeypatch, capsys, tmp_path, tmp_path / "profile")
    assert "FAIL  hosting profile" in out
    assert "paths.hermes_home" in out
