"""Local ONNX failure detector (#455 Stage 1): verdict mapping, fail-soft
paths, route precedence and the settings/bot-check surfaces.

All offline. The detector runs against a tiny synthetic ONNX fixture
(fixtures/tiny_failure_detector.onnx, built by
fixtures/build_tiny_detector.py) that speaks the real model's I/O
contract — input [1, 3, H, W], outputs boxes [1, N, 1, 4] / confs
[1, N, 1] — with confidences driven by frame brightness, so each verdict
band is reachable with a solid-colour frame. Downloads are faked at the
urlopen seam; no test touches the network or the real 202 MB model.
"""
import copy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from print_handy import settings
from print_handy.hermes import _config, local_vision as lv, visual_watch as vw

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_failure_detector.onnx"
FIXTURE_SHA256 = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _fresh_detector_state(monkeypatch):
    """The detector caches sessions/failures per process; every test
    starts from a clean slate and no PRINT_VISION_URL leaks in."""
    monkeypatch.setattr(lv, "_sessions", {})
    monkeypatch.setattr(lv, "_failures", {})
    monkeypatch.setattr(lv, "_verified_files", set())
    monkeypatch.setattr(lv, "_ort", None)
    monkeypatch.setattr(lv, "_ort_error", None)
    monkeypatch.delenv("PRINT_VISION_URL", raising=False)


def frame(value, size=(120, 90)):
    buf = io.BytesIO()
    Image.new("RGB", size, (value, value, value)).save(buf, "JPEG")
    return buf.getvalue()


def cfg_with(**vision):
    base = {"local_detector_enabled": True, "local_model_path": str(FIXTURE)}
    base.update(vision)
    return {"vision": base, "paths": {"hermes_home": "/nonexistent-home"}}


@pytest.fixture
def process_cfg():
    """Install a full process config (deep copy of the live one) with the
    detector enabled against the fixture; restored on teardown."""
    previous = copy.deepcopy(_config.cfg())
    data = copy.deepcopy(previous)
    data["vision"]["local_detector_enabled"] = True
    data["vision"]["local_model_path"] = str(FIXTURE)
    _config.set_override(data)
    yield data
    _config.set_override(previous)


# --------------------------------------------------------------- verdict mapping


def test_bright_frame_is_a_failure_with_areas_counted():
    verdict, detail = lv.local_verdict(frame(235), cfg_with())
    assert verdict == "spaghetti"
    assert "100%" in detail and "2 areas" in detail


def test_mid_frame_is_uncertain_not_a_pass():
    verdict, detail = lv.local_verdict(frame(84), cfg_with())
    assert verdict == "uncertain"
    assert "35%" in detail


def test_dark_frame_is_ok():
    verdict, detail = lv.local_verdict(frame(13), cfg_with())
    assert verdict == "ok"
    assert "no failure detected" in detail


def test_detector_never_produces_endpoint_only_verdicts():
    for value in (0, 40, 84, 160, 235, 255):
        verdict, _ = lv.local_verdict(frame(value), cfg_with())
        assert verdict in ("ok", "uncertain", "spaghetti")


# --------------------------------------------------------------- post-processing


def _boxes(pairs):
    arr = np.zeros((1, len(pairs), 1, 4), dtype=np.float64)
    for i, (box, _conf) in enumerate(pairs):
        arr[0, i, 0] = box
    confs = np.array([[[c]] for _b, c in pairs], dtype=np.float64).reshape(1, len(pairs), 1)
    return arr, confs


def test_nms_suppresses_overlapping_weaker_boxes():
    boxes, confs = _boxes([
        ([0.10, 0.10, 0.50, 0.50], 0.9),
        ([0.15, 0.15, 0.55, 0.55], 0.8),   # IoU ~0.62 with box 0: suppressed
        ([0.70, 0.70, 0.95, 0.95], 0.7),   # disjoint: kept
        ([0.30, 0.60, 0.40, 0.70], 0.05),  # below the positive floor: dropped
    ])
    kept = lv._postprocess(boxes, confs)
    assert [round(c, 2) for c, _b in kept] == [0.9, 0.7]


