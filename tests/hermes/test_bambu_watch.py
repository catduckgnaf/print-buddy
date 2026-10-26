"""Bambu camera parity (#294): status images and the launched-print monitor, offline.

All transports are fakes: the adapter is a scripted stand-in, the monitor's
status/camera/post functions are injected, and the frame dir is a tmp path.
No socket, no printer, no chat is ever touched.
"""
import types

import pytest

from print_buddy.hermes import bambu_watch, print_stop
from print_buddy.printers.bambulab.client import BambuLanError

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body" + b"\xff\xd9"
REMOTE = "benchy_abc.gcode.3mf"


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
        if len(items) > 1:
            return items.pop(0)
        return items[0]

    return next_value


def st(state, filename=REMOTE, layer=3):
    return {"state": state, "filename": filename, "layer": layer, "total_layer": 40,
            "progress": 0.5, "print_duration": None}


class FakeAdapter:
    def __init__(self, statuses, *, configured=True, camera=JPEG):
        self._statuses = scripted(statuses)
        self._configured = configured
        self._camera = camera
        self.control_calls = []

    def lan_configured(self):
        return self._configured

    def client(self):
        return types.SimpleNamespace(snapshot=lambda: {})

    def normalize_status(self, raw):
        return self._statuses()

    def camera_snapshot(self):
        if isinstance(self._camera, Exception):
            raise self._camera
        return self._camera

    def control(self, action):
        self.control_calls.append(action)


@pytest.fixture(autouse=True)
def frame_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_WATCH_FRAME_DIR", str(tmp_path / "frames"))


# -- Stage 2: status with camera ---------------------------------------------

def test_status_with_camera_returns_image_and_status():
    adapter = FakeAdapter([st("printing")])
    out = bambu_watch.status_with_camera(adapter)
    assert out["state"] == "printing" and out["filename"] == REMOTE
    assert out["camera_note"] == ""
    from pathlib import Path
    assert Path(out["camera_image_path"]).read_bytes() == JPEG


def test_status_with_camera_unconfigured_is_a_plain_note_never_an_exception():
    adapter = FakeAdapter([], configured=False)
    out = bambu_watch.status_with_camera(adapter)
    assert out["state"] == "unknown" and out["camera_image_path"] is None
    assert "camera is not configured" in out["camera_note"]


def test_status_with_camera_failure_is_a_note_not_an_exception():
    adapter = FakeAdapter([st("standby")], camera=BambuLanError("the camera did not send a usable image"))
    out = bambu_watch.status_with_camera(adapter)
    assert out["state"] == "standby" and out["camera_image_path"] is None
    assert "did not send a usable image" in out["camera_note"]


def test_print_stop_status_carries_the_camera_image_for_bambu(monkeypatch):
    adapter = FakeAdapter([st("printing")])
    monkeypatch.setattr(print_stop, "_lan_adapter", lambda: adapter)
    out = print_stop.status()
    assert out["state"] == "printing"
    assert out["camera_image_path"] and out["camera_note"] == ""


# -- Stage 2: the launched-print monitor --------------------------------------

def _monitor(statuses, camera=JPEG):
    posts = []
    clock = FakeClock()
    monitor = bambu_watch.BambuPrintMonitor(
        REMOTE, status_fn=scripted(statuses),
        camera_fn=lambda: (_ for _ in ()).throw(camera) if isinstance(camera, Exception) else camera,
        post=posts.append, clock=clock, wall=clock, sleep=clock.sleep, poll_s=10)
    return monitor, posts


def test_monitor_posts_completion_with_the_final_snapshot():
    monitor, posts = _monitor([st("printing"), st("printing"), st("complete")])
    assert monitor.run() == "complete"
    assert len(posts) == 1
    assert posts[0].startswith("Print complete")
    assert "MEDIA:" in posts[0]


def test_monitor_completion_without_a_camera_still_posts_the_text():
    monitor, posts = _monitor([st("error")], camera=BambuLanError("the camera did not answer"))
    assert monitor.run() == "error"
    assert len(posts) == 1 and "MEDIA:" not in posts[0]


def test_monitor_ignores_a_different_print():
    monitor, posts = _monitor([st("printing", filename="other.gcode.3mf"), st("complete", filename="other.gcode.3mf")])
    assert monitor.run() is None
    assert posts == []


def test_monitor_treats_standby_after_printing_as_completion():
    monitor, posts = _monitor([st("printing"), st("standby")])
    assert monitor.run() == "complete"
    assert len(posts) == 1


def test_start_monitor_with_injected_parts_uses_the_given_thread_factory():
    ran = []
    monitor_thread = bambu_watch.start_monitor(
        FakeAdapter([st("printing")]), REMOTE,
        status_fn=scripted([st("complete")]), camera_fn=lambda: JPEG,
        post=lambda text: ran.append(text),
        thread_factory=lambda target: types.SimpleNamespace(start=lambda: target()))
    assert monitor_thread is not None
    assert len(ran) == 1 and "MEDIA:" in ran[0]


