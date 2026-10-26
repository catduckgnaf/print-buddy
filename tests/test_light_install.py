"""Light installer and setup wizard: offline checks (no network, no apt, no systemd, no real Hermes)."""
import io
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from print_buddy import printers, settings, setup_wizard as sw

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-light.sh"
PERMS = 274878024704  # View Channels, Send Messages (+threads), Embed Links, Attach Files, Read Message History


def wizard(answers=None, typed="", yes=False):
    return sw.Wizard(answers or {}, io.StringIO(typed), io.StringIO(), yes, environ={})


BASE = {"has_printer_software": "yes", "moonraker_url": "http://printer.local:7125", "nozzle_diameter_mm": "0.4",
        "material": "PLA", "install_slicer": "yes", "spoolman": "skip", "camera": "no", "have_bot": "yes",
        "discord_app_id": "123", "discord_chat_id": "111", "discord_user_ids": "222, 333", "bot_name": "Printy",
        "discord_bot_token": "SECRET-TOKEN", "hermes": "no"}


def plan_for(**extra):
    w = wizard({**BASE, **extra}, yes=True)
    return sw.build_plan(w), w


def test_brand_menu_lists_every_registry_vendor_and_other():
    w = wizard({"brand": "1", "model": "1"}, yes=True)
    sw.choose_printer(w)
    out = w.output.getvalue()
    for vendor in printers.VENDORS.values():
        assert vendor.label in out
    assert "Other / generic" in out


@pytest.mark.parametrize("key", list(printers.MODELS))
def test_every_registry_model_is_reachable_by_brand_then_model(key):
    picked, overrides, _ = sw.choose_printer(wizard({"brand": key.split(".")[0], "model": key}, yes=True))
    assert picked == key and overrides == {}


def test_other_model_of_a_known_brand_asks_firmware_and_build_volume():
    picked, overrides, name = sw.choose_printer(wizard(
        {"brand": "sovol", "model": "other", "firmware": "klipper", "bed_x": "300", "bed_y": "310", "bed_z": "340"},
        yes=True))
    assert picked == "klipper.generic"
    assert overrides["bed_mm"] == [300.0, 310.0] and overrides["max_print_height_mm"] == 340.0
    assert name == "Sovol printer"


def test_other_brand_marlin_uses_octoprint():
    plan, _ = plan_for(brand="other", firmware="octoprint", octoprint_url="http://octopi.local",
                       octoprint_api_key="OP-KEY")
    assert plan["config"]["printer"]["model"] == "octoprint.marlin"
    assert plan["config"]["services"]["octoprint_url"] == "http://octopi.local"
    assert plan["secrets"]["OCTOPRINT_API_KEY"] == "OP-KEY"


def test_bambu_defaults_to_bambu_studio_and_has_no_connection():
    plan, _ = plan_for(brand="bambulab", model="bambulab.a1")
    assert plan["slicer"] == "bambu_studio"
    assert plan["flatpaks"] == ["com.bambulab.BambuStudio"]
    assert "moonraker_url" not in plan["config"]["services"]
    # LAN status is opt-in in the wizard and off by default: no [bambu] section, no secret.
    assert "bambu" not in plan["config"] and plan["secrets"]["BAMBU_LAN_PASSWORD"] == ""
    assert any("you start the print yourself" in n for n in plan["notes"])


@pytest.mark.parametrize("key", ["sovol.sv06", "flashforge.ad5x", "klipper.generic"])
def test_non_bambu_printers_use_orca(key):
    plan, _ = plan_for(brand=key.split(".")[0], model=key)
    assert plan["slicer"] == "orca" and plan["flatpaks"] == ["com.orcaslicer.OrcaSlicer"]


@pytest.mark.parametrize("key", list(printers.MODELS))
def test_wizard_config_passes_settings_validation(tmp_path, key):
    extra = {"brand": key.split(".")[0], "model": key}
    if key.startswith("octoprint"):
        extra["octoprint_url"] = "http://octopi.local"
    plan, w = plan_for(**extra)
    local = tmp_path / "local.yaml"
    assert sw.merge_config(local, plan["config"], w)
    data = settings.load(local=local, environ={})
    assert data["printer"]["model"] == key
    assert data["bot"]["mode"] == "standalone"
    assert data["discord"]["allowed_user_ids"] == "222, 333"