def test_postprocess_rejects_unexpected_shapes():
    with pytest.raises(lv.LocalVisionError):
        lv._postprocess(np.zeros((3, 4)), np.zeros((3,)))


def test_preprocess_shape_range_and_dtype(monkeypatch):
    seen = {}

    class RecordingSession:
        def get_inputs(self):
            return [SimpleNamespace(name="input", shape=[1, 3, 64, 64])]

        def run(self, _outputs, feed):
            seen["tensor"] = feed["input"]
            boxes, confs = _boxes([([0.1, 0.1, 0.5, 0.5], 0.9)])
            return [boxes, confs]

    monkeypatch.setattr(lv, "_session", lambda path: RecordingSession())
    verdict, _detail = lv.local_verdict(frame(200, size=(37, 211)), cfg_with())
    assert verdict == "spaghetti"
    tensor = seen["tensor"]
    assert tensor.shape == (1, 3, 64, 64) and tensor.dtype == np.float32
    assert 0.0 <= float(tensor.min()) and float(tensor.max()) <= 1.0


# --------------------------------------------------------------- fail-soft paths


def test_missing_runtime_is_a_clean_failure(monkeypatch):
    monkeypatch.setattr(lv, "_ort_error", RuntimeError("no onnxruntime here"))
    with pytest.raises(lv.LocalVisionError, match="onnxruntime is not available"):
        lv.local_verdict(frame(200), cfg_with())
    state, detail = lv.detector_status(cfg_with())
    assert state == "unavailable" and "onnxruntime" in detail


def test_corrupt_model_fails_soft_and_sticks(monkeypatch, tmp_path):
    bad = tmp_path / "corrupt.onnx"
    bad.write_bytes(b"this is not an onnx model")
    cfg = cfg_with(local_model_path=str(bad))
    with pytest.raises(lv.LocalVisionError):
        lv.local_verdict(frame(200), cfg)
    # The failure is remembered: the second call fails the same way
    # without another load attempt (no repeated work per camera check).
    loads = []
    monkeypatch.setattr(lv, "_runtime", lambda: loads.append(1) or (_ for _ in ()).throw(
        AssertionError("runtime must not be retried")))
    with pytest.raises(lv.LocalVisionError):
        lv.local_verdict(frame(200), cfg)
    assert loads == []


def test_inference_error_degrades_to_local_vision_error(monkeypatch):
    class ExplodingSession:
        def get_inputs(self):
            return [SimpleNamespace(name="input", shape=[1, 3, 64, 64])]

        def run(self, _outputs, _feed):
            raise RuntimeError("tensor exploded")

    monkeypatch.setattr(lv, "_session", lambda path: ExplodingSession())
    with pytest.raises(lv.LocalVisionError, match="inference failed"):
        lv.local_verdict(frame(200), cfg_with())


def test_unreadable_frame_is_a_failed_check_not_a_crash():
    with pytest.raises(lv.LocalVisionError):
        lv.local_verdict(b"not a jpeg at all", cfg_with())


# --------------------------------------------------------------- model download


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def test_missing_model_downloads_once_and_verifies(monkeypatch, tmp_path):
    target = tmp_path / "models" / "detector.onnx"
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        return _FakeResponse(FIXTURE.read_bytes())

    monkeypatch.setattr(lv, "MODEL_SHA256", FIXTURE_SHA256)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = cfg_with(local_model_path=str(target))
    verdict, _ = lv.local_verdict(frame(235), cfg)
    assert verdict == "spaghetti"
    assert target.read_bytes() == FIXTURE.read_bytes()
    assert calls == [lv.MODEL_URL]  # the pinned source, fetched exactly once
    verdict, _ = lv.local_verdict(frame(235), cfg)
    assert verdict == "spaghetti" and len(calls) == 1  # file + session are reused


