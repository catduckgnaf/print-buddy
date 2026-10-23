"""The listener's container heartbeat runs on its own event loop and reports the Moonraker link."""
import asyncio
import unittest
from unittest import mock

from print_buddy.hermes import moonraker_event_listener as mel


class ListenerHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_beats_with_connection_state_and_survives_a_write_error(self):
        listener = mel.Listener()
        listener.moonraker_connected = True
        listener.state = "standby"
        sleeps = 0

        async def sleep(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                raise asyncio.CancelledError

        with mock.patch.object(mel.healthcheck, "beat", side_effect=[OSError("disk full"), None]) as beat, \
             mock.patch.object(mel.asyncio, "sleep", sleep), mock.patch.object(mel, "log") as log:
            with self.assertRaises(asyncio.CancelledError):
                await listener.heartbeat()
        self.assertEqual(beat.call_count, 2)
        beat.assert_called_with("moonraker_event_listener", moonraker_connected=True, state="standby")
        self.assertIn("heartbeat write failed", log.call_args_list[0].args[0])

    async def test_connection_flag_drops_when_the_session_ends(self):
        listener = mel.Listener()

        async def session():
            listener.moonraker_connected = True
            raise OSError("printer off")

        async def sleep(_seconds):
            raise asyncio.CancelledError

        with mock.patch.object(listener, "session", session), mock.patch.object(listener, "heartbeat", mock.AsyncMock()), \
             mock.patch.object(mel.asyncio, "sleep", sleep), mock.patch.object(mel, "log"):
            with self.assertRaises(asyncio.CancelledError):
                await listener.forever()
        self.assertFalse(listener.moonraker_connected)
