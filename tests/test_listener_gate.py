"""#256: the Moonraker listener runs only for connections that use one.

The decision comes from the resolved printer model (model -> vendor
connection), never from whether a Moonraker URL is filled in. Offline: the
registry and fake settings only, no printer or container contact.
"""
import contextlib
import importlib.util
import io
import os
import unittest
from pathlib import Path
from unittest import mock

from print_handy import healthcheck, listener_gate, printers, settings

ROOT = Path(__file__).resolve().parents[1]


def data(model):
    return {"printer": {"model": model}}


class ListenerGateDecisionTests(unittest.TestCase):
    def test_moonraker_models_require_the_listener(self):
        for model in ("flashforge.ad5x", "klipper.generic", "sovol.sv06"):
            with self.subTest(model=model):
                self.assertTrue(healthcheck.listener_required(data(model)))

    def test_bambu_models_require_the_listener(self):
        # #299 Stage B: bambulab_lan has its own listener domain now.
        for model in ("bambulab.a1", "bambulab.p1s"):
            with self.subTest(model=model):
                self.assertTrue(healthcheck.listener_required(data(model)))

    def test_non_listener_models_do_not(self):
        # flashforge_stock forbids a Moonraker URL in settings; octoprint
        # never populates the listener's websocket URL. Both SystemExited
        # the listener before #256, and neither has a domain listener yet.
        for model in ("flashforge_stock.ad5x", "octoprint.marlin"):
            with self.subTest(model=model):
                self.assertFalse(healthcheck.listener_required(data(model)))

    def test_every_registered_model_is_classified_by_its_connection(self):
        from print_handy import listeners
        for key, model in printers.MODELS.items():
            with self.subTest(model=key):
                domain = listeners.DOMAINS[model.vendor.connection]
                self.assertEqual(healthcheck.listener_required(data(key)),
                                 domain.implemented)


class ListenerGateCliTests(unittest.TestCase):
    def run_gate(self, connection):
        with mock.patch.object(healthcheck, "listener_connection",
                               return_value=connection):
            return listener_gate.main()

    def test_moonraker_connection_starts_the_listener(self):
        self.assertEqual(self.run_gate("moonraker"), 0)

    def test_bambulab_connection_starts_the_listener(self):
        self.assertEqual(self.run_gate("bambulab_lan"), 0)

    def test_other_connections_skip_the_listener(self):
        for connection in ("flashforge_stock", "octoprint", "offline",
                           "prusalink", "elegoo_sdcp"):
            with self.subTest(connection=connection):
                self.assertEqual(self.run_gate(connection), 3)

    def test_unresolved_configuration_is_a_distinct_failure(self):
        with mock.patch.object(healthcheck, "listener_connection",
                               side_effect=settings.SettingsError("bad model")):
            self.assertEqual(listener_gate.main(), 2)


