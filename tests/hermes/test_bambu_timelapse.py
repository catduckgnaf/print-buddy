"""Bambu launched-print timelapse (#295 stage 3), offline throughout.

The monitor's status/camera/source/post/encode functions are injected
fakes; the full-lifecycle test drives a real capture session fed by
real JPEG stills and encodes with the real ffmpeg (skipped where no
ffmpeg/ffprobe exists). No socket, no printer, no chat is ever touched.
The pre-#295 behaviour — the completion post carrying the final
snapshot — is the pinned fallback whenever capture produces no video.
"""
import io
import shutil
import subprocess
import types
from pathlib import Path

import pytest
from PIL import Image

from print_buddy.hermes import bambu_watch, timelapse_capture
from print_buddy.hermes import moonraker_event_listener as mel
from print_buddy.hermes import visual_watch as vw
from print_buddy.printers.bambulab import camera as bambulab_camera

REMOTE = "benchy_abc.gcode.3mf"
TCP_SOURCE = "bambu-camera://192.0.2.30/tcp6000"
JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body" + b"\xff\xd9"

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def jpeg_bytes(colour):
    out = io.BytesIO()
    Image.new("RGB", (320, 240), colour).save(out, format="JPEG")
    return out.getvalue()


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def scripted(values):
    items = list(values)

    def next_value():
        item = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(item, Exception):
            raise item
        return item

    return next_value


def st(state, filename=REMOTE, layer=3):
    return {"state": state, "filename": filename, "layer": layer, "total_layer": 40,
            "progress": 0.5, "print_duration": None}


class FakeSession:
    def __init__(self, frames=3, failures=0):
        self.frames = frames
        self.failures = failures
        self.ticks = 0
        self.stopped = None
        self.filename = REMOTE
        self.frames_dir = Path("/unused/frames")
        self.directory = Path("/unused")

    def tick(self):
        self.ticks += 1
        return True

    def stop(self, state="complete"):
        self.stopped = state
        return {"state": state, "frames": self.frames}

    @property
    def frame_count(self):
        return self.frames


class Rig:
    """A monitor wired to recorders; every collaborator is a fake."""

    def __init__(self, statuses, *, camera=JPEG, camera_source=(TCP_SOURCE, "fetch"),
                 session="default", encode=None, **monitor_kwargs):
        self.posts = []
        self.begins = []
        self.encodes = []
        self.session = FakeSession() if session == "default" else session
        self.clock = FakeClock()
        self.monitor = bambu_watch.BambuPrintMonitor(
            REMOTE,
            status_fn=scripted(statuses),
            camera_fn=lambda: (_ for _ in ()).throw(camera) if isinstance(camera, Exception) else camera,
            camera_source_fn=scripted([camera_source]),
            post=self.posts.append,
            begin_fn=self._begin,
            encode_fn=encode or self._encode,
            clock=self.clock, wall=self.clock, sleep=self.clock.sleep,
            poll_s=30.0, capture_poll_s=0.5, **monitor_kwargs)

    def _begin(self, url, fetch):
        self.begins.append((url, fetch))
        return self.session

    def _encode(self, session):
        self.encodes.append(session)
        return Path("/tmp/timelapse.mp4")


@pytest.fixture(autouse=True)
def frame_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_WATCH_FRAME_DIR", str(tmp_path / "frames"))


@pytest.fixture(autouse=True)
def capture_logs(monkeypatch):
    rigs = []
    monkeypatch.setattr(bambu_watch, "log", lambda line: rigs.append(str(line)))
    return rigs


# -- the happy path -------------------------------------------------------------


def test_completion_posts_the_timelapse_through_the_media_marker(capture_logs):
    rig = Rig([st("printing"), st("printing"), st("complete")])
    assert rig.monitor.run() == "complete"
    assert rig.begins == [(TCP_SOURCE, "fetch")]
    assert rig.session.stopped == "complete"
    assert len(rig.encodes) == 1
    assert len(rig.posts) == 1
    assert "MEDIA:/tmp/timelapse.mp4" in rig.posts[0]


