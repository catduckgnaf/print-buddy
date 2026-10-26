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


# -- Stage 3: the camera watchdog ----------------------------------------------

from print_buddy.hermes import visual_watch as vw


def _watch_monitor(*, sensitivity=3, verdict=("ok", "looks fine"), changed=True):
    alerts = []
    clock = FakeClock()
    monitor = bambu_watch.BambuPrintMonitor(
        REMOTE, status_fn=scripted([st("complete")]), camera_fn=lambda: JPEG,
        post=lambda text: None,
        watch=vw.VisualPrintWatch(sensitivity=sensitivity),
        verdict=lambda image, prompt: verdict,
        alert=lambda filename, image, reason: alerts.append((filename, image, reason)),
        changed=lambda before, after: changed,
        clock=clock, wall=clock, sleep=clock.sleep, poll_s=10)
    return monitor, alerts, clock


def test_watchdog_alerts_on_a_suspicious_verdict_with_the_snapshot():
    monitor, alerts, _clock = _watch_monitor(verdict=("spaghetti", "tangled mess under the nozzle"))
    monitor.poll_active(st("printing", layer=1))
    assert alerts == []
    monitor.poll_active(st("printing", layer=2))
    assert len(alerts) == 1
    filename, image, reason = alerts[0]
    assert filename == REMOTE and image == JPEG
    assert "layer2" in reason and "spaghetti" in reason


def test_watchdog_stays_quiet_on_a_healthy_verdict():
    monitor, alerts, _clock = _watch_monitor(verdict=("ok", "plastic on the bed"))
    monitor.poll_active(st("printing", layer=2))
    monitor.poll_active(st("printing", layer=5))
    assert alerts == []


def test_watchdog_never_controls_the_printer_itself():
    # The monitor is not even given a control callable: with a suspicious
    # verdict the only outward effects are the alert and (later) posts.
    monitor, alerts, _clock = _watch_monitor(verdict=("detached", "part on the floor"))
    assert not hasattr(monitor, "control")
    monitor.poll_active(st("printing", layer=2))
    assert len(alerts) == 1


def test_stall_alerts_at_level_5_even_with_a_healthy_verdict():
    # Layer 2 and layer 5 checks run first (baselines recorded); the next
    # advance over an unchanged frame is the layer_progress stall probe.
    monitor, alerts, _clock = _watch_monitor(sensitivity=5, verdict=("ok", "looks fine"), changed=False)
    monitor.poll_active(st("printing", layer=2))
    monitor.poll_active(st("printing", layer=5))
    monitor.poll_active(st("printing", layer=8))
    assert len(alerts) == 1 and "stalled_layers" in alerts[0][2]


def test_stall_is_vetoed_by_a_healthy_verdict_at_level_1():
    monitor, alerts, _clock = _watch_monitor(sensitivity=1, verdict=("ok", "looks fine"), changed=False)
    monitor.poll_active(st("printing", layer=2))
    monitor.poll_active(st("printing", layer=5))
    monitor.poll_active(st("printing", layer=13))
    assert alerts == []


def test_periodic_checks_still_run_when_the_firmware_reports_no_layer():
    verdicts = []

    def verdict(image, prompt):
        verdicts.append(prompt)
        return "ok", "fine"

    clock = FakeClock()
    clock.t = 1000.0
    monitor = bambu_watch.BambuPrintMonitor(
        REMOTE, status_fn=scripted([st("complete")]), camera_fn=lambda: JPEG,
        post=lambda text: None,
        watch=vw.VisualPrintWatch(sensitivity=5),  # periodic_s = 450
        verdict=verdict, alert=lambda *args: None, changed=lambda a, b: True,
        clock=clock, wall=clock, sleep=clock.sleep, poll_s=10)
    no_layer = st("printing", layer=None)
    monitor.poll_active(no_layer)
    assert verdicts == []
    clock.t += 500
    monitor.poll_active(no_layer)
    assert len(verdicts) == 1


def test_visual_alert_delivery_posts_buttons_like_the_moonraker_alert(monkeypatch):
    from print_buddy.hermes import print_alert_buttons as pab
    seen = {}
    monkeypatch.setattr(pab, "post_visual_alert",
                        lambda token, chat, text, filename, path: seen.update(
                            token=token, chat=chat, text=text, filename=filename, path=path) or True)
    path = bambu_watch.deliver_visual_alert(REMOTE, JPEG, "layer2: spaghetti; test",
                                            post=lambda text: (_ for _ in ()).throw(AssertionError("fallback used")),
                                            token="tok", chat_id="42", buttonless=None)
    assert seen["path"] == path and seen["filename"] == REMOTE
    assert "Print camera check" in seen["text"]


def test_visual_alert_delivery_buttonless_posts_plain_media(monkeypatch):
    posts = []
    path = bambu_watch.deliver_visual_alert(REMOTE, JPEG, "periodic: uncertain; test",
                                            post=posts.append, token="tok", chat_id="42", buttonless="telegram")
    assert len(posts) == 1 and f"MEDIA:{path}" in posts[0]


# -- Stage 3: the alert's Pause button on Bambu ---------------------------------

def test_pause_sends_one_lan_pause_for_the_alerted_file(monkeypatch):
    from unittest import mock
    adapter, _client = _bambu_pause(monkeypatch, [bst2("printing"), bst2("paused")])
    with mock.patch.object(print_stop.time, "sleep"):
        sent, text = print_stop.pause("plate_1.gcode.3mf", wait_s=5)
    assert sent and "Paused" in text
    adapter.control.assert_called_once_with("pause")


def test_pause_refuses_a_different_file_without_sending(monkeypatch):
    from unittest import mock
    adapter, _client = _bambu_pause(monkeypatch, [bst2("printing", filename="other.gcode.3mf")])
    sent, text = print_stop.pause("plate_1.gcode.3mf")
    assert not sent and "different print" in text
    adapter.control.assert_not_called()


def test_handle_click_visual_pause_routes_to_the_bambu_pause(monkeypatch):
    from unittest import mock
    from print_buddy.hermes import print_alert_buttons as pab
    adapter, _client = _bambu_pause(monkeypatch, [bst2("printing"), bst2("paused")])
    with mock.patch.object(print_stop.time, "sleep"):
        text = pab.handle_click("pause", {"kind": "visual", "filename": "plate_1.gcode.3mf"})
    assert "Paused" in text
    adapter.control.assert_called_once_with("pause")


def bst2(state, filename="plate_1.gcode.3mf", layer=1, total=513, progress=0.01):
    return {"state": state, "filename": filename, "layer": layer, "total_layer": total, "progress": progress}


def _bambu_pause(monkeypatch, snapshots):
    """Route print_stop through a fake Bambu LAN adapter, as in test_print_stop.py."""
    from unittest import mock
    from print_buddy import printers
    client = mock.Mock()
    client.snapshot.side_effect = list(snapshots)
    adapter = types.SimpleNamespace(
        transport="bambulab_lan", lan_configured=lambda: True, client=lambda: client,
        normalize_status=lambda raw: raw, control=mock.Mock(),
        camera_snapshot=mock.Mock(side_effect=BambuLanError("no camera in this fake")))
    monkeypatch.setattr(printers, "current", lambda: adapter)
    return adapter, client
