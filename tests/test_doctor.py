"""The doctor reports every check and fails on any problem. Network and slicer are mocked."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from print_buddy import doctor, settings


class DoctorTests(unittest.TestCase):
    def run_doctor(self, local_toml=""):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local.toml"
            path.write_text(local_toml)
            data = settings.load(local=path)
        out = io.StringIO()
        with mock.patch.object(doctor.settings, "load", return_value=data), \
                mock.patch.object(doctor.shutil, "which", side_effect=self.which), \
                mock.patch.object(doctor.subprocess, "run", return_value=mock.MagicMock(returncode=self.orca_code)):
            code = doctor.run(out)
        return code, out.getvalue()

    def setUp(self):
        self.orca_code = 0  # what the stubbed `orca --help` exits with
        self.which = lambda name: f"/usr/bin/{name}" if name == "flatpak" else None

    def test_home_setup_passes_and_skips_unset_services(self):
        code, text = self.run_doctor()
        self.assertEqual(code, 0, text)
        self.assertIn("ok    settings: Flashforge AD5X, bed 220x220 mm, 4 slot(s), 0.4 mm nozzle", text)
        self.assertIn("skip  moonraker", text)
        self.assertIn("ok    orca cli: flatpak run com.orcaslicer.OrcaSlicer", text)

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

    def test_bad_service_url_is_a_settings_error(self):
        with self.assertRaisesRegex(settings.SettingsError, "http"):
            self.run_doctor('[services]\nspoolman_url = "spoolman.lan"\n')