def test_download_with_wrong_checksum_is_refused(monkeypatch, tmp_path):
    target = tmp_path / "detector.onnx"
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda request, timeout=None: _FakeResponse(FIXTURE.read_bytes()))
    cfg = cfg_with(local_model_path=str(target))  # real MODEL_SHA256 stays: mismatch
    with pytest.raises(lv.LocalVisionError, match="SHA-256"):
        lv.local_verdict(frame(235), cfg)
    assert not target.exists() and not target.with_name("detector.onnx.part").exists()


def test_failed_download_is_not_retried_every_check(monkeypatch, tmp_path):
    target = tmp_path / "detector.onnx"
    calls = []

    def failing_urlopen(request, timeout=None):
        calls.append(1)
        raise OSError("network is down")

    monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)
    cfg = cfg_with(local_model_path=str(target))
    for _ in range(2):
        with pytest.raises(lv.LocalVisionError, match="network is down"):
            lv.local_verdict(frame(235), cfg)
    assert len(calls) == 1


def test_preexisting_default_model_must_match_the_pinned_checksum(monkeypatch, tmp_path):
    home = tmp_path / "home"
    target = home / "models" / lv.MODEL_FILENAME
    target.parent.mkdir(parents=True)
    target.write_bytes(FIXTURE.read_bytes())  # a valid model, but not the pinned one
    cfg = {"vision": {"local_detector_enabled": True, "local_model_path": ""},
           "paths": {"hermes_home": home}}
    with pytest.raises(lv.LocalVisionError, match="does not match the pinned"):
        lv.local_verdict(frame(235), cfg)


# --------------------------------------------------------------- detector status


def test_status_off_by_default():
    state, detail = lv.detector_status(cfg_with(local_detector_enabled=False))
    assert state == "off" and "local_detector_enabled" in detail


def test_status_ready_with_model_present():
    state, detail = lv.detector_status(cfg_with())
    assert state == "ready" and "present" in detail


def test_status_ready_model_downloads_on_first_use(tmp_path):
    cfg = cfg_with(local_model_path=str(tmp_path / "not-yet.onnx"))
    state, detail = lv.detector_status(cfg)
    assert state == "ready" and "downloads on first use" in detail


# --------------------------------------------------------------- settings


def test_settings_defaults_and_env_form():
    data = settings.load(home=settings.HOME, local=False, environ={})
    assert data["vision"]["local_detector_enabled"] is False
    assert data["vision"]["local_model_path"] == ""
    env = {"PRINT_HANDY__VISION__LOCAL_DETECTOR_ENABLED": "true",
           "PRINT_HANDY__VISION__LOCAL_MODEL_PATH": "/models/mine.onnx"}
    data = settings.load(home=settings.HOME, local=False, environ=env)
    assert data["vision"]["local_detector_enabled"] is True
    assert data["vision"]["local_model_path"] == "/models/mine.onnx"


def test_settings_reject_wrong_types(tmp_path):
    local = tmp_path / "local.yaml"
    local.write_text("vision:\n  local_detector_enabled: sometimes\n")
    with pytest.raises(settings.SettingsError, match="local_detector_enabled"):
        settings.load(home=settings.HOME, local=local, environ={})
    local.write_text("vision:\n  local_model_path: 42\n")
    with pytest.raises(settings.SettingsError, match="local_model_path"):
        settings.load(home=settings.HOME, local=local, environ={})


# --------------------------------------------------------------- verdict routing


def _verdict(image, **overrides):
    call = dict(chat_url=lambda: "", model="m", api_key=lambda: "", context="")
    call.update(overrides)
    return vw.visual_verdict(image, "prompt", **call)


def _chat_response(verdict="ok", reason="chat endpoint"):
    body = {"choices": [{"message": {
        "content": json.dumps({"verdict": verdict, "reason": reason})}}]}
    return _FakeResponse(json.dumps(body).encode())


def _url_response(verdict="ok", reason="custom endpoint"):
    return _FakeResponse(json.dumps({"verdict": verdict, "reason": reason}).encode())


def test_print_vision_url_wins_and_local_is_not_consulted(monkeypatch, process_cfg):
    monkeypatch.setenv("PRINT_VISION_URL", "http://detector.invalid/judge")
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda request, timeout=None: _url_response())
    consulted = []
    monkeypatch.setattr(lv, "local_verdict",
                        lambda image: consulted.append(1) or ("spaghetti", "local"))
    verdict, detail = _verdict(frame(235))
    assert (verdict, detail) == ("ok", "custom endpoint")
    assert consulted == []


