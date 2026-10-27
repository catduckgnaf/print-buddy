"""Offline tests for the /print-design dispatch handler (#388 Stage 1).

No Discord, no network, no real model: the plugin runs against a fake
adapter and gateway (the /print-live test style), the design model is a
scripted fake plugged into the plugin's transport seam, and the clarify
wait is patched to press the button each test chooses. Real-OpenSCAD
turns are skipped where openscad/xvfb-run are absent.
"""
import asyncio
import importlib.util
import shutil
from pathlib import Path
from types import SimpleNamespace as S
from unittest import mock

import pytest

from print_buddy.core import design, prepared_intake, printer_state
from print_buddy.core import prompts as core_prompts
from print_buddy.hermes import _config

ROOT = Path(__file__).parents[1]
PLUGIN_PATH = ROOT / "plugins/print-feedback/__init__.py"
spec = importlib.util.spec_from_file_location("print_feedback_design", PLUGIN_PATH)
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

GOOD = ("plate_z = 3;\n$fn = 48;\ndifference() {\n"
        "  translate([-20, -10, 0]) cube([40, 20, plate_z]);\n"
        "  for (x = [-15, 15]) translate([x, 0, -1]) cylinder(h = plate_z + 2, d = 4);\n}\n")
THICKER = GOOD.replace("plate_z = 3", "plate_z = 5")

needs_scad = pytest.mark.skipif(not (shutil.which("openscad") and shutil.which("xvfb-run")),
                                reason="openscad/xvfb-run not installed")


class FakeAdapter:
    def __init__(self):
        self.sent = []
        self.clarified = []

    async def send(self, chat_id=None, content=None, metadata=None):
        self.sent.append(content)

    async def send_clarify(self, chat_id=None, question=None, choices=None,
                           clarify_id=None, session_key=None, metadata=None):
        self.clarified.append((question, list(choices or [])))
        return S(success=True)


def _event(text, platform="discord", user_id="42"):
    source = S(platform=S(value=platform), profile="3dprinting", is_bot=False,
               profile_route_rejected=False, user_id=user_id, chat_id="c", thread_id=None)
    return S(source=source, text=text, internal=False, message_id="m1", metadata={})


def _gateway(adapter, authorized=True):
    return S(_is_user_authorized_for_source=lambda s: authorized,
             _delivery_adapter_for=lambda s: adapter,
             _session_key_for_source=lambda s: "session-key")


def scripted(replies):
    calls = []

    def complete(messages):
        calls.append(messages)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    complete.calls = calls
    return complete


@pytest.fixture
def design_env(tmp_path):
    cfg = {"bot": {"mode": "standalone"},
           "design": {"enabled": True, "chat_url": "", "model": "", "api_key_env": "",
                      "timeout_s": 180, "repair_attempts": 3},
           "llm": {"chat_url": "", "model": "", "api_key_env": "LLM_API_KEY", "timeout_s": 20},
           "paths": {"cache": tmp_path / "cache", "hermes_home": tmp_path},
           "printer": {"bed_mm": [220, 220]},
           "discord": {"question_timeout_s": 5}}
    _config.set_override(cfg)
    plugin._HERMES_LLM = None
    yield cfg
    _config.set_override(None)
    plugin._HERMES_LLM = None


def _dispatch(text, adapter, fake, choice, platform="discord", authorized=True):
    with mock.patch.object(plugin, "_design_transport", return_value=(fake, "http")), \
            mock.patch.object(core_prompts, "wait_for_response", return_value=choice):
        return asyncio.run(plugin.design_dispatch(
            _event(text, platform=platform), _gateway(adapter, authorized)))


def test_disabled_design_answers_not_set_up(design_env):
    design_env["design"]["enabled"] = False
    adapter = FakeAdapter()
    out = _dispatch("/print-design a plate", adapter, scripted([GOOD]), design.CANCEL_LABEL)
    assert out == {"action": "skip", "reason": "design not enabled"}
    assert "not set up" in adapter.sent[-1] and "DESIGN__ENABLED" in adapter.sent[-1]


