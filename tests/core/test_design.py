"""Offline tests for the AI design engine (#388 Stage 1).

The model is always a scripted fake. Real-OpenSCAD renders run only when
openscad and xvfb-run are installed (the render_preview test pattern);
everything else — sandbox scan, extraction, transports, session store —
runs everywhere.
"""
import asyncio
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from print_buddy.core import design

GOOD = ("plate_z = 3;\n$fn = 48;\ndifference() {\n"
        "  translate([-20, -10, 0]) cube([40, 20, plate_z]);\n"
        "  for (x = [-15, 15]) translate([x, 0, -1]) cylinder(h = plate_z + 2, d = 4);\n}\n")
THICKER = GOOD.replace("plate_z = 3", "plate_z = 5")
SYNTAX_BAD = "cube([10, 10, 10);\n"
EMPTY = "difference() { cube([10, 10, 10]); cube([20, 20, 20]); }\n"
CFG = {"design": {"enabled": True, "chat_url": "", "model": "", "api_key_env": "",
                  "timeout_s": 180, "repair_attempts": 3},
       "printer": {"bed_mm": [220, 220]}}

needs_scad = pytest.mark.skipif(not (shutil.which("openscad") and shutil.which("xvfb-run")),
                                reason="openscad/xvfb-run not installed")


def scripted(replies):
    """A fake model transport: replies in order, recording every message list."""
    calls = []

    def complete(messages):
        calls.append(messages)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    complete.calls = calls
    return complete


def engine(tmp_path, complete, **kw):
    return design.DesignEngine(tmp_path / "cache", complete, cfg=CFG, **kw)


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------- source handling

def test_extract_scad_accepts_fences_and_bare_source():
    assert design.extract_scad(f"```scad\n{GOOD}```") == GOOD.strip()
    assert design.extract_scad(f"```\n{GOOD}```") == GOOD.strip()
    assert design.extract_scad(GOOD) == GOOD.strip()
    with pytest.raises(design.DesignError, match="did not return any OpenSCAD"):
        design.extract_scad("I cannot help with that.")
    with pytest.raises(design.DesignError):
        design.extract_scad("")


@pytest.mark.parametrize("source", [
    "import('/etc/passwd');\ncube([1, 1, 1]);",
    "IMPORT ('x.stl');",
    "translate([0, 0, 0]) import('a.stl');",
    "include <../outside/lib.scad>\ncube([1, 1, 1]);",
    "use <lib.scad>\ncube([1, 1, 1]);",
    "surface(file = 'height.png');",
    "Surface (file='x.png');",
    "import(str('a', '.stl'));",
])
def test_sandbox_scan_refuses_file_access_statements(source):
    with pytest.raises(design.DesignError, match="may not use"):
        design.scan_scad(source)


def test_sandbox_scan_allows_ordinary_design_words():
    design.scan_scad(GOOD)  # no exception
    design.scan_scad("// a plate, imported dimensions noted in comments\ncube([1, 1, 1]);\n")


