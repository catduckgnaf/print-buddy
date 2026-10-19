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
    assert any("vision check failed" in item for item in alerts)


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