def test_standby_after_printing_is_a_completion_with_video(capture_logs):
    rig = Rig([st("printing"), st("standby")])
    assert rig.monitor.run() == "complete"
    assert len(rig.posts) == 1 and "MEDIA:/tmp/timelapse.mp4" in rig.posts[0]


def test_errored_print_posts_once_with_video(capture_logs):
    rig = Rig([st("printing"), st("paused"), st("error")])
    assert rig.monitor.run() == "error"
    assert rig.session.stopped == "error"
    assert len(rig.posts) == 1


def test_completion_without_ever_printing_posts_the_final_snapshot(capture_logs):
    # The print finished between the start confirmation and the first
    # poll: no capture was ever opened, so the completion keeps the
    # pre-#295 shape — the final snapshot through the MEDIA: marker.
    rig = Rig([st("complete")])
    assert rig.monitor.run() == "complete"
    assert rig.begins == []
    assert len(rig.posts) == 1 and "MEDIA:" in rig.posts[0]
    assert ".mp4" not in rig.posts[0]


# -- dedupe ------------------------------------------------------------------------


def test_duplicate_polls_flaps_and_reconnects_never_duplicate(capture_logs):
    rig = Rig([st("printing"), RuntimeError("read failed"), st("printing"),
               st("paused"), st("printing"), st("complete"), st("complete")])
    assert rig.monitor.run() == "complete"
    assert len(rig.begins) == 1                 # one session, opened once
    assert len(rig.posts) == 1                  # one completion post


def test_a_different_print_taking_over_posts_nothing(capture_logs):
    rig = Rig([st("printing"), st("printing", "other.gcode.3mf"), st("complete", "other.gcode.3mf")])
    assert rig.monitor.run() is None
    assert rig.posts == []
    assert rig.session.stopped == "superseded"


def test_a_terminal_state_for_another_print_is_ignored(capture_logs):
    rig = Rig([st("complete", "other.gcode.3mf")])
    assert rig.monitor.run() is None
    assert rig.posts == [] and rig.begins == []


# -- the fail-soft paths: capture trouble degrades to the snapshot, then the text ----


def test_no_verified_camera_source_posts_the_snapshot_with_a_diagnostic(capture_logs):
    rig = Rig([st("printing"), st("complete")], camera_source=("", None))
    assert rig.monitor.run() == "complete"
    assert rig.begins == []
    assert len(rig.posts) == 1 and "MEDIA:" in rig.posts[0] and ".mp4" not in rig.posts[0]
    assert any("no verified camera source" in line for line in capture_logs)


def test_camera_source_read_failure_posts_the_snapshot(capture_logs):
    rig = Rig([st("printing"), st("complete")])
    rig.monitor._camera_source_fn = scripted([RuntimeError("fan-out not running")])
    assert rig.monitor.run() == "complete"
    assert rig.begins == []
    assert len(rig.posts) == 1 and "MEDIA:" in rig.posts[0] and ".mp4" not in rig.posts[0]
    assert any("could not be read" in line for line in capture_logs)


def test_capture_unavailable_posts_the_snapshot_and_is_attempted_once(capture_logs):
    rig = Rig([st("printing"), st("printing"), st("complete")], session=None)
    assert rig.monitor.run() == "complete"
    assert len(rig.begins) == 1                 # attempted once, never retried per poll
    assert len(rig.posts) == 1 and "MEDIA:" in rig.posts[0] and ".mp4" not in rig.posts[0]
    assert any("capture unavailable" in line for line in capture_logs)


def test_encode_failure_posts_the_final_snapshot_and_logs(capture_logs):
    def encode(session):
        raise RuntimeError("ffmpeg exploded")

    rig = Rig([st("printing"), st("complete")], encode=encode)
    assert rig.monitor.run() == "complete"
    assert len(rig.posts) == 1 and "MEDIA:" in rig.posts[0] and ".mp4" not in rig.posts[0]
    assert any("encode failed" in line for line in capture_logs)