def test_sandbox_scan_refuses_oversize_source():
    with pytest.raises(design.DesignError, match="limit"):
        design.scan_scad("cube([1,1,1]);\n" + "// pad\n" * (design.MAX_SCAD_BYTES // 6))


# --------------------------------------------------------------------- transports

def test_resolve_http_config_inherits_llm_then_prefers_design():
    cfg = {"design": {"chat_url": "", "model": "", "api_key_env": "", "timeout_s": 180},
           "llm": {"chat_url": "http://llm/v1", "model": "luna", "api_key_env": "K1"}}
    assert design.resolve_http_config(cfg) == {
        "chat_url": "http://llm/v1", "model": "luna", "api_key_env": "K1", "timeout_s": 180}
    cfg["design"].update(chat_url="http://design/v1", model="sol", api_key_env="K2",
                         timeout_s=90)
    resolved = design.resolve_http_config(cfg)
    assert resolved["chat_url"] == "http://design/v1" and resolved["model"] == "sol"
    assert resolved["api_key_env"] == "K2" and resolved["timeout_s"] == 90
    assert design.resolve_http_config({"design": {}, "llm": {}}) is None
    assert design.resolve_http_config({"design": {"chat_url": "http://x"}, "llm": {}}) is None


def test_http_complete_sends_design_budgets_and_reads_the_reply():
    cfg = {"design": {"chat_url": "", "model": "sol", "api_key_env": "", "timeout_s": 90},
           "llm": {"chat_url": "http://llm/v1/chat", "model": "luna", "api_key_env": "LLM_API_KEY"}}
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "```scad\ncube([1,1,1]);\n```"}}]}).encode()

    def opener(req, timeout=None):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(req.data)
        return Resp()

    out = design.http_complete(cfg, [{"role": "user", "content": "make a cube"}], opener=opener)
    assert "cube([1,1,1])" in out
    assert seen["url"] == "http://llm/v1/chat" and seen["timeout"] == 90.0
    assert seen["body"]["model"] == "sol"  # the design model, not the chat model
    assert seen["body"]["max_tokens"] == 4000


def test_http_complete_without_an_endpoint_is_a_plain_error():
    with pytest.raises(design.DesignError, match="no model endpoint"):
        design.http_complete({"design": {}, "llm": {}}, [])


def test_hermes_complete_uses_the_print_design_task():
    seen = {}

    class FakeLlm:
        async def acomplete(self, **kwargs):
            seen.update(kwargs)
            return type("R", (), {"text": "cube([1, 1, 1]);"})()

    out = run(design.hermes_complete(FakeLlm(), [{"role": "user", "content": "x"}],
                                     timeout_s=42))
    assert out == "cube([1, 1, 1]);"
    assert seen["task"] == "print_design" and seen["purpose"] == "print-design"
    assert seen["timeout"] == 42


def test_hermes_complete_trust_refusal_is_plain_words():
    class TrustError(Exception):
        pass

    class FakeLlm:
        async def acomplete(self, **kwargs):
            raise TrustError("PluginLlmTrustError: operator has not granted this")

    with pytest.raises(design.DesignError, match="trust gate"):
        run(design.hermes_complete(FakeLlm(), []))


# --------------------------------------------------------------------- sessions

def test_session_store_roundtrip_and_owner_lookup(tmp_path):
    eng = engine(tmp_path, scripted([GOOD]))
    session = eng.start_session("owner-1", "chan", "a plate")
    assert (eng.root / session["id"] / "session.json").is_file()
    assert design.find_session_for_owner(eng.root, "owner-1")["id"] == session["id"]
    assert design.find_session_for_owner(eng.root, "someone-else") is None
    eng.cancel(session)
    assert design.find_session_for_owner(eng.root, "owner-1") is None


def test_prune_drops_old_sessions(tmp_path):
    eng = engine(tmp_path, scripted([GOOD]))
    session = eng.start_session("o", "c", "old")
    folder = eng.root / session["id"]
    data = json.loads((folder / "session.json").read_text())
    data["updated_at"] = 1
    (folder / "session.json").write_text(json.dumps(data))
    assert design.prune_old_sessions(eng.root, now=10 ** 10) == 1
    assert not folder.exists()


# --------------------------------------------------------------------- the turn loop

@needs_scad
def test_turn_renders_validates_and_previews(tmp_path):
    eng = engine(tmp_path, scripted([f"```scad\n{GOOD}```"]))
    session = eng.start_session("o", "c", "a 40x20x3 plate with two 4 mm holes 30 mm apart")
    result = run(eng.run_turn(session, session["description"]))
    assert result["geometry"]["dimensions_mm"] == [40.0, 20.0, 3.0]
    assert result["geometry"]["watertight"] is True
    assert result["geometry"]["shell_count"] == 1
    assert result["stl_path"].is_file() and result["scad_path"].is_file()
    assert result["preview_path"] and Path(result["preview_path"]).is_file()
    assert "40 × 20 × 3" in design.summary_text(result)


