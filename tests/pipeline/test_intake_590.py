"""#590 at the intake surface: the live MakerWorld token failure and an
unknown failure, end to end through prepare_link's generic handler."""
import asyncio
import json
from types import SimpleNamespace as S

from print_handy.core import model_job, prepared_intake
from .test_color_intake import state
from .test_prepared_intake import Adapter, env  # noqa: F401  (env: shared intake fixture)

URL = "https://makerworld.com/en/models/3382409-miniature-baroque-frame"
TOKEN_ERROR = RuntimeError(
    "MakerWorld links need an account token in /data/.config/bambu/token; "
    "see docs/PROJECT-REFERENCE.md (MakerWorld account token)")


def _run(env, monkeypatch, error, mid):
    def fail(url):
        raise error
    monkeypatch.setattr(model_job, "maker_inventory", fail)
    event = S(source=S(profile="3dprinting", chat_id="c1", thread_id=None, user_id="u"),
              message_id=mid, text=URL)
    adapter = Adapter([])
    asyncio.run(prepared_intake.prepare_link(event, adapter, state(), env.root, timeout=1))
    receipt = json.loads(next(env.root.glob("*.json")).read_text())
    assert receipt["status"] == "FAILED"
    return [str(m) for m in adapter.sent]


def test_makerworld_token_failure_names_the_cause(env, monkeypatch):
    posts = _run(env, monkeypatch, TOKEN_ERROR, "mw590")
    hits = [m for m in posts if "MakerWorld" in m and "account token" in m]
    assert hits, posts
    post = hits[0]
    assert "PROJECT-REFERENCE" in post
    assert "Reference: PH_INTAKE_CONFIGURATION" in post
    assert "UNKNOWN" not in post
    assert "Send the link" not in post
    assert "/data/.config" not in post  # raw exception text stays out of chat


def test_unknown_failure_keeps_bundle_hint_without_resend_advice(env, monkeypatch):
    posts = _run(env, monkeypatch, RuntimeError("mystery"), "mw591")
    hits = [m for m in posts if "Preparing that model stopped" in m]
    assert hits, posts
    post = hits[0]
    assert "Reference: PH_INTAKE_UNKNOWN" in post
    assert "/print-handy bundle" in post
    assert "Send the link" not in post


def test_transient_failure_may_suggest_resending(env, monkeypatch):
    posts = _run(env, monkeypatch, ConnectionError("connection reset"), "mw592")
    hits = [m for m in posts if "Preparing that model stopped" in m]
    assert hits, posts
    post = hits[0]
    assert "Reference: PH_INTAKE_TRANSIENT" in post
    assert "Send the link or file again" in post
