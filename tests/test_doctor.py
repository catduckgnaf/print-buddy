"""The doctor reports every check and fails on any problem. Network and slicer are mocked."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from print_buddy import doctor, settings


HARDWARE = {"spool": {"material": "PLA", "density": 1.24}, "temps_c": {"nozzle": 210, "bed": 60},
            "nozzle": {"diameter_mm": 0.4}}


class DoctorTests(unittest.TestCase):
    def run_doctor(self, local_toml="", hardware=None, profile_config="enabled"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local.toml"
            path.write_text(local_toml)
            data = settings.load(local=path, environ={"PRINT_BUDDY__PATHS__HERMES_HOME": str(self.profile)})
        if profile_config is not None:
            self.profile.mkdir(parents=True, exist_ok=True)
            (self.profile / "config.yaml").write_text(
                "platforms:\n  discord:\n    enabled: true\n" if profile_config == "enabled" else profile_config)
        state = settings.state_dir(data)
        state.mkdir(parents=True, exist_ok=True)
        if hardware is not False:
            (state / "printer_hardware.json").write_text(json.dumps(hardware or HARDWARE))
        out = io.StringIO()
        with mock.patch.object(doctor.settings, "load", return_value=data), \
                mock.patch.object(doctor.shutil, "which", side_effect=self.which), \
                mock.patch.object(doctor.subprocess, "run", return_value=mock.MagicMock(returncode=self.orca_code)):
            code = doctor.run(out)
        return code, out.getvalue()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name) / "profile"
        self.orca_code = 0  # what the stubbed `orca --help` exits with
        self.which = lambda name: f"/usr/bin/{name}" if name == "flatpak" else None

    def test_home_setup_passes_and_skips_unset_services(self):
        code, text = self.run_doctor()
        self.assertEqual(code, 0, text)
        self.assertIn("ok    settings: Flashforge AD5X, bed 220x220 mm, 4 slot(s), 0.4 mm nozzle", text)
        self.assertIn("skip  moonraker", text)
        self.assertIn("ok    orca cli: flatpak run com.orcaslicer.OrcaSlicer", text)
        self.assertIn("ok    hermes discord platform", text)

    def test_hermes_profile_disabling_discord_fails_with_the_remedy(self):
        """#384: the gateway honours an explicit platform disable over any
        credentials, so the doctor must fail loudly instead of all-ok."""
        with mock.patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "token-present"}):
            code, text = self.run_doctor(profile_config="platforms:\n  discord:\n    enabled: false\n")
        self.assertEqual(code, 1)
        self.assertIn("FAIL  hermes discord platform", text)
        self.assertIn("platforms.discord.enabled is false", text)
        self.assertIn("Set it to true and restart the Hermes gateway", text)

    def test_hermes_profile_config_missing_skips(self):
        """No profile config means the profile was never installed — already
        loud everywhere else; this check must not become an update blocker
        for it (home-update.sh gates on the doctor)."""
        code, text = self.run_doctor(profile_config=None)
        self.assertEqual(code, 0, text)
        self.assertIn("skip  hermes discord platform", text)

    def test_stray_state_files_warn_without_failing(self):
        root = Path(self.tmp.name) / "hermes"
        self.profile = root / "profiles" / "main"
        (root / "state").mkdir(parents=True)
        (root / "state" / "print_alert_buttons.json").write_text("{}")
        with mock.patch.dict("os.environ", {"HOME": str(Path(self.tmp.name) / "home")}):
            code, text = self.run_doctor()
        self.assertEqual(code, 0, text)
        self.assertIn("WARN  stray state files: 1 outside", text)
        self.assertIn(str(root / "state" / "print_alert_buttons.json"), text)

    def test_no_stray_state_files_is_ok(self):
        with mock.patch.dict("os.environ", {"HOME": str(Path(self.tmp.name) / "home")}):
            code, text = self.run_doctor()
        self.assertIn("ok    stray state files: none", text)

    def test_bad_settings_fail_and_name_the_key(self):
        out = io.StringIO()
        with mock.patch.object(doctor.settings, "load", side_effect=settings.SettingsError("[printer] bed_mm bad")):
            self.assertEqual(doctor.run(out), 1)
        self.assertIn("FAIL  settings: [printer] bed_mm bad", out.getvalue())

    def test_template_drift_fails(self):
        code, text = self.run_doctor("[printer]\nbed_mm = [235, 235]\n")
        self.assertEqual(code, 1)
        self.assertIn("FAIL  orca templates", text)

    def test_unreachable_service_fails_and_other_checks_still_run(self):
        with mock.patch.object(doctor.urllib.request, "urlopen", side_effect=OSError("connection refused")):
            code, text = self.run_doctor('[services]\nspoolman_url = "http://spoolman.lan:7912"\n')
        self.assertEqual(code, 1)
        self.assertIn("FAIL  spoolman: connection refused", text)
        self.assertIn("ok    core", text)

    def test_healthy_service_passes(self):
        response = mock.MagicMock(status=200)
        response.__enter__.return_value = response
        with mock.patch.object(doctor.urllib.request, "urlopen", return_value=response) as urlopen:
            code, text = self.run_doctor('[services]\nmoonraker_url = "http://ad5x.lan:7125/"\n')
        self.assertEqual(code, 0, text)
        self.assertEqual(urlopen.call_args[0][0], "http://ad5x.lan:7125/printer/info")

    def test_missing_orca_binary_fails(self):
        code, text = self.run_doctor('[orca]\ncommand = ["definitely-not-orca-xyz"]\n')
        self.assertEqual(code, 1)
        self.assertIn("FAIL  orca cli: definitely-not-orca-xyz is not on PATH", text)

    def test_orca_that_will_not_start_fails(self):
        self.orca_code = 1
        code, text = self.run_doctor()
        self.assertEqual(code, 1)
        self.assertIn("FAIL  orca cli: flatpak run com.orcaslicer.OrcaSlicer --help exited 1", text)

    def test_missing_hardware_record_fails_with_the_path(self):
        code, text = self.run_doctor(hardware=False)
        self.assertEqual(code, 1)
        self.assertIn("FAIL  hardware record:", text)
        self.assertIn("printer_hardware.json is missing", text)

    def test_hardware_record_nozzle_must_match_settings(self):
        code, text = self.run_doctor(hardware={**HARDWARE, "nozzle": {"diameter_mm": 0.6}})
        self.assertEqual(code, 1)
        self.assertIn("recorded nozzle 0.6 mm does not match settings 0.4 mm", text)

    def test_hardware_record_needs_its_sections(self):
        code, text = self.run_doctor(hardware={"nozzle": {"diameter_mm": 0.4}})
        self.assertIn("lacks spool, temps_c", text)

    def test_hardware_record_needs_the_fields_slicing_reads(self):
        code, text = self.run_doctor(hardware={**HARDWARE, "spool": {}, "temps_c": {"nozzle": "hot"}})
        self.assertEqual(code, 1)
        self.assertIn("lacks spool.material, spool.density, temps_c.nozzle, temps_c.bed", text)

    def test_bad_service_url_is_a_settings_error(self):
        with self.assertRaisesRegex(settings.SettingsError, "must be a URL"):
            self.run_doctor('[services]\nspoolman_url = "spoolman.lan"\n')