def test_stills_source_failing_posts_the_snapshot_and_logs_the_failures(capture_logs):
    rig = Rig([st("printing"), st("complete")], session=FakeSession(frames=0, failures=4))
    assert rig.monitor.run() == "complete"
    assert rig.encodes == []
    assert len(rig.posts) == 1 and "MEDIA:" in rig.posts[0] and ".mp4" not in rig.posts[0]
    assert any("no frames" in line and "4 failed fetch" in line for line in capture_logs)


def test_no_frames_and_no_snapshot_posts_the_text_only(capture_logs):
    from print_buddy.printers.bambulab.client import BambuLanError
    rig = Rig([st("printing"), st("complete")], session=FakeSession(frames=0, failures=2),
              camera=BambuLanError("the camera did not answer"))
    assert rig.monitor.run() == "complete"
    assert len(rig.posts) == 1 and "MEDIA:" not in rig.posts[0]


def test_oversize_video_posts_the_too_large_line_with_the_snapshot(capture_logs, monkeypatch):
    monkeypatch.setattr(bambu_watch, "_too_big_text", lambda: "RECORDED BUT TOO LARGE")
    rig = Rig([st("printing"), st("complete")], encode=lambda session: None)
    assert rig.monitor.run() == "complete"
    assert len(rig.posts) == 1
    assert "RECORDED BUT TOO LARGE" in rig.posts[0]
    assert "MEDIA:" in rig.posts[0] and ".mp4" not in rig.posts[0]  # the snapshot still goes out


def test_media_post_failure_falls_back_to_the_snapshot_post(capture_logs):
    rig = Rig([st("printing"), st("complete")])
    posts = []

    def flaky_post(message):
        posts.append(message)
        if ".mp4" in message:
            raise RuntimeError("platform refused the attachment")

    rig.monitor._post = flaky_post
    assert rig.monitor.run() == "complete"
    assert len(posts) == 2
    assert ".mp4" in posts[0]
    assert "MEDIA:" in posts[1] and ".mp4" not in posts[1]
    assert any("post with timelapse failed" in line for line in capture_logs)


# -- the watchdog is not disturbed ---------------------------------------------------


def test_capture_and_the_watchdog_run_side_by_side(capture_logs):
    alerts = []
    rig = Rig(
        [st("printing", layer=1), st("printing", layer=2), st("complete")],
        watch=vw.VisualPrintWatch(sensitivity=3),
        verdict=lambda image, prompt: ("spaghetti", "tangled mess under the nozzle"),
        alert=lambda filename, image, reason: alerts.append((filename, image, reason)),
        changed=lambda before, after: True)
    assert rig.monitor.run() == "complete"
    assert len(rig.begins) == 1
    assert len(alerts) == 1 and "spaghetti" in alerts[0][2]
    assert "MEDIA:/tmp/timelapse.mp4" in rig.posts[0]


# -- the per-family frame source ---------------------------------------------------


class FakeSourceAdapter:
    def __init__(self, kind, *, configured=True, host="192.0.2.30"):
        self._kind = kind
        self._configured = configured
        self._host = host

    def camera_kind(self):
        return self._kind

    def lan_configured(self):
        return self._configured

    def client(self):
        return types.SimpleNamespace(host=self._host)

    def access_code(self):
        return "the-access-code"


def test_timelapse_source_tcp6000_names_the_route_and_fetches_through_the_client(monkeypatch):
    built = {}

    class StubClient:
        def __init__(self, host, access_code):
            built.update(host=host, access_code=access_code)

        def snapshot(self):
            return JPEG

    monkeypatch.setattr(bambulab_camera, "BambuCameraClient", StubClient)
    url, fetch = bambu_watch._timelapse_source(FakeSourceAdapter("tcp6000"))
    assert url == TCP_SOURCE
    assert built == {"host": "192.0.2.30", "access_code": "the-access-code"}
    assert fetch("https://ignored.example/") == JPEG  # the client route ignores the name