def test_other_generic_config_passes_settings_validation(tmp_path):
    plan, w = plan_for(brand="other", firmware="klipper", printer_name="Ender", bed_x="235", bed_y="235",
                       bed_z="250")
    local = tmp_path / "local.yaml"
    sw.merge_config(local, plan["config"], w)
    data = settings.load(local=local, environ={})
    assert data["printer"]["bed_mm"] == [235.0, 235.0] and data["printer"]["name"] == "Ender"


def test_missing_klipper_offers_kiauh_and_spoolman_install():
    plan, _ = plan_for(brand="klipper", model="klipper.generic", has_printer_software="no", spoolman="install")
    labels = [label for label, _ in plan["actions"]]
    assert any("KIAUH" in l for l in labels) and any("Spoolman" in l for l in labels)
    assert plan["config"]["services"]["spoolman_url"] == "http://localhost:7912"


def test_camera_default_follows_moonraker_host_and_timelapse_note():
    plan, w = plan_for(brand="klipper", model="klipper.generic", camera="yes", timelapse="yes")
    assert plan["config"]["services"]["camera_snapshot_url"] == "http://printer.local/webcam/?action=snapshot"
    assert any("moonraker-timelapse" in n for n in plan["notes"])


def test_bad_url_in_answers_stops_with_a_clear_error():
    with pytest.raises(SystemExit, match="moonraker_url"):
        plan_for(brand="klipper", model="klipper.generic", moonraker_url="printer.local")


def test_typed_answers_retry_until_valid():
    w = sw.Wizard({}, io.StringIO("9\n2\n"), io.StringIO(), False, environ={})
    assert w.menu("x", "Pick:", ["a", "b"], "a") == "b"
    assert "Pick 1 to 2" in w.output.getvalue()


def test_invite_permissions_are_the_named_flags():
    perms = sw.discord_permissions()
    assert sum(perms.values()) == PERMS
    assert "Administrator" not in perms
    assert sw.discord_invite_url("42") == (
        f"https://discord.com/oauth2/authorize?client_id=42&scope=bot+applications.commands&permissions={PERMS}")


def test_discord_steps_shown_only_without_a_bot():
    _, w = plan_for(brand="sovol", model="sovol.sv06", have_bot="no")
    assert "MESSAGE CONTENT" in w.output.getvalue()
    _, w = plan_for(brand="sovol", model="sovol.sv06")
    assert "MESSAGE CONTENT" not in w.output.getvalue()