def test_chat_endpoint_wins_when_configured(monkeypatch, process_cfg):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda request, timeout=None: _chat_response())
    consulted = []
    monkeypatch.setattr(lv, "local_verdict",
                        lambda image: consulted.append(1) or ("spaghetti", "local"))
    verdict, detail = _verdict(
        frame(235), chat_url=lambda: "http://vision.invalid/v1/chat/completions",
        api_key=lambda: "key")
    assert (verdict, detail) == ("ok", "chat endpoint")
    assert consulted == []


def test_configured_chat_endpoint_failure_does_not_fall_through(monkeypatch, process_cfg):
    monkeypatch.setattr(vw._config, "service_url",
                        lambda key: "http://vision.invalid/v1" if key == "vision_chat_url" else "")

    def failing_urlopen(request, timeout=None):
        raise OSError("endpoint down")

    monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)
    consulted = []
    monkeypatch.setattr(lv, "local_verdict",
                        lambda image: consulted.append(1) or ("spaghetti", "local"))
    verdict, detail = _verdict(
        frame(235), chat_url=lambda: "http://vision.invalid/v1/chat/completions",
        api_key=lambda: "key")
    assert (verdict, detail) == ("uncertain", "the vision check could not be completed")
    assert consulted == []


def test_no_key_and_local_enabled_local_detector_answers(process_cfg):
    verdict, detail = _verdict(frame(235))
    assert verdict == "spaghetti" and "local failure detector" in detail


def test_half_configured_chat_route_local_detector_answers(monkeypatch, process_cfg):
    """CLIPROXY_API_KEY present but services.vision_chat_url unset: the
    injected chat_url raises (the listener's _config.require), which is
    'no endpoint route configured', so the local detector stands in."""
    monkeypatch.setattr(vw._config, "service_url",
                        lambda key: "" if key == "vision_chat_url" else "")

    def raising_chat_url():
        raise RuntimeError("services.vision_chat_url is not configured")

    verdict, detail = _verdict(frame(13), chat_url=raising_chat_url, api_key=lambda: "key")
    assert verdict == "ok" and "local failure detector" in detail


def test_no_key_and_local_disabled_is_the_existing_missing_key_result(monkeypatch):
    previous = copy.deepcopy(_config.cfg())
    data = copy.deepcopy(previous)
    data["vision"]["local_detector_enabled"] = False
    _config.set_override(data)
    try:
        verdict, detail = _verdict(frame(235))
    finally:
        _config.set_override(previous)
    assert (verdict, detail) == ("uncertain", "vision key is not configured")


def test_local_failure_inside_verdict_degrades_generically(monkeypatch, process_cfg):
    monkeypatch.setattr(lv, "_ort_error", RuntimeError("no runtime"))
    verdict, detail = _verdict(frame(235))
    assert (verdict, detail) == ("uncertain", "the vision check could not be completed")


def test_visual_extract_never_uses_the_local_detector(monkeypatch, process_cfg):
    consulted = []
    monkeypatch.setattr(lv, "local_verdict",
                        lambda image: consulted.append(1) or ("spaghetti", "local"))
    result = vw.visual_extract(frame(235), "read the label",
                               chat_url=lambda: "", model="m",
                               api_key=lambda: "", context="")
    assert result is None and consulted == []


# --------------------------------------------------------------- vision_ready


def test_vision_ready_with_local_detector(process_cfg):
    assert vw.vision_ready(lambda: "", None) is True


def test_vision_ready_local_unavailable_stays_off(monkeypatch, process_cfg):
    monkeypatch.setattr(lv, "_ort_error", RuntimeError("no runtime"))
    monkeypatch.setattr(vw, "_vision_missing_logged", False)
    lines = []
    assert vw.vision_ready(lambda: "", lines.append) is False
    assert len(lines) == 1 and "vision.local_detector_enabled" in lines[0]
