"""Stock screen errors (e.g. E0102 feed timeout) halt prints while Klipper still says printing."""
import sys
import unittest
from pathlib import Path
from unittest import mock
from print_handy.hermes import moonraker_event_listener as mel

E0102 = {"status": "error", "errorCode": "E0102", "matlStationInfo": {"currentLoadSlot": 3}}
OK = {"status": "printing", "errorCode": "", "matlStationInfo": {"currentLoadSlot": 1}}


class NativeErrorKeyTests(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(mel.native_error_key(E0102), ("E0102", 3))
        self.assertIsNone(mel.native_error_key(OK))
        self.assertEqual(mel.native_error_key({"status": "error"}), ("unknown", None))
        self.assertIsNone(mel.native_error_key({}))

    def test_text_names_code_slot_and_retry(self):
        text = mel.native_error_text("Ghost.gcode", ("E0102", 3))
        self.assertIn("E0102 (slot 3)", text)
        self.assertIn("could not feed", text)
        self.assertIn("retry", text)


class PollAlertTests(unittest.IsolatedAsyncioTestCase):
    async def poll(self, listener, detail):
        async def read():
            return detail, {}
        listener.read_slots = read
        await listener.poll_native_presence()

    async def test_alerts_once_per_error_and_rearms_after_clear(self):
        lis = mel.Listener()
        lis.state, lis.filename = "printing", "Ghost.gcode"
        with mock.patch.object(mel, "post") as post, mock.patch.object(mel, "log"):
            await self.poll(lis, E0102)
            await self.poll(lis, E0102)
            self.assertEqual(post.call_count, 1)
            self.assertIn("E0102", post.call_args[0][0])
            await self.poll(lis, OK)
            await self.poll(lis, E0102)
            self.assertEqual(post.call_count, 2)

    async def test_idle_errors_do_not_alert(self):
        lis = mel.Listener()
        lis.state = "standby"
        with mock.patch.object(mel, "post") as post, mock.patch.object(mel, "log"):
            await self.poll(lis, E0102)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