def test_token_is_never_printed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    plan, w = plan_for(brand="klipper", model="klipper.generic")
    plan["data_home"] = str(tmp_path / "data")
    calls = []
    sw.apply(plan, w, repo=ROOT, python="/usr/bin/python3", local=tmp_path / "local.yaml",
             runner=lambda cmd: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    out = w.output.getvalue() + sw.summary(plan)
    assert "SECRET-TOKEN" not in out
    env = tmp_path / "data" / ".env"
    assert "DISCORD_BOT_TOKEN=SECRET-TOKEN" in env.read_text()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert any("install-standalone.sh" in c[0] for c in calls)


def test_existing_env_values_and_config_keys_are_kept(tmp_path):
    (tmp_path / ".env").write_text("DISCORD_BOT_TOKEN=OLD\nOCTOPRINT_API_KEY=\n")
    changed = sw.update_env(tmp_path, {"DISCORD_BOT_TOKEN": "NEW", "OCTOPRINT_API_KEY": "K"})
    assert changed == ["OCTOPRINT_API_KEY"]
    assert "DISCORD_BOT_TOKEN=OLD" in (tmp_path / ".env").read_text()
    local = tmp_path / "local.yaml"
    local.write_text("printer:\n  model: sovol.sv06\n")
    w = wizard({"merge_config": "no"}, yes=True)
    assert not sw.merge_config(local, {"printer": {"model": "klipper.generic", "name": "x"}}, w)
    assert local.read_text() == "printer:\n  model: sovol.sv06\n"
    assert "name: x" in w.output.getvalue()
    w = wizard({"merge_config": "yes"}, yes=True)
    assert sw.merge_config(local, {"printer": {"model": "klipper.generic", "name": "x"}}, w)
    assert yaml.safe_load(local.read_text())["printer"] == {"model": "sovol.sv06", "name": "x"}


def _fake_hermes(tmp_path, profiles=""):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "hermes"
    exe.write_text(f"#!/bin/sh\n[ \"$1 $2\" = 'profile list' ] && printf '%s\\n' '{profiles}'\nexit 0\n")
    exe.chmod(0o755)
    return bin_dir


def test_hermes_profile_list_is_parsed_from_a_fake_hermes(tmp_path):
    bin_dir = _fake_hermes(tmp_path, " ◆ 3D Printing (3dprinting)    running")
    assert sw.hermes_profiles({"PATH": f"{bin_dir}:/usr/bin:/bin"}) == {"3dprinting"}


def test_hermes_mode_creates_profile_runs_installer_and_skips_standalone(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    plan, w = plan_for(brand="klipper", model="klipper.generic", hermes="yes", profile="printer3d")
    assert plan["config"]["bot"]["mode"] == "hermes"
    assert plan["config"]["paths"]["hermes_home"] == "~/.hermes/profiles/printer3d"
    calls = []
    sw.apply(plan, w, repo=ROOT, python="/usr/bin/python3", local=tmp_path / "local.yaml",
             runner=lambda cmd: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    flat = [" ".join(str(x) for x in c) for c in calls]
    assert any(c.startswith("hermes profile create printer3d --description") for c in flat)
    assert any("install-hermes.sh --hermes-home" in c and "DISCORD_CHANNEL_ID=111" in c for c in flat)
    assert not any("install-standalone.sh" in c or "systemctl" in c for c in flat)
    env = (tmp_path / ".hermes" / "profiles" / "printer3d" / ".env").read_text()
    assert "DISCORD_BOT_TOKEN=SECRET-TOKEN" in env and "DISCORD_ALLOWED_USERS=222,333" in env
    assert "DISCORD_HOME_CHANNEL=111" in env
    assert "SECRET-TOKEN" not in w.output.getvalue()


def test_existing_hermes_profile_is_reused_not_recreated():
    cmds = sw.build_hermes_commands("3dprinting", "Sovol SV06", ROOT, "/usr/bin/python3", profile_exists=True)
    assert not any(c[:3] == ["hermes", "profile", "create"] for c in cmds)
    assert any("install-hermes.sh" in " ".join(c) for c in cmds)


def test_answers_file_formats(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("# comment\nbrand: sovol\nMODEL=sovol.sv06\nmoonraker_url: http://x:7125\n")
    assert sw.parse_answers(f) == {"brand": "sovol", "model": "sovol.sv06", "moonraker_url": "http://x:7125"}


def test_main_dry_run_with_answers_changes_nothing(tmp_path, monkeypatch):
    f = tmp_path / "answers.yaml"
    f.write_text(yaml.safe_dump({**BASE, "brand": "sovol", "model": "sovol.sv06"}))
    monkeypatch.setattr(sw.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(sw.Path, "home", classmethod(lambda cls: tmp_path))
    before = sorted(p.name for p in (ROOT / "config").iterdir())
    assert sw.main(["--answers", str(f), "--dry-run", "--yes"]) == 0
    assert sorted(p.name for p in (ROOT / "config").iterdir()) == before
    assert list(tmp_path.iterdir()) == [f]


def test_installer_shell_syntax_and_options():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    text = SCRIPT.read_text()
    assert text.rstrip().endswith('main "$@"'), "curl | bash must read the whole script first"
    for flag in ("--ref", "--dir", "--answers", "--yes", "--dry-run", "--uninstall", "--purge"):
        assert flag in text
    assert "setup_wizard" in text and "sudo apt-get" in text


def test_installer_rejects_purge_without_uninstall():
    r = subprocess.run(["bash", str(SCRIPT), "--purge"], capture_output=True, text=True)
    assert r.returncode != 0 and "--purge only works with --uninstall" in r.stderr


def test_uninstall_dry_run_touches_nothing(tmp_path):
    units = tmp_path / "units"
    units.mkdir()
    (units / "print-buddy-bot.service").write_text("x")
    env = {**os.environ, "SYSTEMD_USER_DIR": str(units), "NO_SYSTEMCTL": "1", "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(SCRIPT), "--uninstall", "--dry-run", "--dir", str(tmp_path / "pb")],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert (units / "print-buddy-bot.service").exists()
    assert "rm -f" in r.stdout


def test_docs_and_readme_point_at_the_installer():
    readme = (ROOT / "README.md").read_text()
    assert "scripts/install-light.sh | bash" in readme
    assert "--ref 2.1.4" in readme
    assert (ROOT / "docs" / "INSTALL-LIGHT.md").exists()
    discord = (ROOT / "docs" / "DISCORD-BOT-SETUP.md").read_text()
    assert f"permissions={PERMS}" in discord and "MESSAGE CONTENT" in discord
