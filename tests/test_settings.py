"""config/home.toml is the real home setup. These tests keep it valid and in step with the Orca templates."""
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
