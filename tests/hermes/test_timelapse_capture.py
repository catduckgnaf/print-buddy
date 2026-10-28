"""#246 stage 2: in-container timelapse frame capture.

Everything offline: frames come from an injected fetch or a loopback HTTP
fixture, Moonraker events are driven through the listener directly, and
no camera, printer, GPU or Discord is contacted.
"""
import asyncio
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from print_handy import settings  # noqa: E402
from print_handy.hermes import _config, timelapse_capture  # noqa: E402
from print_handy.hermes import moonraker_event_listener as mel  # noqa: E402

JPEG = b"\xff\xd8" + b"fake-jpeg-payload" + b"\xff\xd9"
SECRET_URL = "http://user:hunter2@cam.example/webcam/?action=snapshot"


def make_data(root, **timelapse):
    base = {"capture_enabled": True, "capture_source_url": "",
            "capture_trigger": "interval", "capture_interval_s": 5.0,
            "capture_max_frames": 3600, "capture_max_bytes": 536870912,
            "capture_encoder": "auto", "local_retention_days": 1}
    base.update(timelapse)
    return {"timelapse": base,
            "services": {"camera_snapshot_url": "http://printer.example/webcam/?action=snapshot"},
            "paths": {"cache": str(root)}}


class Clock:
    def __init__(self, start=1_000_000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_session(root, clock, **kwargs):
    kwargs.setdefault("trigger", timelapse_capture.make_trigger("interval", 5.0))
    kwargs.setdefault("url", "http://cam.example/snapshot")
    kwargs.setdefault("fetch", lambda url: JPEG)
    kwargs.setdefault("now", clock)
    session = timelapse_capture.CaptureSession(root, "job:7", "benchy.gcode", **kwargs)
    return session


class SessionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "timelapse"
        self.clock = Clock()

    def test_start_creates_frames_dir_and_manifest(self):
        session = make_session(self.root, self.clock)
        self.assertTrue(session.start())
        self.assertTrue(session.frames_dir.is_dir())
        manifest = json.loads(session.manifest_path.read_text())
        self.assertEqual(manifest["job_key"], "job:7")
        self.assertEqual(manifest["filename"], "benchy.gcode")
        self.assertEqual(manifest["state"], "capturing")
        self.assertEqual(manifest["trigger"], "interval")
        self.assertEqual(manifest["frames"], 0)
        self.assertEqual(manifest["started_at"], self.clock.now)

    def test_interval_trigger_captures_first_frame_then_every_interval(self):
        session = make_session(self.root, self.clock)
        session.start()
        self.assertTrue(session.tick())  # first frame is due immediately
        self.assertFalse(session.tick())  # same instant: not due
        self.clock.advance(4.9)
        self.assertFalse(session.tick())
        self.clock.advance(0.1)
        self.assertTrue(session.tick())
        frames = sorted(p.name for p in session.frames_dir.glob("*.jpg"))
        self.assertEqual(frames, ["frame-000001.jpg", "frame-000002.jpg"])
        self.assertEqual((session.frames_dir / "frame-000001.jpg").read_bytes(), JPEG)
        manifest = json.loads(session.manifest_path.read_text())
        self.assertEqual(manifest["frames"], 2)
        self.assertEqual(manifest["bytes"], 2 * len(JPEG))

    def test_stop_stamps_the_manifest_and_keeps_frames(self):
        session = make_session(self.root, self.clock)
        session.start()
        session.tick()
        self.clock.advance(60)
        manifest = session.stop("cancelled")
        self.assertEqual(manifest["state"], "cancelled")
        self.assertEqual(manifest["finished_at"], self.clock.now)
        self.assertEqual(manifest["frames"], 1)
        self.assertTrue((session.frames_dir / "frame-000001.jpg").is_file())
        self.assertFalse(session.active)
        self.assertFalse(session.tick())  # a stopped session never captures

    def test_start_failure_is_soft(self):
        # frames/ already exists as a file: mkdir fails, start reports False.
        blocker = self.root / "job-7" / "frames"
        blocker.parent.mkdir(parents=True)
        blocker.write_bytes(b"not a directory")
        session = make_session(self.root, self.clock)
        self.assertFalse(session.start())
        self.assertEqual(session.state, "failed")


class TriggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "timelapse"
        self.clock = Clock()

    def test_layer_trigger_fires_on_change_only(self):
        session = make_session(self.root, self.clock,
                               trigger=timelapse_capture.make_trigger("layer", 5.0))
        session.start()
        self.assertFalse(session.tick())  # no layer seen yet
        self.assertTrue(session.tick(layer=1))  # first layer
        self.assertFalse(session.tick(layer=1))  # same layer
        self.clock.advance(3600)
        self.assertFalse(session.tick(layer=1))  # time alone never fires it
        self.assertTrue(session.tick(layer=2))
        self.assertEqual(session.frame_count, 2)

    def test_both_trigger_fires_on_either(self):
        session = make_session(self.root, self.clock,
                               trigger=timelapse_capture.make_trigger("both", 5.0))
        session.start()
        self.assertTrue(session.tick(layer=1))  # interval's first frame
        self.assertTrue(session.tick(layer=2))  # layer change, interval not due
        self.assertFalse(session.tick(layer=2))
        self.clock.advance(5.0)
        self.assertTrue(session.tick(layer=2))  # interval floor
        self.assertEqual(session.frame_count, 3)

    def test_unknown_trigger_falls_back_to_interval(self):
        trigger = timelapse_capture.make_trigger("nonsense", 5.0)
        self.assertEqual(trigger.name, "interval")


class CapAndFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "timelapse"
        self.clock = Clock()

    def test_frame_cap_stops_capture_and_keeps_frames(self):
        session = make_session(self.root, self.clock, max_frames=2)
        session.start()
        self.assertTrue(session.capture_once())
        self.assertTrue(session.capture_once())
        self.assertFalse(session.capture_once())
        self.assertTrue(session.capped)
        self.assertTrue(session.active)  # capped, not ended: stop() still stamps it
        manifest = session.stop("complete")
        self.assertEqual(manifest["frames"], 2)
        self.assertTrue(manifest["capped"])

    def test_byte_cap_refuses_the_frame_that_would_overflow(self):
        session = make_session(self.root, self.clock, max_bytes=len(JPEG))
        session.start()
        self.assertTrue(session.capture_once())
        self.assertFalse(session.capture_once())
        self.assertTrue(session.capped)
        self.assertEqual(session.frame_count, 1)

    def test_zero_caps_disable_them(self):
        session = make_session(self.root, self.clock, max_frames=0, max_bytes=0)
        session.start()
        for _ in range(5):
            self.assertTrue(session.capture_once())
        self.assertFalse(session.capped)

    def test_fetch_failure_is_soft_and_retried_at_the_interval(self):
        attempts = []

        def flaky(url):
            attempts.append(url)
            if len(attempts) == 1:
                raise ConnectionError("camera gone")
            return JPEG

        logs = []
        session = make_session(self.root, self.clock, fetch=flaky, log=logs.append)
        session.start()
        self.assertFalse(session.tick())
        self.assertEqual(session.failures, 1)
        self.assertTrue(any("fetch failed" in line for line in logs))
        self.assertFalse(session.tick())  # no hot retry on the next event
        self.clock.advance(5.0)
        self.assertTrue(session.tick())
        self.assertEqual(session.frame_count, 1)

    def test_credentials_never_reach_logs_or_manifest(self):
        logs = []

        def broken(url):
            raise ConnectionError("refused")

        session = make_session(self.root, self.clock, url=SECRET_URL,
                               fetch=broken, log=logs.append)
        session.start()
        session.capture_once()
        manifest = json.loads(session.manifest_path.read_text())
        self.assertNotIn("hunter2", "\n".join(logs))
        self.assertNotIn("hunter2", json.dumps(manifest))
        self.assertIn("cam.example", manifest["source"])


def _jpeg(rgb, size=(64, 48)):
    import io

    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", size, rgb).save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


DARK_JPEG = _jpeg((0, 0, 0))
BRIGHT_JPEG = _jpeg((200, 200, 200))


class DarkFrameCaptureTests(unittest.TestCase):
    """#476: dark frames are skipped and counted, never stored."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "timelapse"
        self.clock = Clock()

    def test_dark_frames_are_skipped_and_counted(self):
        frames = iter([DARK_JPEG, BRIGHT_JPEG, DARK_JPEG])
        session = make_session(self.root, self.clock, fetch=lambda url: next(frames))
        session.start()
        self.assertFalse(session.capture_once())
        self.assertTrue(session.capture_once())
        self.assertFalse(session.capture_once())
        self.assertEqual(session.frame_count, 1)
        self.assertEqual(session.dark_frames, 2)
        stored = sorted(path.name for path in session.frames_dir.iterdir())
        self.assertEqual(stored, ["frame-000001.jpg"])
        self.assertEqual((session.frames_dir / "frame-000001.jpg").read_bytes(), BRIGHT_JPEG)
        manifest = session.manifest()
        self.assertEqual(manifest["frames"], 1)
        self.assertEqual(manifest["dark_frames"], 2)

    def test_all_dark_session_keeps_nothing(self):
        logs = []
        session = make_session(self.root, self.clock,
                               fetch=lambda url: DARK_JPEG, log=logs.append)
        session.start()
        for _ in range(3):
            self.assertFalse(session.capture_once())
        manifest = session.stop()
        self.assertEqual(session.frame_count, 0)
        self.assertEqual(session.dark_frames, 3)
        self.assertEqual(manifest["frames"], 0)
        self.assertEqual(manifest["dark_frames"], 3)
        self.assertEqual(list(session.frames_dir.iterdir()), [])
        self.assertTrue(any("completely dark" in line for line in logs))
        self.assertTrue(any("3 dark frame(s) skipped" in line for line in logs))


class FrameUrlTests(unittest.TestCase):
    def test_go2rtc_endpoint_when_the_binary_is_present(self):
        with tempfile.NamedTemporaryFile() as fake_bin:
            os.chmod(fake_bin.name, 0o755)
            with mock.patch.dict(os.environ, {"GO2RTC_BIN": fake_bin.name}):
                data = make_data(Path("/cache"))
                self.assertEqual(timelapse_capture.frame_url(data),
                                 timelapse_capture.GO2RTC_FRAME_URL)

    def test_snapshot_fallback_without_the_binary(self):
        with mock.patch.dict(os.environ, {"GO2RTC_BIN": "/nonexistent/go2rtc"}):
            data = make_data(Path("/cache"))
            self.assertEqual(timelapse_capture.frame_url(data),
                             "http://printer.example/webcam/?action=snapshot")

    def test_rtsp_override_still_names_go2rtc(self):
        with mock.patch.dict(os.environ, {"GO2RTC_BIN": "/nonexistent/go2rtc"}):
            data = make_data(Path("/cache"), capture_source_url="rtsp://cam.example/live")
            self.assertEqual(timelapse_capture.frame_url(data),
                             timelapse_capture.GO2RTC_FRAME_URL)

    def test_no_source_no_url(self):
        data = make_data(Path("/cache"))
        data["services"]["camera_snapshot_url"] = ""
        self.assertIsNone(timelapse_capture.frame_url(data))


class FetchFrameTests(unittest.TestCase):
    def serve(self, payload, content_type="image/jpeg"):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.shutdown)
        import threading
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{server.server_port}/frame"

    def test_fetches_a_jpeg(self):
        self.assertEqual(timelapse_capture.fetch_frame(self.serve(JPEG)), JPEG)

    def test_rejects_a_non_jpeg(self):
        with self.assertRaises(ValueError):
            timelapse_capture.fetch_frame(self.serve(b"<html>not a camera</html>", "text/html"))

    def test_rejects_an_oversized_frame(self):
        with mock.patch.object(timelapse_capture, "MAX_FRAME_BYTES", 4):
            with self.assertRaises(ValueError):
                timelapse_capture.fetch_frame(self.serve(JPEG))


class BeginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "cache"
        self.env = mock.patch.dict(os.environ, {"GO2RTC_BIN": "/nonexistent/go2rtc"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_disabled_capture_begins_nothing_and_creates_nothing(self):
        data = make_data(self.cache, capture_enabled=False)
        self.assertIsNone(timelapse_capture.begin("job:1", "a.gcode", data=data))
        self.assertFalse((self.cache / "timelapse").exists())

    def test_no_source_begins_nothing(self):
        data = make_data(self.cache)
        data["services"]["camera_snapshot_url"] = ""
        self.assertIsNone(timelapse_capture.begin("job:1", "a.gcode", data=data))

    def test_begin_uses_the_settings_knobs(self):
        data = make_data(self.cache, capture_trigger="layer", capture_max_frames=3)
        session = timelapse_capture.begin("job:1", "a.gcode", data=data,
                                          fetch=lambda url: JPEG)
        self.assertIsNotNone(session)
        self.assertEqual(session.trigger.name, "layer")
        self.assertEqual(session.max_frames, 3)
        self.assertEqual(session.url, "http://printer.example/webcam/?action=snapshot")
        self.assertTrue(session.active)
        session.stop()

    def test_repeated_job_key_gets_a_fresh_directory(self):
        data = make_data(self.cache)
        first = timelapse_capture.begin("job:1", "a.gcode", data=data, fetch=lambda url: JPEG)
        first.tick()
        first.stop()
        second = timelapse_capture.begin("job:1", "a.gcode", data=data, fetch=lambda url: JPEG)
        self.assertNotEqual(first.directory, second.directory)
        self.assertTrue(second.directory.name.endswith("-2"))
        second.stop()

    def test_capture_settings_defaults_for_plain_dicts(self):
        knobs = timelapse_capture.capture_settings({})
        self.assertEqual(knobs["capture_trigger"], "interval")
        self.assertEqual(knobs["capture_interval_s"], 5.0)
        self.assertEqual(knobs["capture_max_frames"], 3600)
        self.assertEqual(knobs["capture_max_bytes"], 512 * 1024 * 1024)


class PruneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "cache"
        self.root = self.cache / "timelapse"
        self.root.mkdir(parents=True)
        self.data = make_data(self.cache)
        self.now = time.time()

    def write_job(self, name, manifest=None, age_days=0):
        directory = self.root / name
        (directory / "frames").mkdir(parents=True)
        (directory / "frames" / "frame-000001.jpg").write_bytes(JPEG)
        if manifest is not None:
            (directory / "capture.json").write_text(json.dumps(manifest))
        stamp = self.now - age_days * 86400
        os.utime(directory, (stamp, stamp))
        os.utime(directory / "capture.json", (stamp, stamp)) if manifest else None
        return directory

    def test_finished_past_retention_is_removed(self):
        self.write_job("old-job", {"state": "complete", "finished_at": self.now - 2 * 86400})
        self.write_job("new-job", {"state": "complete", "finished_at": self.now - 3600})
        removed = timelapse_capture.prune(self.root, self.data, now=self.now)
        self.assertEqual(removed, ["old-job"])
        self.assertTrue((self.root / "new-job").is_dir())

    def test_live_capture_is_never_touched(self):
        self.write_job("live-job", {"state": "capturing", "finished_at": None})
        removed = timelapse_capture.prune(self.root, self.data, now=self.now)
        self.assertEqual(removed, [])

    def test_abandoned_capture_ages_out_by_manifest_mtime(self):
        self.write_job("stale-job", {"state": "capturing", "finished_at": None}, age_days=3)
        removed = timelapse_capture.prune(self.root, self.data, now=self.now)
        self.assertEqual(removed, ["stale-job"])

    def test_zero_retention_removes_nothing(self):
        self.write_job("old-job", {"state": "complete", "finished_at": self.now - 30 * 86400})
        data = make_data(self.cache, local_retention_days=0)
        self.assertEqual(timelapse_capture.prune(self.root, data, now=self.now), [])


class CaptureSettingsValidationTests(unittest.TestCase):
    """The Stage 2 [timelapse] keys: defaults and refusals via settings.load."""

    def test_defaults(self):
        data = settings.load(environ={})
        timelapse = data["timelapse"]
        self.assertEqual(timelapse["capture_trigger"], "interval")
        self.assertEqual(timelapse["capture_interval_s"], 5.0)
        self.assertEqual(timelapse["capture_max_frames"], 3600)
        self.assertEqual(timelapse["capture_max_bytes"], 536870912)
        self.assertEqual(timelapse["capture_encoder"], "auto")

    def test_env_overrides(self):
        data = settings.load(environ={
            "PRINT_HANDY__TIMELAPSE__CAPTURE_TRIGGER": "both",
            "PRINT_HANDY__TIMELAPSE__CAPTURE_INTERVAL_S": "2.5",
            "PRINT_HANDY__TIMELAPSE__CAPTURE_ENCODER": "vaapi",
        })
        self.assertEqual(data["timelapse"]["capture_trigger"], "both")
        self.assertEqual(data["timelapse"]["capture_interval_s"], 2.5)
        self.assertEqual(data["timelapse"]["capture_encoder"], "vaapi")

    def test_bad_values_are_refused(self):
        for environ in (
                {"PRINT_HANDY__TIMELAPSE__CAPTURE_TRIGGER": "sometimes"},
                {"PRINT_HANDY__TIMELAPSE__CAPTURE_ENCODER": "gpu"},
                {"PRINT_HANDY__TIMELAPSE__CAPTURE_INTERVAL_S": "0"},
                {"PRINT_HANDY__TIMELAPSE__CAPTURE_INTERVAL_S": "-3"},
                {"PRINT_HANDY__TIMELAPSE__CAPTURE_MAX_FRAMES": "-1"},
                {"PRINT_HANDY__TIMELAPSE__CAPTURE_MAX_BYTES": "-1"}):
            with self.subTest(environ=environ):
                with self.assertRaises(settings.SettingsError):
                    settings.load(environ=environ)


class ListenerCaptureHookTests(unittest.IsolatedAsyncioTestCase):
    """The listener wiring: off is a no-op; on follows the print lifecycle."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "cache"
        self.env = mock.patch.dict(os.environ, {"GO2RTC_BIN": "/nonexistent/go2rtc"})
        self.env.start()
        self.addCleanup(self.env.stop)
        # tests/conftest.py installs the test settings as the _config
        # override for the whole session: restore that object, never None.
        previous = _config.cfg()
        self.addCleanup(lambda: _config.set_override(previous))

    def install_config(self, **timelapse):
        data = copy.deepcopy(_config.cfg())
        data["timelapse"].update(timelapse)
        data["paths"]["cache"] = str(self.cache)
        _config.set_override(data)
        return data

    async def drive_start(self, listener):
        listener.state, listener.filename = "standby", "benchy.gcode"
        listener.visual_watch.due = lambda *a, **k: None
        with mock.patch.object(mel, "post"), mock.patch.object(mel, "run_announcer"), \
                mock.patch.object(mel, "start_claimed", return_value=True), \
                mock.patch.object(mel, "announce_warmup_done"), \
                mock.patch.object(mel, "_claim_notification", return_value=True):
            await listener.on_status(
                {"state": "printing", "filename": "benchy.gcode",
                 "info": {"current_layer": 1}}, "event")

    async def test_disabled_capture_is_a_noop(self):
        self.install_config(capture_enabled=False)
        listener = mel.Listener()
        listener._capture_begin("job:1")
        self.assertIsNone(listener.capture_session)
        await self.drive_start(listener)
        self.assertIsNone(listener.capture_session)
        self.assertFalse((self.cache / "timelapse").exists())

    async def test_lifecycle_start_capture_complete(self):
        self.install_config(capture_enabled=True, capture_trigger="interval",
                            capture_interval_s=5.0)
        listener = mel.Listener()
        with mock.patch.object(timelapse_capture, "fetch_frame", return_value=JPEG) as fetch:
            await self.drive_start(listener)
            session = listener.capture_session
            self.assertIsNotNone(session)
            self.assertTrue(session.active)
            await listener._capture_due(1)  # first frame is due at once
            self.assertEqual(session.frame_count, 1)
            self.assertEqual(fetch.call_count, 1)
            with mock.patch.object(mel, "post"), mock.patch.object(mel, "run_announcer"), \
                    mock.patch.object(mel, "_claim_notification", return_value=True), \
                    mock.patch.object(listener, "after_print", new=mock.AsyncMock()):
                await listener.on_status({"state": "complete"}, "event")
        self.assertIsNone(listener.capture_session)
        manifest = json.loads(session.manifest_path.read_text())
        self.assertEqual(manifest["state"], "complete")
        self.assertEqual(manifest["frames"], 1)

    async def test_pause_keeps_the_session_open_but_takes_no_frames(self):
        self.install_config(capture_enabled=True)
        listener = mel.Listener()
        with mock.patch.object(timelapse_capture, "fetch_frame", return_value=JPEG):
            await self.drive_start(listener)
            session = listener.capture_session
            self.assertIsNotNone(session)
            listener.state = "paused"
            await listener._capture_due(3)  # paused: the due hook is inert
            self.assertEqual(session.frame_count, 0)
            self.assertIs(listener.capture_session, session)  # still the same session
            listener.state = "printing"
            await listener._capture_due(3)  # resumed: the same session captures again
            self.assertEqual(session.frame_count, 1)
            listener._capture_end("complete")


def _mjpeg_stream(*frames):
    """A recorded multipart MJPEG body: one part per frame, then the closing boundary."""
    parts = []
    for frame in frames:
        parts.append(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
    return b"".join(parts) + b"--frame--\r\n"


class FetchMjpegFrameTests(unittest.TestCase):
    """#373: stream-only camera sources (the stock Flashforge cameraStreamUrl)."""

    def serve(self, payload, content_type="multipart/x-mixed-replace; boundary=frame"):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.shutdown)
        import threading
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{server.server_port}/?action=stream"

    def test_returns_the_first_complete_frame(self):
        url = self.serve(_mjpeg_stream(JPEG, JPEG))
        self.assertEqual(timelapse_capture.fetch_mjpeg_frame(url), JPEG)

    def test_a_stream_with_no_frame_raises(self):
        with self.assertRaises(ValueError):
            timelapse_capture.fetch_mjpeg_frame(self.serve(b"<html>not a camera</html>", "text/html"))

    def test_an_oversized_frame_raises(self):
        big = b"\xff\xd8" + b"x" * 64 + b"\xff\xd9"
        with mock.patch.object(timelapse_capture, "MAX_FRAME_BYTES", 8):
            with self.assertRaises(ValueError):
                timelapse_capture.fetch_mjpeg_frame(self.serve(_mjpeg_stream(big)))


class BeginExplicitUrlTests(unittest.TestCase):
    """#373: a caller with a per-printer camera source passes it explicitly."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "cache"

    def test_explicit_url_skips_the_settings_source(self):
        data = make_data(self.cache)
        data["services"]["camera_snapshot_url"] = ""  # no settings source at all
        session = timelapse_capture.begin(
            "job:9", "a.gcode", data=data,
            url="http://192.0.2.10:8080/?action=stream", fetch=lambda url: JPEG)
        self.assertIsNotNone(session)
        self.assertEqual(session.url, "http://192.0.2.10:8080/?action=stream")
        session.stop()

    def test_explicit_url_still_honours_the_capture_gate(self):
        data = make_data(self.cache, capture_enabled=False)
        self.assertIsNone(timelapse_capture.begin(
            "job:9", "a.gcode", data=data,
            url="http://192.0.2.10:8080/?action=stream", fetch=lambda url: JPEG))
        self.assertFalse((self.cache / "timelapse").exists())


if __name__ == "__main__":
    unittest.main()
