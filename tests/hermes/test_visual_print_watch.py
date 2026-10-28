"""Offline tests for the visual watchdog trigger policy."""
import sys
from pathlib import Path
from print_buddy.hermes import moonraker_event_listener as mel
from print_buddy.hermes import print_alert_buttons as pab


def test_strip_json_fence_and_profile_adapter(monkeypatch):
    import json
    assert mel._strip_json_fence('```json\n{"verdict":"empty_idle","reason":"bed clear"}\n```') == '{"verdict":"empty_idle","reason":"bed clear"}'

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": '```json\n{"verdict":"empty_idle","reason":"idle bed"}\n```'}}]}).encode()

    seen = {}

    def fake_open(req, timeout=0):
        seen["body"] = json.loads(req.data)
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(mel, "_profile_env_value", lambda name: "test-key")
    monkeypatch.setattr(mel.urllib.request, "urlopen", fake_open)
    verdict, reason = mel._visual_verdict(b"frame", "idle snapshot")
    assert verdict == "empty_idle" and reason == "idle bed"
    assert seen["body"]["temperature"] == 0
    assert seen["body"]["model"] == "gemini-latest"
    assert "Flashforge AD5X" in seen["body"]["messages"][0]["content"][0]["text"]
    assert "empty_idle" not in mel.VISUAL_ALERT_VERDICTS
    assert mel.VISUAL_ALERT_VERDICTS == {"air", "spaghetti", "detached", "uncertain"}


def test_visual_alert_posts_image_and_components_together(monkeypatch, tmp_path):
    frame_dir = tmp_path / "frames"
    seen = {}

    def posted(token, channel_id, content, filename, image):
        seen.update(token=token, channel_id=channel_id, content=content, filename=filename, image=image)
        return True

    monkeypatch.setenv("PRINT_WATCH_FRAME_DIR", str(frame_dir))
    monkeypatch.setattr(mel, "_profile_env_value", lambda name: "test-token")
    monkeypatch.setattr(mel.announcer, "DISCORD_CHAT_ID", "42")
    monkeypatch.setattr(pab, "post_visual_alert", posted)
    monkeypatch.setattr(mel, "post", lambda text: (_ for _ in ()).throw(AssertionError("plain fallback used")))
    path = mel._visual_alert("job.gcode", _jpeg(), "stalled_layers at layer 48")
    assert path == seen["image"] and path.read_bytes() == _jpeg()
    assert seen["filename"] == "job.gcode" and "Buttons:" not in seen["content"]


def test_visual_alert_plain_fallback_has_no_fake_buttons(monkeypatch, tmp_path):
    monkeypatch.setenv("PRINT_WATCH_FRAME_DIR", str(tmp_path / "frames"))
    monkeypatch.setattr(mel, "_profile_env_value", lambda name: "test-token")
    monkeypatch.setattr(pab, "post_visual_alert", lambda *args: False)
    posted = []
    monkeypatch.setattr(mel, "post", posted.append)
    mel._visual_alert("job.gcode", _jpeg(), "stalled_layers at layer 48")
    assert posted and "Buttons:" not in posted[0] and "MEDIA:" in posted[0]


def test_layer_two_empty_bed_requests_check_and_alert_on_air(monkeypatch):
    watch = mel.VisualPrintWatch()
    calls = []
    monkeypatch.setattr(mel, "_visual_verdict", lambda image, prompt: ("air", "empty bed"))
    monkeypatch.setattr(mel, "_visual_alert", lambda filename, image, reason: calls.append(reason))
    assert watch.due(1, 10) is None
    assert watch.due(2, 11) == "layer2"
    watch.record(2, 11, b"frame")
    verdict, detail = mel._visual_verdict(b"frame", "is there plastic?")
    if verdict in {"air", "no", "unsafe", "uncertain"}:
        mel._visual_alert("test.gcode", b"frame", f"layer2: {verdict}; {detail}")
    assert calls and "air" in calls[0]


def test_layer_progression_without_visual_change_triggers_alert():
    watch = mel.VisualPrintWatch()
    watch.layer2_checked = watch.layer5_checked = True
    watch.record(5, 100, b"frame")
    assert watch.due(9, 101, snapshot_changed=False) == "stalled_layers"
    assert watch.due(12, 102, snapshot_changed=False) is None


def test_layer_progression_after_normal_snapshot_does_not_false_trigger():
    watch = mel.VisualPrintWatch()
    watch.layer2_checked = watch.layer5_checked = True
    watch.record(5, 100, b"frame")
    assert watch.due(6, 101, snapshot_changed=True) is None
    watch.record(6, 102, b"changed-frame")
    assert watch.due(9, 103, snapshot_changed=True) is None


def test_normal_print_waits_for_periodic_interval():
    watch = mel.VisualPrintWatch()
    watch.layer2_checked = watch.layer5_checked = True
    watch.record(5, 100, b"frame")
    assert watch.due(6, 200, snapshot_changed=True) is None
    assert watch.due(8, 1001, snapshot_changed=True) == "periodic"