class ListenerGatePerPrinterCliTests(unittest.TestCase):
    """#336: --printer decides for one roster entry, --roster lists them."""

    ROSTER = {"printers": [
        {"id": "moon-two", "model": "klipper.generic"},
        {"id": "prusa-two", "model": "prusa.mk4s"},
    ]}

    def run_gate(self, argv, data=None):
        with mock.patch.object(settings, "current",
                               return_value=self.ROSTER if data is None else data):
            return listener_gate.main(argv)

    def test_moonraker_printer_starts_its_listener(self):
        self.assertEqual(self.run_gate(["--printer", "moon-two"]), 0)

    def test_printer_without_a_listener_domain_skips(self):
        self.assertEqual(self.run_gate(["--printer", "prusa-two"]), 3)

    def test_unknown_printer_is_a_configuration_failure(self):
        self.assertEqual(self.run_gate(["--printer", "ghost"]), 2)

    def test_missing_printer_value_is_a_usage_error(self):
        self.assertEqual(self.run_gate(["--printer"]), 2)

    def test_roster_lists_the_configured_ids(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.run_gate(["--roster"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().splitlines(), ["moon-two", "prusa-two"])

    def test_roster_unresolved_configuration_fails(self):
        with mock.patch.object(settings, "current",
                               side_effect=settings.SettingsError("bad roster")):
            self.assertEqual(listener_gate.main(["--roster"]), 2)


def load_docker_healthcheck():
    spec = importlib.util.spec_from_file_location(
        "pb_docker_healthcheck", ROOT / "docker" / "healthcheck.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DockerHealthcheckTests(unittest.TestCase):
    """docker/healthcheck.py mirrors the supervisor's gate decision."""

    def run_main(self, module):
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        env = {"DISCORD_BOT_TOKEN": "", "PRINT_HANDY_BUNDLED_SPOOLMAN": "true"}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(module.urllib.request, "urlopen",
                                  return_value=response), \
                contextlib.redirect_stdout(out):
            code = module.main()
        return code, out.getvalue()

    def test_not_required_listener_is_ok_without_a_heartbeat(self):
        check = mock.Mock(side_effect=AssertionError("heartbeat must not be read"))
        module = load_docker_healthcheck()
        with mock.patch.object(module, "listener_required", return_value=False), \
                mock.patch.object(module, "listener_check", check):
            code, out = self.run_main(module)
        self.assertEqual(code, 0)
        self.assertIn("not required for this printer connection", out)

    def test_required_listener_states(self):
        for heartbeat_ok, expected in ((True, 0), (False, 1)):
            with self.subTest(heartbeat_ok=heartbeat_ok):
                module = load_docker_healthcheck()
                with mock.patch.object(module, "listener_required", return_value=True), \
                        mock.patch.object(module, "listener_check",
                                          return_value=(heartbeat_ok, "reason")):
                    code, _ = self.run_main(module)
                self.assertEqual(code, expected)

    def test_unresolved_configuration_fails(self):
        module = load_docker_healthcheck()
        with mock.patch.object(module, "listener_required",
                               side_effect=settings.SettingsError("bad model")):
            code, out = self.run_main(module)
        self.assertEqual(code, 1)
        self.assertIn("configuration unresolved", out)

    def test_multi_printer_rows_report_each_printer(self):
        """#336: one row per roster printer; any required failure fails."""
        module = load_docker_healthcheck()
        entries = [{"id": "moon-two"}, {"id": "bambu-two"}]

        def check(data, printer_id=None):
            if printer_id == "moon-two":
                return True, "fresh heartbeat"
            return False, "no heartbeat yet"

        with mock.patch.object(module.settings, "printers", return_value=entries), \
                mock.patch.object(module, "listener_required", return_value=True), \
                mock.patch.object(module, "listener_check", side_effect=check):
            code, out = self.run_main(module)
        self.assertEqual(code, 1)
        self.assertIn("ok  listener (moon-two): fresh heartbeat", out)
        self.assertIn("FAIL  listener (bambu-two): no heartbeat yet", out)

    def test_multi_printer_not_required_row_stays_ok(self):
        module = load_docker_healthcheck()
        entries = [{"id": "moon-two"}, {"id": "prusa-two"}]
        domain = mock.Mock()
        domain.name = "prusalink"
        domain.availability = "planned"

        def required(data, printer_id=None):
            return printer_id == "moon-two"

        with mock.patch.object(module.settings, "printers", return_value=entries), \
                mock.patch.object(module, "listener_required", side_effect=required), \
                mock.patch.object(module, "listener_check",
                                  return_value=(True, "fresh heartbeat")), \
                mock.patch.object(module, "listener_domain", return_value=domain):
            code, out = self.run_main(module)
        self.assertEqual(code, 0)
        self.assertIn("ok  listener (moon-two): fresh heartbeat", out)
        self.assertIn("ok  listener (prusa-two): not required", out)
        self.assertIn("has no listener yet", out)


if __name__ == "__main__":
    unittest.main()