@needs_scad
def test_iteration_edits_the_same_session(tmp_path):
    eng = engine(tmp_path, scripted([GOOD, THICKER]))
    session = eng.start_session("o", "c", "a plate")
    first = run(eng.run_turn(session, "a plate"))
    second = run(eng.run_turn(first["session"], "make it 5 mm thick"))
    assert second["geometry"]["dimensions_mm"] == [40.0, 20.0, 5.0]
    folder = eng.root / session["id"]
    assert (folder / "turn-1.scad").is_file() and (folder / "turn-2.scad").is_file()
    assert (folder / "turn-1.stl").is_file() and (folder / "turn-2.stl").is_file()


@needs_scad
def test_broken_scad_is_repaired_with_the_real_error(tmp_path):
    fake = scripted([SYNTAX_BAD, GOOD])
    eng = engine(tmp_path, fake)
    session = eng.start_session("o", "c", "a plate")
    result = run(eng.run_turn(session, "a plate"))
    assert result["geometry"]["dimensions_mm"] == [40.0, 20.0, 3.0]
    assert len(fake.calls) == 2
    repair_prompt = fake.calls[1][1]["content"]
    assert "Parser error" in repair_prompt or "ERROR" in repair_prompt


@needs_scad
def test_unrepairable_scad_fails_honestly_and_hands_nothing_on(tmp_path):
    fake = scripted([SYNTAX_BAD])
    eng = engine(tmp_path, fake, )
    eng.repair_attempts = 2
    session = eng.start_session("o", "c", "a plate")
    with pytest.raises(design.DesignError, match="could not render"):
        run(eng.run_turn(session, "a plate"))
    assert len(fake.calls) == 3  # initial + 2 repairs
    assert design.load_session(eng.root, session["id"])["stl"] is None


@needs_scad
def test_empty_geometry_is_rejected(tmp_path):
    eng = engine(tmp_path, scripted([EMPTY]))
    eng.repair_attempts = 0
    session = eng.start_session("o", "c", "nothing at all")
    with pytest.raises(design.DesignError, match="could not render|no solid volume"):
        run(eng.run_turn(session, "nothing at all"))


def test_sandbox_refusal_happens_before_any_render(tmp_path):
    renders = []

    def counting_runner(cmd, **kwargs):
        renders.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    eng = engine(tmp_path, scripted(["import('/etc/passwd');\ncube([1, 1, 1]);"]),
                 runner=counting_runner)
    session = eng.start_session("o", "c", "evil")
    with pytest.raises(design.DesignError, match="may not use"):
        run(eng.run_turn(session, "evil"))
    assert renders == []


def test_model_returning_no_code_is_a_plain_failure(tmp_path):
    eng = engine(tmp_path, scripted(["Sorry, I cannot design that."]))
    session = eng.start_session("o", "c", "a plate")
    with pytest.raises(design.DesignError, match="did not return any OpenSCAD"):
        run(eng.run_turn(session, "a plate"))


def test_render_argv_always_carries_hardwarnings(tmp_path):
    seen = {}

    def fake_runner(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_bytes(b"\0" * 200)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    ok, error = design.render_scad(tmp_path / "a.scad", tmp_path / "a.stl", runner=fake_runner)
    assert "--hardwarnings" in seen["cmd"]
    assert seen["kwargs"]["cwd"] == str(tmp_path)
    assert "OPENSCADPATH" not in seen["kwargs"]["env"]


def test_turn_cap_stops_an_endless_session(tmp_path):
    eng = engine(tmp_path, scripted([GOOD]))
    session = eng.start_session("o", "c", "a plate")
    session["turns"] = design.MAX_TURNS
    session["scad"] = "turn-1.scad"
    with pytest.raises(design.DesignError, match="turns"):
        run(eng.run_turn(session, "one more"))