def test_layer_two_trigger_only_once():
    watch = mel.VisualPrintWatch()
    assert watch.due(2, 10) == "layer2"
    assert watch.due(3, 20) is None


def _jpeg():
    return bytes((0xff, 0xd8, 0xff, 0xd9))


def test_session_due_signature_schedules_stall_probe():
    """The live loop calls due(layer, now) with no snapshot flag."""
    watch = mel.VisualPrintWatch()
    watch.layer2_checked = watch.layer5_checked = True
    watch.record(5, 100, _jpeg())
    assert watch.due(8, 200) == "layer_progress"
    assert watch.due(9, 201) == "layer_progress"
    assert watch.due(6, 250) is None


def test_visual_check_alerts_on_air_uncertain_and_endpoint_error(monkeypatch):
    import asyncio

    alerts = []
    monkeypatch.setattr(mel, "_camera_snapshot_bytes", lambda: _jpeg())
    monkeypatch.setattr(mel, "_visual_alert", lambda filename, image, reason: alerts.append(reason) or reason)

    async def run(verdict):
        monkeypatch.setattr(mel, "_visual_verdict", lambda image, prompt: verdict)
        listener = mel.Listener()
        listener.filename = "bin.gcode"
        await listener.visual_check("layer2", 2)

    asyncio.run(run(("air", "empty bed")))
    asyncio.run(run(("uncertain", "model unsure")))

    def boom(image, prompt):
        raise OSError("endpoint down")

    async def run_boom():
        monkeypatch.setattr(mel, "_visual_verdict", boom)
        listener = mel.Listener()
        listener.filename = "bin.gcode"
        await listener.visual_check("layer2", 2)

    asyncio.run(run_boom())
    assert any("air" in item for item in alerts)
    assert any("uncertain" in item for item in alerts)
    assert any("the vision check could not be completed" in item for item in alerts)
    assert all("endpoint down" not in item and "OSError" not in item for item in alerts)  # raw detail demoted (#467)


def test_visual_check_promotes_unchanged_layers_and_ignores_motion(monkeypatch):
    import asyncio

    alerts = []
    frames = {"n": 0}

    def snapshot():
        frames["n"] += 1
        return _jpeg() + bytes((frames["n"],))

    monkeypatch.setattr(mel, "_camera_snapshot_bytes", snapshot)
    monkeypatch.setattr(mel, "_visual_alert", lambda filename, image, reason: alerts.append(reason))
    monkeypatch.setattr(mel, "_visual_verdict", lambda image, prompt: ("safe", "plastic present"))

    async def unchanged():
        listener = mel.Listener()
        listener.filename = "air.gcode"
        listener.visual_watch.layer2_checked = True
        listener.visual_watch.layer5_checked = True
        listener.visual_frames["air.gcode"] = _jpeg() + bytes((1,))
        listener.visual_watch.record(5, 100, listener.visual_frames["air.gcode"])
        monkeypatch.setattr(mel, "_frame_changed", lambda before, after: False)
        reason = listener.visual_watch.due(9, 200)
        assert reason == "layer_progress"
        await listener.visual_check(reason, 9)
        return listener

    listener = asyncio.run(unchanged())
    assert alerts and "stalled_layers" in alerts[0]
    assert listener.visual_watch.alerted_stall_layer == 9

    alerts.clear()

    async def moving():
        listener = mel.Listener()
        listener.filename = "ok.gcode"
        listener.visual_watch.layer2_checked = True
        listener.visual_watch.layer5_checked = True
        listener.visual_frames["ok.gcode"] = _jpeg()
        listener.visual_watch.record(5, 100, _jpeg())
        monkeypatch.setattr(mel, "_frame_changed", lambda before, after: True)
        reason = listener.visual_watch.due(9, 200)
        await listener.visual_check(reason, 9)
        assert listener.visual_watch.due(10, 250) is None
        assert listener.visual_watch.due(12, 260) == "layer_progress"

    asyncio.run(moving())
    assert alerts == []


def test_sensitivity_three_is_the_original_behavior():
    profile = mel.VISUAL_SENSITIVITY[3]
    assert profile == {"diff": 3.0, "stall_layers": 3, "periodic_s": 900, "vision_veto": False}
    assert mel.VisualPrintWatch().sensitivity == 3  # home.toml default


def test_sensitivity_scales_stall_layers():
    for level, needed in ((1, 8), (2, 5), (3, 3), (4, 3), (5, 2)):
        watch = mel.VisualPrintWatch(level)
        watch.layer2_checked = watch.layer5_checked = True
        watch.record(5, 100, b"frame")
        assert watch.due(5 + needed - 1, 101, snapshot_changed=False) is None, level
        assert watch.due(5 + needed, 102, snapshot_changed=False) == "stalled_layers", level


def test_sensitivity_scales_periodic_interval():
    for level, seconds in ((1, 1800), (3, 900), (5, 450)):
        watch = mel.VisualPrintWatch(level)
        watch.layer2_checked = watch.layer5_checked = True
        watch.record(5, 0, b"frame")
        assert watch.due(6, seconds - 1, snapshot_changed=True) is None, level
        assert watch.due(6, seconds, snapshot_changed=True) == "periodic", level


