"""The checked-in home config is kept valid and in step with the Orca templates."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from print_buddy import settings
from print_buddy.core import orca_adapter, plate_merge, slice_guard


class HomeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.home = settings.load(local=False)
        self.machine = json.loads((self.home["orca"]["templates"] / "machine.json").read_text())

    def test_home_file_is_the_ad5x(self):
        printer = self.home["printer"]
        self.assertEqual(printer["bed_mm"], [220.0, 220.0])
        self.assertEqual(printer["ifs_slots"], 4)
        self.assertEqual(printer["nozzle_diameter_mm"], 0.4)
        self.assertEqual(self.home["orca"]["command"], ["flatpak", "run", "com.orcaslicer.OrcaSlicer"])
        self.assertTrue(self.home["visual_watch"]["enabled"])

    def test_bed_matches_orca_printable_area(self):
        corners = [tuple(float(v) for v in c.split("x")) for c in self.machine["printable_area"]]
        width = max(x for x, _ in corners) - min(x for x, _ in corners)
        depth = max(y for _, y in corners) - min(y for _, y in corners)
        self.assertEqual([width, depth], self.home["printer"]["bed_mm"])

    def test_height_and_nozzle_match_orca_machine(self):
        self.assertEqual(float(self.machine["printable_height"]), self.home["printer"]["max_print_height_mm"])
        self.assertEqual(float(self.machine["nozzle_diameter"][0]), self.home["printer"]["nozzle_diameter_mm"])

    def test_templates_folder_has_all_three_profiles(self):
        for name in ("machine", "process", "filament"):
            self.assertTrue((self.home["orca"]["templates"] / f"{name}.json").is_file(), name)

    def test_alpha_app_id_override_preserves_stable_default(self):
        stable_settings = settings.load(local=False, environ={})
        with mock.patch.object(orca_adapter, "_S", stable_settings):
            with mock.patch.dict(os.environ, {"ORCA_FLATPAK_APP_ID": "org.orcaslicer.OrcaSlicer.Alpha"}, clear=True):
                self.assertEqual(orca_adapter._orca_command(),
                                 ["flatpak", "run", "org.orcaslicer.OrcaSlicer.Alpha"])
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(orca_adapter._orca_command(),
                                 ["flatpak", "run", "com.orcaslicer.OrcaSlicer"])

    def test_pinned_commit_keeps_stable_app_id(self):
        stable_settings = settings.load(local=False, environ={})
        with mock.patch.object(orca_adapter, "_S", stable_settings):
            with mock.patch.dict(os.environ, {"ORCA_FLATPAK_COMMIT": "a" * 64}, clear=True):
                self.assertEqual(orca_adapter._orca_command(),
                                 ["flatpak", "run", f"--commit={'a' * 64}", "com.orcaslicer.OrcaSlicer"])

    def test_core_uses_the_settings(self):
        current = settings.current()
        self.assertEqual(orca_adapter.BED, current["printer"]["bed_mm"])
        self.assertEqual(orca_adapter.SINGLE_COPY_EDGE_MM, current["layout"]["single_copy_edge_mm"])
        self.assertEqual(plate_merge.IFS_SLOTS, current["printer"]["ifs_slots"])
        self.assertTrue(slice_guard.pre_slice(bounds=(0, 0, 219, 219), tool_slots={0: 1}).ok)
        self.assertEqual(orca_adapter.ORCA_COMMAND, current["orca"]["command"])


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def toml(self, text, name="local.toml"):
        path = self.dir / name
        path.write_text(text)
        return path

    def test_yaml_local_file_overrides_key_by_key(self):
        path = self.toml("printer:\n  ifs_slots: 2\nlayout:\n  multi_copy_edge_mm: 4\n", "local.yaml")
        data = settings.load(local=path, environ={})
        self.assertEqual(data["printer"]["ifs_slots"], 2)
        self.assertEqual(data["layout"]["multi_copy_edge_mm"], 4)
        self.assertEqual(data["layout"]["single_copy_edge_mm"], 1)

    def test_yaml_rejects_unknown_keys(self):
        path = self.toml("services:\n  moonraker_urll: http://printer.test\n", "local.yaml")
        with self.assertRaisesRegex(settings.SettingsError, "unknown setting"):
            settings.load(local=path, environ={})

    def test_yaml_parse_error_names_file(self):
        path = self.toml("printer: [\n", "broken.yaml")
        with self.assertRaisesRegex(settings.SettingsError, "broken.yaml"):
            settings.load(local=path, environ={})

    def test_yaml_and_legacy_toml_local_precedence_is_yaml_first(self):
        toml_path = self.toml("[layout]\nmulti_copy_edge_mm = 4\n", "local.toml")
        yaml_path = self.toml("layout:\n  multi_copy_edge_mm: 6\n", "local.yaml")
        with mock.patch.object(settings, "LOCAL", yaml_path), mock.patch.object(settings, "LEGACY_LOCAL", toml_path):
            data = settings.load(local=None, environ={})
        self.assertEqual(data["layout"]["multi_copy_edge_mm"], 6)

    def test_explicit_config_path_selects_yaml(self):
        path = self.toml("visual_watch:\n  enabled: false\n", "selected.yaml")
        data = settings.load(local=None, environ={"PRINT_BUDDY_CONFIG": str(path)})
        self.assertFalse(data["visual_watch"]["enabled"])

    def test_environment_overrides_yaml(self):
        path = self.toml("visual_watch:\n  sensitivity: 2\n", "local.yaml")
        data = settings.load(local=path, environ={"PRINT_BUDDY__VISUAL_WATCH__SENSITIVITY": "4"})
        self.assertEqual(data["visual_watch"]["sensitivity"], 4)

    def test_yaml_boolean_enabled_defaults_to_legacy_behavior(self):
        path = self.toml("visual_watch:\n  sensitivity: 3\n", "local.yaml")
        data = settings.load(local=path, environ={})
        self.assertIs(data["visual_watch"]["enabled"], True)

    def test_yaml_boolean_enabled_false_is_preserved(self):
        path = self.toml("visual_watch:\n  enabled: false\n", "local.yaml")
        data = settings.load(local=path, environ={})
        self.assertIs(data["visual_watch"]["enabled"], False)

    def test_yaml_boolean_enabled_can_be_opted_in(self):
        path = self.toml("visual_watch:\n  enabled: true\n", "local.yaml")
        data = settings.load(local=path, environ={})
        self.assertIs(data["visual_watch"]["enabled"], True)

    def test_yaml_home_preserves_effective_legacy_toml_values(self):
        yaml_data = settings.load(home=settings.HOME, local=False, environ={})
        toml_data = settings.load(home=settings.LEGACY_HOME, local=False, environ={})
        self.assertEqual(yaml_data, toml_data)

    def test_legacy_home_toml_is_used_when_yaml_is_absent(self):
        home = self.toml(Path(settings.LEGACY_HOME).read_text(), "home.toml")
        yaml_home = self.dir / "home.yaml"
        with mock.patch.object(settings, "HOME", yaml_home), mock.patch.object(settings, "LEGACY_HOME", home):
            data = settings.load(home=None, local=False, environ={})
        self.assertEqual(data["printer"]["model"], "flashforge.ad5x")
        self.assertIs(data["visual_watch"]["enabled"], True)

    def test_legacy_local_toml_is_used_when_yaml_is_absent(self):
        home = self.toml(Path(settings.HOME).read_text(), "home.yaml")
        local = self.toml("[layout]\nmulti_copy_edge_mm = 6\n", "local.toml")
        missing_yaml = self.dir / "local.yaml"
        with mock.patch.object(settings, "HOME", home), mock.patch.object(settings, "LOCAL", missing_yaml), mock.patch.object(settings, "LEGACY_LOCAL", local):
            data = settings.load(home=home, local=None, environ={})
        self.assertEqual(data["layout"]["multi_copy_edge_mm"], 6.0)

    def test_yaml_can_enable_visual_watch_with_legacy_home_toml(self):
        home = self.toml(Path(settings.LEGACY_HOME).read_text(), "legacy-home.toml")
        local = self.toml("visual_watch:\n  enabled: true\n", "local.yaml")
        data = settings.load(home=home, local=local, environ={})
        self.assertIs(data["visual_watch"]["enabled"], True)

    def test_env_can_enable_visual_watch_with_legacy_home_toml(self):
        home = self.toml(Path(settings.LEGACY_HOME).read_text(), "legacy-home.toml")
        data = settings.load(home=home, local=False, environ={"PRINT_BUDDY__VISUAL_WATCH__ENABLED": "true"})
        self.assertIs(data["visual_watch"]["enabled"], True)
        disabled = settings.load(home=home, local=False, environ={"PRINT_BUDDY__VISUAL_WATCH__ENABLED": "false"})
        self.assertIs(disabled["visual_watch"]["enabled"], False)
        with self.assertRaisesRegex(settings.SettingsError, "must be true or false"):
            settings.load(home=home, local=False, environ={"PRINT_BUDDY__VISUAL_WATCH__ENABLED": "sometimes"})

    def test_settings_inventory_covers_every_model_default_key(self):
        inventory = settings.load(home=settings.HOME, local=False, environ={})
        expected = {
            "printer": {"name", "firmware", "start_macro", "end_macro", "bed_mm",
                        "max_print_height_mm", "nozzle_diameter_mm", "ifs_slots", "model", "vendor", "slicer"},
            "layout": {"single_copy_edge_mm", "multi_copy_edge_mm", "merge_edge_margin_mm", "merge_spacing_mm", "max_merged_hours"},
            "prime_tower": {"size_mm", "part_clearance_mm", "edge_mm", "merge_slack_mm"},
            "cold_pull": {"pla_trial", "petg"},
            "orca": {"templates", "command"},
            "bambu": {"command", "lan_host", "lan_serial", "lan_access_code_env", "start_confirm_s"},
            "slicer": {"flash_studio_path"},
            "flashforge_stock": {"host"},
            "prusa": {"link_host", "api_key_env"},
            "elegoo_sdcp": {"host"},
            "paths": {"hermes_home", "archive", "records_vault", "cache", "hermes_bin", "ffmpeg",
                      "hermes_agent", "hermes_restart_helper"},
            "services": {"moonraker_url", "moonraker_ws_url", "camera_snapshot_url", "camera_source",
                         "spoolman_url", "openviking_url", "vision_chat_url", "stock_api_port"},
            "discord": {"chat_id", "approval_user_id", "upload_max_bytes", "post_print_quiet_s",
                        "daily_reset_hour", "timezone", "bot_name", "question_timeout_s",
                        "safety_confirm_timeout_s", "upload_wait_s", "cold_pull_outcome_s",
                        "token_env", "allowed_user_ids"},
            "telegram": {"token_env", "chat_id", "allowed_user_ids", "approval_user_id", "upload_max_bytes"},
            "matrix": {"homeserver_url", "access_token_env", "room_id", "allowed_user_ids",
                       "approval_user_id", "bot_user_id", "upload_max_bytes"},
            "bot": {"mode", "platform", "health_port", "health_stale_s", "sync_commands"},
            "llm": {"chat_url", "model", "api_key_env", "timeout_s"},
            "listener": {"tick_s", "ifs_presence_poll_s", "spool_nag_s", "start_claim_ttl_s"},
            "vision": {"model", "roast_model"},
            "visual_watch": {"enabled", "sensitivity"},
            "timelapse": {"mode", "encoder", "archive_host", "archive_dir", "ssh_key", "render_wait_s", "render_poll_s",
                          "max_bytes", "local_retention_days", "plan_clip_retention_days",
                          "vertical_short", "vertical_short_mode", "vertical_short_overlay",
                          "capture_enabled", "capture_source_url", "capture_trigger",
                          "capture_interval_s", "capture_max_frames", "capture_max_bytes",
                          "capture_encoder"},
            "logging": {"level", "format", "file"},
            "webui": {"enabled", "host", "port", "access_token_env"},
            "live_stream": {"enabled", "voice_channel_id", "auto_start_on_print", "max_height", "fps",
                            "max_bitrate_kbps", "encoder", "empty_timeout_s", "activity_origin"},
            "maintenance": {"quick_hours", "full_hours", "full_days"},
            "delivery": {"methods"},
            "nozzle_temp_offsets": {"brass", "hardened_steel", "stainless_steel", "ruby", "tungsten_carbide", "diamond"},
            "material_temps": {"PLA", "PETG", "ABS", "ASA", "TPU", "PA", "PC"},
        }
        # "printers" is the resolved [[printers]] roster (#333): a list, not a section, so it is
        # pinned separately below rather than as another expected section.
        self.assertEqual(set(inventory), set(expected) | {"printers"})
        for section, keys in expected.items():
            with self.subTest(section=section):
                self.assertEqual(set(inventory[section]), keys)
        self.assertTrue(all("security" not in key and "safety" not in key for key in inventory))
        # The roster synthesised from this legacy config mirrors the legacy view above: one
        # entry for the AD5X, its id the slug of the resolved [printer] name.
        roster = inventory["printers"]
        self.assertEqual(len(roster), 1)
        self.assertEqual(roster[0]["id"], "flashforge-ad5x")
        self.assertEqual(roster[0]["model"], inventory["printer"]["model"])
        self.assertEqual(roster[0]["name"], inventory["printer"]["name"])
        self.assertEqual(roster[0]["moonraker_url"], inventory["services"]["moonraker_url"])

    def test_bambu_start_confirm_window_defaults_and_limits(self):
        home = self.toml(Path(settings.LEGACY_HOME).read_text(), "legacy-home.toml")
        self.assertEqual(settings.load(home=home, local=False, environ={})["bambu"]["start_confirm_s"], 90)
        env = {"PRINT_BUDDY__BAMBU__START_CONFIRM_S": "120"}
        self.assertEqual(settings.load(home=home, local=False, environ=env)["bambu"]["start_confirm_s"], 120)
        # An older home file without the key still accepts it from the environment and from YAML.
        older = self.toml(Path(settings.LEGACY_HOME).read_text().replace("start_confirm_s = 90\n", ""), "older-home.toml")
        self.assertEqual(settings.load(home=older, local=False, environ={})["bambu"]["start_confirm_s"], 90)
        self.assertEqual(settings.load(home=older, local=False, environ=env)["bambu"]["start_confirm_s"], 120)
        local = self.toml("bambu:\n  start_confirm_s: 60\n", "local.yaml")
        self.assertEqual(settings.load(home=older, local=local, environ={})["bambu"]["start_confirm_s"], 60)
        for bad, message in (("0", "positive"), ("301", "at most 300")):
            with self.assertRaisesRegex(settings.SettingsError, message):
                settings.load(home=home, local=False, environ={"PRINT_BUDDY__BAMBU__START_CONFIRM_S": bad})
        with self.assertRaisesRegex(settings.SettingsError, "whole number"):
            settings.load(home=home, local=self.toml("bambu:\n  start_confirm_s: 12.5\n", "frac.yaml"), environ={})

    def test_timelapse_mode_derives_from_the_moonraker_url(self):
        # No Moonraker URL in the shipped home config: the derived default is off.
        self.assertEqual(settings.load(local=False, environ={})["timelapse"]["mode"], "off")
        with_moonraker = self.toml("services:\n  moonraker_url: http://printer.local:7125\n", "moonraker.yaml")
        self.assertEqual(settings.load(local=with_moonraker, environ={})["timelapse"]["mode"], "rendered")
        # An explicit value always wins over the derivation, and the
        # environment overrides the file like any other scalar.
        explicit = self.toml("timelapse:\n  mode: container\n", "container.yaml")
        self.assertEqual(settings.load(local=explicit, environ={})["timelapse"]["mode"], "container")
        off = self.toml("timelapse:\n  mode: 'off'\n", "off.yaml")
        self.assertEqual(settings.load(local=off, environ={})["timelapse"]["mode"], "off")
        env = {"PRINT_BUDDY__TIMELAPSE__MODE": "container"}
        self.assertEqual(settings.load(local=off, environ=env)["timelapse"]["mode"], "container")
        with self.assertRaisesRegex(settings.SettingsError, "timelapse.*mode"):
            settings.load(local=self.toml("timelapse:\n  mode: sometimes\n", "bad.yaml"), environ={})
        with self.assertRaisesRegex(settings.SettingsError, "timelapse.*mode"):
            settings.load(local=False, environ={"PRINT_BUDDY__TIMELAPSE__MODE": "sometimes"})

    def test_camera_source_defaults_to_auto_and_validates(self):
        self.assertEqual(settings.load(local=False, environ={})["services"]["camera_source"], "auto")
        for source in ("moonraker", "bambu", "go2rtc", "none"):
            local = self.toml(f"services:\n  camera_source: {source}\n", f"{source}.yaml")
            self.assertEqual(settings.load(local=local, environ={})["services"]["camera_source"], source)
        env = {"PRINT_BUDDY__SERVICES__CAMERA_SOURCE": "bambu"}
        self.assertEqual(settings.load(local=False, environ=env)["services"]["camera_source"], "bambu")
        with self.assertRaisesRegex(settings.SettingsError, "camera_source"):
            settings.load(local=self.toml("services:\n  camera_source: webcam\n", "bad.yaml"), environ={})
        with self.assertRaisesRegex(settings.SettingsError, "camera_source"):
            settings.load(local=False, environ={"PRINT_BUDDY__SERVICES__CAMERA_SOURCE": "webcam"})

    def test_docker_yaml_matches_legacy_toml_effective_settings(self):
        docker_yaml = settings.ROOT / "config" / "docker.yaml"
        docker_toml = settings.ROOT / "config" / "docker.toml"
        yaml_data = settings.load(home=settings.HOME, local=docker_yaml, environ={})
        toml_data = settings.load(home=settings.LEGACY_HOME, local=docker_toml, environ={})
        self.assertEqual(yaml_data, toml_data)

    def test_docker_default_selects_yaml_and_explicit_legacy_mount_selects_toml(self):
        import yaml
        import tomllib

        dockerfile = (settings.ROOT / "Dockerfile").read_text()
        compose = (settings.ROOT / "docker-compose.yml").read_text()
        self.assertIn("ENV PRINT_BUDDY_CONFIG=/app/config/docker.yaml", dockerfile)
        self.assertIn("PRINT_BUDDY_CONFIG: ${PRINT_BUDDY_CONFIG:-/app/config/docker.yaml}", compose)
        self.assertIn("/app/config/docker.toml", compose)
        env = (settings.ROOT / ".env.example").read_text()
        self.assertIn("PRINT_BUDDY_CONFIG=/app/config/docker.toml", env)
        yaml_data = yaml.safe_load((settings.ROOT / "config/docker.yaml").read_text())
        toml_data = tomllib.loads((settings.ROOT / "config/docker.toml").read_text())
        self.assertEqual(yaml_data["orca"], toml_data["orca"])
        self.assertEqual(yaml_data["paths"], toml_data["paths"])
        self.assertEqual(yaml_data["services"], toml_data["services"])
        self.assertEqual(yaml_data["printer"], toml_data["printer"])

    def test_gitignore_preserves_yaml_and_legacy_local_configuration(self):
        result = subprocess.run(
            ["git", "check-ignore", "-v", "config/local.yaml", "config/local.toml"],
            cwd=settings.ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("config/local.yaml", result.stdout)
        self.assertIn("config/local.toml", result.stdout)

    def test_local_file_overrides_key_by_key(self):
        data = settings.load(local=self.toml("[printer]\nifs_slots = 1\n"))
        self.assertEqual(data["printer"]["ifs_slots"], 1)
        self.assertEqual(data["printer"]["bed_mm"], [220.0, 220.0])

    def test_env_var_points_at_another_file(self):
        path = self.toml("[layout]\nmulti_copy_edge_mm = 5\n", "docker.toml")
        with mock.patch.dict(os.environ, {"PRINT_BUDDY_CONFIG": str(path)}):
            self.assertEqual(settings.load()["layout"]["multi_copy_edge_mm"], 5.0)

    def test_env_var_to_missing_file_fails_loudly(self):
        with mock.patch.dict(os.environ, {"PRINT_BUDDY_CONFIG": str(self.dir / "nope.toml")}):
            with self.assertRaisesRegex(settings.SettingsError, "missing file"):
                settings.load()

    def test_bad_values_are_rejected(self):
        from print_buddy.settings import validate
        for text, message in [("[printer]\nbed_mm = [220]\n", "bed_mm"),
                              ("[printer]\nbed_mm = [220, -1]\n", "bed_mm"),
                              ("[printer]\nifs_slots = 2.5\n", "whole number"),
                              ("[printer]\nnozzle_diameter_mm = true\n", "should be like 0.4"),
                              ("[layout]\nmulti_copy_edge_mm = 0\n", "positive number"),
                              ('[orca]\ncommand = "flatpak run orca"\n', "should be like"),
                              ("[printer]\nbed_size = 220\n", "unknown setting \\[printer\\] bed_size"),
                              ("[pritner]\nifs_slots = 1\n", "unknown section"),
                              ('[services]\nspoolman_url = "spoolman.lan"\n', "must be a URL"),
                              ("[nozzle_temp_offsets]\nbrass = 16\n", "between -10 and \\+15"),
                              ("[nozzle_temp_offsets]\nmystery = 2\n", "unknown nozzle type"),
                              ("[printer\n", "local.toml")]:

            with self.subTest(text=text):
                with self.assertRaisesRegex(settings.SettingsError, message):
                    settings.load(local=self.toml(text))

        base = settings.load(local=False, environ={})
        for bad in ({"mystery": 1}, {"brass": 16}, {"brass": True}):
            with self.subTest(offsets=bad), self.assertRaises(settings.SettingsError):
                validate({**base, "nozzle_temp_offsets": bad})
        valid = settings.load(local=self.toml("[nozzle_temp_offsets]\nhardened_steel = 5\n"))
        self.assertEqual(valid["nozzle_temp_offsets"]["hardened_steel"], 5.0)

    def test_relative_templates_resolve_from_the_repo(self):
        data = settings.load(local=self.toml('[orca]\ntemplates = "my/profiles"\n'))
        self.assertEqual(data["orca"]["templates"], settings.ROOT / "my/profiles")

    def test_override_changes_core_behavior_in_a_fresh_process(self):
        path = self.toml("[printer]\nbed_mm = [300, 300]\n")
        code = ("from print_buddy.core import slice_guard, orca_adapter;"
                "print(slice_guard.pre_slice(bounds=(0, 0, 250, 250), tool_slots={0: 1}).ok, orca_adapter.BED)")
        out = subprocess.run([sys.executable, "-c", code], cwd=settings.ROOT, capture_output=True, text=True,
                             env={**os.environ, "PRINT_BUDDY_CONFIG": str(path)}, check=True).stdout
        self.assertEqual(out.strip(), "True [300.0, 300.0]")


class RuntimeSettingsTests(unittest.TestCase):
    def test_legacy_env_names_still_work(self):
        data = settings.load(local=False, environ={"MOONRAKER_URL": "http://ad5x.lan:7125", "SPOOL_NAG_SECONDS": "300",
                                                   "PRINT_DISCORD_CHAT_ID": "123"})
        self.assertEqual(data["services"]["moonraker_url"], "http://ad5x.lan:7125")
        self.assertEqual(data["listener"]["spool_nag_s"], 300)
        self.assertEqual(data["discord"]["chat_id"], "123")

    def test_hermes_home_env_does_not_move_state(self):
        # The multiplexed gateway runs with HERMES_HOME=~/.hermes for every profile. Reading it
        # sent the print plugin to ~/.hermes/state, where printer_hardware.json does not exist.
        data = settings.load(local=False, environ={"HERMES_HOME": "/somewhere/else/.hermes"})
        self.assertEqual(data["paths"]["hermes_home"], Path("~/.hermes/profiles/3dprinting").expanduser())
        data = settings.load(local=False, environ={"PRINT_BUDDY__PATHS__HERMES_HOME": "/tmp/pb-profile"})
        self.assertEqual(data["paths"]["hermes_home"], Path("/tmp/pb-profile"))

    def test_generic_env_override(self):
        data = settings.load(local=False, environ={"PRINT_BUDDY__MAINTENANCE__FULL_DAYS": "45"})
        self.assertEqual(data["maintenance"]["full_days"], 45)

    def test_discord_timeouts_are_positive_whole_seconds(self):
        data = settings.load(local=False, environ={})
        self.assertEqual(data["discord"]["question_timeout_s"], 1800)
        self.assertEqual(data["discord"]["safety_confirm_timeout_s"], 600)
        self.assertEqual(data["discord"]["upload_wait_s"], 3600)
        self.assertEqual(data["discord"]["cold_pull_outcome_s"], 1800)
        data = settings.load(local=False, environ={"PRINT_BUDDY__DISCORD__QUESTION_TIMEOUT_S": "2400"})
        self.assertEqual(data["discord"]["question_timeout_s"], 2400)
        for key, raw in [("question_timeout_s", "0"), ("upload_wait_s", "-10"),
                         ("safety_confirm_timeout_s", "1.5"), ("cold_pull_outcome_s", "nope")]:
            with self.subTest(key=key), self.assertRaises(settings.SettingsError):
                settings.load(local=False, environ={f"PRINT_BUDDY__DISCORD__{key.upper()}": raw})

    def test_visual_watch_sensitivity_is_one_to_five(self):
        self.assertEqual(settings.load(local=False, environ={})["visual_watch"]["sensitivity"], 3)
        data = settings.load(local=False, environ={"PRINT_BUDDY__VISUAL_WATCH__SENSITIVITY": "1"})
        self.assertEqual(data["visual_watch"]["sensitivity"], 1)
        for bad in ("0", "6"):
            with self.subTest(value=bad), self.assertRaisesRegex(settings.SettingsError, "1 to 5"):
                settings.load(local=False, environ={"PRINT_BUDDY__VISUAL_WATCH__SENSITIVITY": bad})
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "local.toml"
            local.write_text("[visual_watch]\nsensitivity = 2.5\n")
            with self.assertRaisesRegex(settings.SettingsError, "1 to 5"):
                settings.load(local=local, environ={})

    def test_env_typos_and_bad_numbers_fail(self):
        for env, message in [({"PRINT_BUDDY__LISTENER__TICKS": "5"}, "unknown setting"),
                             ({"SPOOL_NAG_SECONDS": "ten"}, "should be a number"),
                             ({"PRINT_BUDDY__COLD_PULL__PETG": "1"}, "list")]:
            with self.subTest(env=env), self.assertRaisesRegex(settings.SettingsError, message):
                settings.load(local=False, environ=env)

    def test_delivery_methods_env_list_is_parsed_and_validated(self):
        """PRINT_BUDDY__DELIVERY__METHODS (#270): comma- or space-separated, checked like the YAML list."""
        a1 = {"PRINT_BUDDY__PRINTER__MODEL": "bambulab.a1"}
        for raw in ("discord,bambu_handoff,printer", "discord bambu_handoff printer", " printer , discord,  bambu_handoff "):
            with self.subTest(raw=raw):
                data = settings.load(local=False, environ={**a1, "PRINT_BUDDY__DELIVERY__METHODS": raw})
                methods = data["delivery"]["methods"]
                self.assertIsInstance(methods, list)
                self.assertTrue(all(type(m) is str for m in methods))
                # Vendor order, like the YAML value: the post-slice buttons follow it.
                self.assertEqual(methods, ["printer", "discord", "bambu_handoff"])
        # The .env.example line itself loads for the printer it is written for.
        example = next(line.split("=", 1)[1] for line in (settings.ROOT / ".env.example").read_text().splitlines()
                       if line.startswith("# PRINT_BUDDY__DELIVERY__METHODS="))
        data = settings.load(local=False, environ={**a1, "PRINT_BUDDY__DELIVERY__METHODS": example})
        self.assertIn("printer", data["delivery"]["methods"])
        # A value the Bambu vendor does not offer is refused, naming the key, exactly like YAML.
        for raw in ("discord,sd_card", "printer,Discord"):
            with self.subTest(raw=raw), self.assertRaisesRegex(settings.SettingsError, r"\[delivery\] methods .* not offered"):
                settings.load(local=False, environ={**a1, "PRINT_BUDDY__DELIVERY__METHODS": raw})
        # A list of only separators is an empty list, refused like `methods: []` in YAML.
        with self.assertRaisesRegex(settings.SettingsError, r"\[delivery\] methods must be a non-empty list"):
            settings.load(local=False, environ={**a1, "PRINT_BUDDY__DELIVERY__METHODS": ","})
        # The Flashforge vendor offers no Bambu handoff: the same check applies to every vendor.
        with self.assertRaisesRegex(settings.SettingsError, r"\[delivery\] methods \['bambu_handoff'\] are not offered"):
            settings.load(local=False, environ={"PRINT_BUDDY__DELIVERY__METHODS": "bambu_handoff"})

    def test_delivery_methods_env_wins_over_yaml_and_yaml_stands_when_env_unset(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        local = Path(tmp.name) / "local.yaml"
        local.write_text("printer:\n  model: bambulab.a1\ndelivery:\n  methods: [discord]\n")
        self.assertEqual(settings.load(local=local, environ={})["delivery"]["methods"], ["discord"])
        # An empty value leaves the file value alone, like every other Docker feature variable left blank.
        self.assertEqual(settings.load(local=local, environ={"PRINT_BUDDY__DELIVERY__METHODS": ""})["delivery"]["methods"],
                         ["discord"])
        data = settings.load(local=local, environ={"PRINT_BUDDY__DELIVERY__METHODS": "discord,printer"})
        self.assertEqual(data["delivery"]["methods"], ["printer", "discord"])
        # The vendor default stands when neither the file nor the environment sets it: `printer` is never a default.
        self.assertEqual(settings.load(local=False, environ={"PRINT_BUDDY__PRINTER__MODEL": "bambulab.a1"})["delivery"]["methods"],
                         ["discord", "bambu_handoff"])

    def test_other_lists_stay_file_only(self):
        for env in ({"PRINT_BUDDY__ORCA__COMMAND": "orca-slicer"}, {"PRINT_BUDDY__PRINTER__BED_MM": "220,220"}):
            with self.subTest(env=env), self.assertRaisesRegex(settings.SettingsError, "cannot come from the environment"):
                settings.load(local=False, environ=env)

    def test_moonraker_url_derives_websocket_and_camera(self):
        data = settings.load(local=False, environ={"MOONRAKER_URL": "http://ad5x.lan:7125/"})
        self.assertEqual(data["services"]["moonraker_ws_url"], "ws://ad5x.lan:7125/websocket")
        self.assertEqual(data["services"]["camera_snapshot_url"], "http://ad5x.lan/webcam/?action=snapshot")

    def test_paths_expand_and_state_lives_in_the_profile(self):
        data = settings.load(local=False, environ={})
        self.assertEqual(data["paths"]["hermes_home"], Path.home() / ".hermes/profiles/3dprinting")
        self.assertEqual(settings.state_dir(data), Path.home() / ".hermes/profiles/3dprinting/state")
        self.assertEqual(data["paths"]["ffmpeg"], "ffmpeg")

    def test_home_file_has_no_addresses_or_ids(self):
        data = settings.load(local=False, environ={})
        self.assertTrue(all(not v for k, v in data["services"].items() if k.endswith("_url")))
        self.assertEqual((data["discord"]["chat_id"], data["discord"]["approval_user_id"]), ("", ""))


class SettingsCliTests(unittest.TestCase):
    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-m", "print_buddy.settings", *args], cwd=settings.ROOT,
                              capture_output=True, text=True, env={**os.environ, **(env or {})})

    def test_get_prints_the_value(self):
        out = self.run_cli("get", "services.moonraker_ws_url", env={"MOONRAKER_URL": "http://ad5x.lan:7125"})
        self.assertEqual(out.stdout.strip(), "ws://ad5x.lan:7125/websocket")

    def test_unknown_key_fails(self):
        self.assertNotEqual(self.run_cli("get", "services.nope").returncode, 0)


class LiveStreamSettingsTests(unittest.TestCase):
    """The [live_stream] section (#311 stage 3): off by default, older configs load unchanged."""

    DEFAULTS = {"enabled": False, "voice_channel_id": "", "auto_start_on_print": False,
                "max_height": 720, "fps": 15, "max_bitrate_kbps": 2500, "encoder": "auto",
                "empty_timeout_s": 300, "activity_origin": ""}

    def test_absent_section_yields_the_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "local.yaml"
            local.write_text("visual_watch:\n  sensitivity: 3\n")
            data = settings.load(local=local, environ={})
        self.assertEqual(data["live_stream"], self.DEFAULTS)

    def test_section_values_and_env_override_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "local.yaml"
            local.write_text("live_stream:\n  enabled: true\n  voice_channel_id: '123456789012345678'\n"
                             "  encoder: NVENC\n  activity_origin: https://pb.example/\n")
            data = settings.load(local=local, environ={})
            self.assertEqual(data["live_stream"]["voice_channel_id"], "123456789012345678")
            self.assertEqual(data["live_stream"]["encoder"], "nvenc")
            self.assertEqual(data["live_stream"]["activity_origin"], "https://pb.example")
            env = {"PRINT_BUDDY__LIVE_STREAM__ENABLED": "false", "PRINT_BUDDY__LIVE_STREAM__FPS": "30"}
            data = settings.load(local=local, environ=env)
            self.assertEqual((data["live_stream"]["enabled"], data["live_stream"]["fps"]), (False, 30))

    def test_encoder_names_match_the_stage_2_plan(self):
        from print_buddy import live_stream
        self.assertEqual(settings.LIVE_STREAM_ENCODERS, live_stream.ENCODER_PREFERENCES)

    def test_bad_values_are_rejected(self):
        for text in ("live_stream:\n  enabled: sometimes\n",
                     "live_stream:\n  auto_start_on_print: maybe\n",
                     "live_stream:\n  voice_channel_id: not-a-channel\n",
                     "live_stream:\n  max_height: 100\n", "live_stream:\n  max_height: 4000\n",
                     "live_stream:\n  max_height: 12.5\n",
                     "live_stream:\n  fps: 0\n", "live_stream:\n  fps: 61\n",
                     "live_stream:\n  max_bitrate_kbps: 50\n",
                     "live_stream:\n  max_bitrate_kbps: 99999\n",
                     "live_stream:\n  encoder: av1\n",
                     "live_stream:\n  empty_timeout_s: 0\n",
                     "live_stream:\n  activity_origin: http://insecure.example\n"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                local = Path(tmp) / "local.yaml"
                local.write_text(text)
                with self.assertRaises(settings.SettingsError):
                    settings.load(local=local, environ={})
        with self.assertRaisesRegex(settings.SettingsError, "encoder"):
            settings.load(local=False, environ={"PRINT_BUDDY__LIVE_STREAM__ENCODER": "vp9"})
