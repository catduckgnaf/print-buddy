"""#390 Stage 5: the new doctor rows — logging writability and listener heartbeats."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from print_handy import doctor


class LoggingRowTests(unittest.TestCase):
    def test_no_log_file_is_ok_and_reports_stderr_only(self):
        self.assertEqual(doctor.check_logging({"logging": {}}), "stderr only")

    def test_missing_log_folder_fails_with_remedy_and_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"logging": {"file": str(Path(tmp) / "gone" / "pb.log")}}
            with self.assertRaises(RuntimeError) as ctx:
                doctor.check_logging(data)
        self.assertIn("does not exist", str(ctx.exception))
        self.assertIn("PB_LOGGING_CONFIGURATION", str(ctx.exception))

    def test_writable_log_file_passes_and_counts_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"logging": {"file": str(Path(tmp) / "pb.log"),
                                "levels": {"print_handy.core": "DEBUG"}}}
            detail = doctor.check_logging(data)
        self.assertIn("1 subsystem level override(s)", detail)


class ListenerHeartbeatRowTests(unittest.TestCase):
    def test_no_required_listener_is_no_warning(self):
        with mock.patch("print_handy.healthcheck.listener_statuses",
                        return_value={"p1": {"required": False, "ok": None, "reason": "no listener"}}):
            self.assertIsNone(doctor.check_listener_heartbeats({}))

    def test_down_listener_warns_naming_printer_reason_and_marker(self):
        with mock.patch("print_handy.healthcheck.listener_statuses",
                        return_value={"ad5x": {"required": True, "ok": False,
                                                "reason": "listener heartbeat stale or invalid"}}):
            warning = doctor.check_listener_heartbeats({})
        self.assertIn("ad5x", warning)
        self.assertIn("stale", warning)
        self.assertIn("PB_LISTENER_TRANSIENT", warning)

    def test_healthy_required_listener_is_no_warning(self):
        with mock.patch("print_handy.healthcheck.listener_statuses",
                        return_value={"ad5x": {"required": True, "ok": True, "reason": "alive"}}):
            self.assertIsNone(doctor.check_listener_heartbeats({}))


if __name__ == "__main__":
    unittest.main()