def test_sensitivity_rejects_out_of_range():
    import pytest
    for bad in (0, 6):
        with pytest.raises(ValueError):
            mel.VisualPrintWatch(bad)


def test_frame_change_threshold_follows_sensitivity(monkeypatch):
    import io
    from PIL import Image

    def frame(gray):
        buf = io.BytesIO()
        Image.new("L", (64, 48), gray).save(buf, "JPEG", quality=100)
        return buf.getvalue()

    before, after = frame(100), frame(103)  # mean difference of about 3
    assert mel._frame_changed(before, after, threshold=mel.VISUAL_SENSITIVITY[1]["diff"]) is True
    assert mel._frame_changed(before, after, threshold=mel.VISUAL_SENSITIVITY[5]["diff"]) is False


def _stall_alerts(monkeypatch, level, verdict):
    import asyncio

    alerts = []
    monkeypatch.setattr(mel, "_camera_snapshot_bytes", lambda: _jpeg() + b"x")
    monkeypatch.setattr(mel, "_visual_alert", lambda filename, image, reason: alerts.append(reason))
    monkeypatch.setattr(mel, "_frame_changed", lambda before, after: False)
    if isinstance(verdict, Exception):
        def failing(image, prompt):
            raise verdict
        monkeypatch.setattr(mel, "_visual_verdict", failing)
    else:
        monkeypatch.setattr(mel, "_visual_verdict", lambda image, prompt: verdict)

    async def run():
        listener = mel.Listener()
        listener.visual_watch = mel.VisualPrintWatch(level)
        listener.filename = "still.gcode"
        listener.visual_watch.layer2_checked = listener.visual_watch.layer5_checked = True
        listener.visual_frames["still.gcode"] = _jpeg()
        listener.visual_watch.record(5, 100, _jpeg())
        layer = 5 + listener.visual_watch.profile["stall_layers"]
        await listener.visual_check(listener.visual_watch.due(layer, 200), layer)

    asyncio.run(run())
    return alerts


def test_low_sensitivity_trusts_healthy_vision_on_a_stall(monkeypatch):
    for level in (1, 2):
        assert _stall_alerts(monkeypatch, level, ("ok", "")) == [], level
        assert _stall_alerts(monkeypatch, level, ("safe", "plastic present")) == [], level


def test_low_sensitivity_still_alerts_on_a_bad_stall(monkeypatch):
    for level in (1, 2):
        for verdict in (("air", "empty"), ("spaghetti", "mess"), ("uncertain", "dark")):
            alerts = _stall_alerts(monkeypatch, level, verdict)
            assert alerts and "stalled_layers" in alerts[0] and verdict[0] in alerts[0], (level, verdict)
        alerts = _stall_alerts(monkeypatch, level, OSError("vision down"))
        assert alerts and "the vision check could not be completed" in alerts[0], level


def test_default_and_higher_sensitivity_alert_on_every_stall(monkeypatch):
    for level in (3, 4, 5):
        alerts = _stall_alerts(monkeypatch, level, ("ok", ""))
        assert alerts and "stalled_layers" in alerts[0], level


DIRECT_URL = "http://printer.example/webcam/?action=snapshot"
FANOUT_URL = "http://127.0.0.1:1984/api/frame.jpeg?src=camera"


def _record_snapshot_requests(monkeypatch, fanout, fail_urls=()):
    """Route _camera_snapshot_bytes at a fake transport; return the URLs hit."""
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _n=-1):
            return _jpeg()

    def fake_open(req, timeout=0):
        seen.append(req.full_url)
        if req.full_url in fail_urls:
            raise ConnectionError("refused")
        return Response()

    monkeypatch.setattr(mel, "_camera_url", lambda: DIRECT_URL)
    monkeypatch.setattr(mel, "_config", type("Cfg", (), {"cfg": staticmethod(lambda: {})})())
    monkeypatch.setattr(mel.go2rtc, "fanout_frame_url", lambda data: fanout)
    monkeypatch.setattr(mel, "log", lambda line: None)
    monkeypatch.setattr(mel.urllib.request, "urlopen", fake_open)
    return seen


def test_watchdog_snapshot_uses_go2rtc_fanout_when_it_is_running(monkeypatch):
    seen = _record_snapshot_requests(monkeypatch, FANOUT_URL)
    assert mel._camera_snapshot_bytes() == _jpeg()
    assert seen == [FANOUT_URL]  # the direct camera URL is never opened


def test_watchdog_snapshot_is_direct_when_no_fanout_feature_is_on(monkeypatch):
    seen = _record_snapshot_requests(monkeypatch, None)
    assert mel._camera_snapshot_bytes() == _jpeg()
    assert seen == [DIRECT_URL]


def test_watchdog_snapshot_falls_back_direct_when_the_fanout_fails(monkeypatch):
    seen = _record_snapshot_requests(monkeypatch, FANOUT_URL, fail_urls={FANOUT_URL})
    assert mel._camera_snapshot_bytes() == _jpeg()
    assert seen == [FANOUT_URL, DIRECT_URL]  # sequential fallback, never parallel