def test_enabled_but_no_model_answers_not_configured(design_env):
    adapter = FakeAdapter()
    with mock.patch.object(plugin, "_design_transport", return_value=(None, "")):
        out = asyncio.run(plugin.design_dispatch(_event("/print-design a plate"),
                                                 _gateway(adapter)))
    assert out["reason"] == "design model not configured"
    assert "no design model is configured" in adapter.sent[-1]


def test_bare_command_shows_usage(design_env):
    adapter = FakeAdapter()
    out = _dispatch("/print-design", adapter, scripted([GOOD]), design.CANCEL_LABEL)
    assert out["reason"] == "design usage shown"
    assert "Usage: /print-design" in adapter.sent[-1]


def test_unauthorized_and_other_platforms_fall_through(design_env):
    adapter = FakeAdapter()
    assert _dispatch("/print-design a plate", adapter, scripted([GOOD]),
                     design.CANCEL_LABEL, authorized=False) is None
    assert _dispatch("/print-design a plate", adapter, scripted([GOOD]),
                     design.CANCEL_LABEL, platform="telegram") is None
    assert _dispatch("just chatting", adapter, scripted([GOOD]),
                     design.CANCEL_LABEL) is None
    assert adapter.sent == []


@needs_scad
def test_turn_posts_preview_choices_and_change_it_revises(design_env):
    adapter = FakeAdapter()
    fake = scripted([GOOD, THICKER])
    out = _dispatch("/print-design a 40x20x3 plate with two 4 mm holes", adapter, fake,
                    design.CHANGE_LABEL)
    assert out["reason"] == "design awaiting revision"
    post = next(content for content in adapter.sent if "Design turn 1" in content)
    assert "MEDIA:" in post and "40 × 20 × 3" in post and "watertight" in post
    assert adapter.clarified[-1][1] == [design.SLICE_LABEL, design.CHANGE_LABEL,
                                        design.CANCEL_LABEL]
    root = design.sessions_root(design_env["paths"]["cache"])
    session = design.find_session_for_owner(root, "c::42")
    assert session and session["status"] == "awaiting_revision"
    # The next plain message is the revision; Cancel then clears the session.
    out = _dispatch("make it 5 mm thick", adapter, fake, design.CANCEL_LABEL)
    assert out["reason"] == "design cancelled"
    post = next(content for content in adapter.sent if "Design turn 2" in content)
    assert "40 × 20 × 5" in post
    assert design.find_session_for_owner(root, "c::42") is None
    # The revision turn showed the model the previous source.
    assert "plate_z = 3" in fake.calls[1][1]["content"]


@needs_scad
def test_slice_it_hands_the_stl_to_prepared_intake_once(design_env):
    adapter = FakeAdapter()
    handed = {}

    async def fake_prepare(event, adapter_, state, root, **kw):
        handed["event"] = event
        handed["root"] = root
        return {"action": "skip", "reason": "intake handled"}

    with mock.patch.object(prepared_intake, "prepare_link", side_effect=fake_prepare) as prepare, \
            mock.patch.object(printer_state, "load", return_value=S()):
        out = _dispatch("/print-design a plate", adapter, scripted([GOOD]),
                        design.SLICE_LABEL)
    assert prepare.call_count == 1  # exactly one handoff; the design flow never slices itself
    assert out == {"action": "skip", "reason": "intake handled"}
    event = handed["event"]
    root = design.sessions_root(design_env["paths"]["cache"])
    session_dirs = [p for p in root.iterdir() if p.is_dir()]
    assert event.media_urls == [str(session_dirs[0] / "turn-1.stl")]
    assert event.text == "" and event.message_id.startswith("design-")
    session = design.load_session(root, session_dirs[0].name)
    assert session["status"] == "handed_off"


@needs_scad
def test_failed_turn_reports_the_error_and_offers_no_choices(design_env):
    adapter = FakeAdapter()
    out = _dispatch("/print-design a plate", adapter,
                    scripted(["import('/etc/passwd');\ncube([1, 1, 1]);"]),
                    design.CANCEL_LABEL)
    assert out["reason"] == "design turn failed"
    assert "may not use" in adapter.sent[-1]
    assert adapter.clarified == []
