import subprocess
import unittest
from unittest.mock import Mock

from print_handy.core import clear_job


def snapshots(native_status="ready", moon="standby", target=0):
    m = {"state": "ready", "print": {"state": moon, "filename": "old.gcode"},
         "extruder": {"target": target}, "bed": {"target": 0}}
    n = {"status": native_status, "leftTargetTemp": 0, "rightTargetTemp": 0,
         "platTargetTemp": 0, "chamberTargetTemp": 0}
    return m, n


class ClearJobTests(unittest.TestCase):
    def test_cancelled_idle_is_noop(self):
        m, n = snapshots("cancel")
        cancel = Mock()
        self.assertEqual(clear_job.clear(m, Mock(return_value=n), cancel, moonraker_reader=lambda: m)["operation"], "no-op")
        cancel.assert_not_called()

    def test_safe_idle_cancel_verifies_native_cancel(self):
        m, n = snapshots()
        after_native = dict(n, status="cancel")
        reader = Mock(side_effect=[n, after_native])
        receipt = subprocess.CompletedProcess([], 0, "ok", "")
        result = clear_job.clear(m, reader, Mock(return_value=receipt), moonraker_reader=lambda: m)
        self.assertTrue(result["verified"])
        self.assertEqual(result["cancel_receipt"], {"stdout": "ok", "stderr": "", "returncode": 0})

    def test_active_conflict_refuses_without_override(self):
        m, n = snapshots(native_status="printing", moon="standby")
        cancel = Mock()
        with self.assertRaisesRegex(RuntimeError, "--allow-active-cancel"):
            clear_job.clear(m, lambda: n, cancel)
        cancel.assert_not_called()

    def test_explicit_override_allows_conflicting_active_cancel(self):
        m, n = snapshots(native_status="printing", moon="standby")
        after = dict(n, status="cancel")
        reader = Mock(side_effect=[n, after])
        cancel = Mock(return_value=subprocess.CompletedProcess([], 0, "cancelled", ""))
        result = clear_job.clear(m, reader, cancel, allow_active_cancel=True, moonraker_reader=lambda: m)
        self.assertTrue(result["verified"])
        cancel.assert_called_once()

    def test_moonraker_active_requires_explicit_override(self):
        m, n = snapshots(moon="paused")
        cancel = Mock()
        with self.assertRaisesRegex(RuntimeError, "--allow-active-cancel"):
            clear_job.clear(m, lambda: n, cancel)
        cancel.assert_not_called()

    def test_uncertain_cancel_is_not_replayed(self):
        m, n = snapshots()
        reader = Mock(return_value=n)
        cancel = Mock(side_effect=subprocess.TimeoutExpired("cancel", 40, output="sent", stderr="timeout"))
        with self.assertRaises(clear_job.CancelFailure) as caught:
            clear_job.clear(m, reader, cancel)
        cancel.assert_called_once()
        reader.assert_called_once()
        self.assertEqual(caught.exception.evidence["cancel_receipt"]["stdout"], "sent")

    def test_target_mismatch_fails_closed(self):
        m, n = snapshots(target=180)
        cancel = Mock()
        with self.assertRaisesRegex(RuntimeError, "precondition"):
            clear_job.clear(m, lambda: n, cancel)
        cancel.assert_not_called()

    def test_cancel_postcondition_requires_native_cancel(self):
        m, n = snapshots()
        reader = Mock(side_effect=[n, n])
        with self.assertRaisesRegex(clear_job.CancelFailure, "native cancellation not confirmed"):
            clear_job.clear(m, reader, Mock(return_value=subprocess.CompletedProcess([], 0, "", "")), moonraker_reader=lambda: m)


if __name__ == "__main__":
    unittest.main()