def test_timelapse_source_rtsps_reads_the_go2rtc_fanout_still(monkeypatch):
    monkeypatch.setattr(bambulab_camera, "fanout_frame_url",
                        lambda host, code: "http://127.0.0.1:1984/api/frame.jpeg?src=printer")
    url, fetch = bambu_watch._timelapse_source(FakeSourceAdapter("rtsps"))
    assert url == "http://127.0.0.1:1984/api/frame.jpeg?src=printer"
    assert fetch is bambulab_camera.fetch_url_jpeg


def test_timelapse_source_unverified_model_and_unconfigured_lan_resolve_to_none():
    assert bambu_watch._timelapse_source(FakeSourceAdapter(None)) == ("", None)
    assert bambu_watch._timelapse_source(FakeSourceAdapter("tcp6000", configured=False)) == ("", None)


def test_start_monitor_wires_the_adapter_and_starts_one_thread():
    # The print already finished by the first poll: the monitor posts the
    # completion (with the final snapshot) without ever opening a capture.
    adapter = FakeSourceAdapter("tcp6000")
    adapter.client = lambda: types.SimpleNamespace(
        host="192.0.2.30", snapshot=lambda: {"print": {"gcode_state": "FINISH", "gcode_file": REMOTE}})
    from print_buddy.printers.bambulab.adapter import BambuAdapter
    adapter.normalize_status = lambda raw: BambuAdapter.normalize_status(
        object.__new__(BambuAdapter), raw)
    adapter.camera_snapshot = lambda: JPEG
    posts, targets = [], []

    class _Thread:
        def __init__(self, target):
            self._target = target

        def start(self):
            self._target()

    def factory(target):
        targets.append(target)
        return _Thread(target)

    thread = bambu_watch.start_monitor(adapter, REMOTE, post=posts.append,
                                       thread_factory=factory)
    assert thread is not None and len(targets) == 1
    assert len(posts) == 1 and "MEDIA:" in posts[0] and ".mp4" not in posts[0]


# -- the full lifecycle: real session, real JPEG stills, real ffmpeg -------------------


@pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="needs ffmpeg and ffprobe on PATH")
def test_full_lifecycle_produces_a_valid_h264_mp4_under_the_limit(tmp_path, monkeypatch):
    # Three recorded JPEG stills (the form both Bambu routes serve); the
    # fetch hands each to a real capture session, exactly as
    # start_monitor wires it for a port-6000 model.
    stills = scripted([jpeg_bytes(colour) for colour in ("red", "green", "blue")])
    clock = FakeClock()
    root = tmp_path / "cache" / "timelapse"

    def begin_fn(url, fetch):
        session = timelapse_capture.CaptureSession(
            root, REMOTE, REMOTE,
            trigger=timelapse_capture.make_trigger("interval", 0.5),
            max_frames=100, max_bytes=0, url=url,
            fetch=fetch, log=lambda _line: None, now=clock)
        assert session.start()
        return session

    monkeypatch.setattr(mel, "_media_upload_limit", lambda: 500_000)
    posts = []
    monitor = bambu_watch.BambuPrintMonitor(
        REMOTE,
        status_fn=scripted([st("printing"), st("printing"), st("printing"),
                            st("printing"), st("complete")]),
        camera_fn=lambda: JPEG,
        camera_source_fn=lambda: (TCP_SOURCE, lambda _url: stills()),
        post=posts.append,
        begin_fn=begin_fn,
        clock=clock, wall=clock, sleep=clock.sleep, poll_s=30.0, capture_poll_s=0.5)
    assert monitor.run() == "complete"
    assert len(posts) == 1 and "MEDIA:" in posts[0]
    video = Path(posts[0].split("MEDIA:", 1)[1].strip())
    assert video.is_file() and 0 < video.stat().st_size <= 500_000
    probe = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                            str(video)], capture_output=True, text=True, check=True)
    assert probe.stdout.strip() == "h264"
    session_dir = next(root.iterdir())
    frames = list((session_dir / "frames").glob("frame-*.jpg"))
    assert len(frames) >= 2
    assert frames[0].read_bytes().startswith(b"\xff\xd8")  # stored frames are JPEG
