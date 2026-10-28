"""Offline tests for the root registries, lookup engine and troubleshooting flows (issue #169).

No printer, network or Discord is involved: the lookup and flow code is read-only
by construction, and the dispatch tests use a fake adapter that records sends.
"""
import ast
import asyncio
import importlib.util
import shutil
from pathlib import Path
from types import SimpleNamespace as S
from unittest import mock

import pytest

from print_handy import knowledge, printers
from print_handy.bot import commands as bot_commands, llm
from print_handy.core import prompts
from print_handy.knowledge import FlowError, RegistryError

ROOT = Path(__file__).parents[1]
PLUGIN_PATH = ROOT / "plugins/print-feedback/__init__.py"
spec = importlib.util.spec_from_file_location("print_feedback_knowledge", PLUGIN_PATH)
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


@pytest.fixture(scope="module")
def registry():
    return knowledge.load_registry()


# --------------------------------------------------------------------- registries

def test_registries_load_and_validate(registry):
    assert len(registry.flows) == 5
    assert len(registry.symptoms) >= 5
    assert {e.firmware for e in registry.firmware_entries} == {"zmod", "klipper", "marlin"}


def test_printer_registry_matches_code_profiles(registry):
    """The root printer registry must not drift from print_handy/printers."""
    assert {p.key for p in registry.printers} == set(printers.MODELS)
    for entry in registry.printers:
        model = printers.MODELS[entry.key]
        defaults = model.defaults()["printer"]
        assert entry.label == model.label
        assert entry.vendor == model.vendor.key
        assert entry.firmware == defaults["firmware"]
        assert entry.connection == model.vendor.connection
        assert entry.bed_mm == tuple(float(v) for v in defaults["bed_mm"])
        assert entry.max_height_mm == float(defaults["max_print_height_mm"])
        if entry.tools:
            # Toolhead machines record tools, not IFS slots: the model's tool_count
            # is the authority and its ifs_slots stays 1 (see #301 stage 2).
            assert entry.tools == int(defaults["tool_count"])
            assert entry.filament_slots == 0
        else:
            assert entry.filament_slots == int(defaults["ifs_slots"])
        assert (ROOT / entry.profile).is_file()


def test_broken_registry_is_rejected(tmp_path):
    for name in ("knowledge", "firmware", "printers"):
        shutil.copytree(ROOT / name, tmp_path / name)
    flows = tmp_path / "knowledge" / "troubleshooting.toml"
    flows.write_text(flows.read_text().replace('next = "look"', 'next = "no-such-node"', 1))
    with pytest.raises(RegistryError, match="unknown node"):
        knowledge.load_registry(tmp_path)


def test_missing_registry_is_rejected(tmp_path):
    with pytest.raises(RegistryError, match="missing"):
        knowledge.load_registry(tmp_path)


# ----------------------------------------------------------------------- lookups

def top(registry, query, **kwargs):
    results = registry.lookup(query, **kwargs)
    assert results, query
    return results[0]


def test_lookup_zmod_ifs_load(registry):
    hit = top(registry, "zmod ifs load")
    assert hit.kind == "firmware" and hit.item.id == "zmod.ifs-load"


def test_lookup_resolves_across_families(registry):
    assert top(registry, "probe calibrate", firmware="klipper").item.id == "klipper.probe-calibrate"
    assert top(registry, "M600").item.id == "marlin.m600"
    assert top(registry, "change zcolor").item.id == "zmod.change-zcolor"
    assert top(registry, "heating failed").item.id == "marlin.heating-failed"


STAGE3_IDS = {
    "zmod.coldpull", "zmod.load-filament", "zmod.unload-filament", "zmod.load-material",
    "zmod.clear-nozzle", "zmod.set-extruder-slot", "zmod.set-active-spool",
    "zmod.clear-active-spool", "zmod.save-zmod-data", "zmod.get-zmod-data",
    "zmod.nozzle-control", "zmod.pid-tune-extruder", "zmod.pid-tune-bed", "zmod.zshaper",
    "zmod.display-off", "zmod.display-on", "zmod.print-handy",
    "klipper.pause", "klipper.resume", "klipper.cancel-print",
    "klipper.set-pause-next-layer", "klipper.set-pause-at-layer", "klipper.set-print-stats-info",
}


def test_stage3_registry_growth_is_complete_and_provenanced(registry):
    """Stage 3 of #291: every added entry loads, is a macro, and names its source."""
    assert len(registry.firmware_entries) == 45
    by_id = {e.id: e for e in registry.firmware_entries}
    assert STAGE3_IDS <= set(by_id)
    for entry_id in STAGE3_IDS:
        entry = by_id[entry_id]
        assert entry.kind == "macro", entry_id
        assert entry.notes, entry_id
        assert ("@" in entry.notes) or ("print-handy.cfg" in entry.notes), entry_id


def test_lookup_stage3_entries_by_name_and_alias(registry):
    assert top(registry, "COLDPULL").item.id == "zmod.coldpull"
    assert top(registry, "cold pull").item.id == "zmod.coldpull"
    assert top(registry, "set extruder slot").item.id == "zmod.set-extruder-slot"
    assert top(registry, "save zmod data").item.id == "zmod.save-zmod-data"
    assert top(registry, "PRINT_HANDY").item.id == "zmod.print-handy"
    assert top(registry, "pause next layer").item.id == "klipper.set-pause-next-layer"
    assert top(registry, "pause at layer").item.id == "klipper.set-pause-at-layer"
    # The Stage 3 growth must not re-top the pinned cross-family M600 lookup:
    # no same-name macro entry was added for it on purpose.
    assert top(registry, "M600").item.id == "marlin.m600"


def test_lookup_printer_filter_excludes_other_families(registry):
    hits = registry.lookup("start print", printer="flashforge.ad5x")
    ids = [h.item.id for h in hits if h.kind == "firmware"]
    assert "zmod.start-print" in ids and "klipper.print-start" not in ids


def test_lookup_bad_firmware_filter_rejected(registry):
    with pytest.raises(RegistryError):
        registry.lookup("mesh", firmware="prusa")


def test_lookup_symptom_finds_its_flow(registry):
    text = knowledge.lookup_text("first layer not sticking", registry=registry)
    assert "/print-troubleshoot first-layer" in text
    assert text.endswith(knowledge.ADVISORY_NOTE)


def test_lookup_text_for_command_and_unknown_query(registry):
    text = knowledge.lookup_text("M851", registry=registry)
    assert "M851" in text and "Safety:" in text
    unknown = knowledge.lookup_text("warp drive calibration", registry=registry)
    assert "Nothing in the registries matches" in unknown
    assert knowledge.lookup_text("", registry=registry).endswith(knowledge.ADVISORY_NOTE)


# ------------------------------------------------------------------------- flows

def test_flow_first_step_carries_safety_exactly_once():
    session = knowledge.start_flow("clog")
    first = session.step()
    assert first.safety and "burn" in " ".join(first.safety)
    session.answer(first.choices[0])
    assert session.step().safety == ()


def test_flow_branching_first_layer():
    far = knowledge.start_flow("first-layer")
    far.answer("Yes, it is clean")
    step = far.answer("Lines are round with gaps between them")
    assert step.kind == "advice" and "too far" in step.text

    close = knowledge.start_flow("first-layer")
    close.answer("No, or not sure")  # advice node: wash the bed, then continue
    assert close.step().node_id == "wash-bed"
    close.advance()
    step = close.answer("Lines are smeared flat, transparent, or ridged")
    assert "too close" in step.text


def test_flow_unknown_answer_rejected():
    session = knowledge.start_flow("ringing")
    with pytest.raises(FlowError):
        session.answer("banana")


def test_every_flow_completes_by_always_taking_the_first_option():
    for flow_id in ("first-layer", "clog", "heat-creep", "bed-level", "ringing"):
        session = knowledge.start_flow(flow_id)
        for _ in range(40):
            step = session.step()
            if step.done:
                break
            if step.kind == "question":
                session.answer(step.choices[0])
            else:
                session.advance()
        assert session.step().done, flow_id


def test_unknown_flow_rejected():
    with pytest.raises(FlowError, match="unknown troubleshooting flow"):
        knowledge.start_flow("warp-drive")


# --------------------------------------------------------------- no-command proof

def test_knowledge_package_has_no_printer_or_network_imports():
    forbidden = ("print_handy.printers", "print_handy.hermes", "print_handy.core",
                 "requests", "urllib", "socket", "subprocess", "discord")
    package = ROOT / "print_handy" / "knowledge"
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not any(name == f or name.startswith(f + ".") for f in forbidden), (path, name)


# -------------------------------------------------------------------- bot wiring

def test_bot_commands_registered():
    assert bot_commands.by_name("print-lookup") is not None
    assert bot_commands.by_name("print-troubleshoot") is not None
    assert bot_commands.by_name("print-macros") is not None
    assert bot_commands.as_text("print-lookup", {"query": "M600"}) == "/print-lookup M600"
    assert bot_commands.as_text("print-troubleshoot", {"flow": "clog"}) == "/print-troubleshoot clog"
    assert bot_commands.as_text("print-macros", {}) == "/print-macros"
    help_text = bot_commands.help_text()
    assert "/print-lookup" in help_text and "/print-troubleshoot" in help_text
    assert "/print-macros" in help_text


def test_llm_may_only_name_the_read_only_commands():
    assert llm.allowed_command("/print-lookup m600") == "/print-lookup m600"
    assert llm.allowed_command("/print-troubleshoot clog") == "/print-troubleshoot clog"
    assert llm.allowed_command("/print-troubleshoot delete everything") is None
    assert llm.allowed_command("/print-macros") == "/print-macros"
    assert llm.allowed_command("/print-macros run PRINT_START") is None


class FakeAdapter:
    """Records everything the dispatch tries to show the user; has no printer API at all."""

    def __init__(self):
        self.sent = []
        self.clarified = []

    async def send(self, chat_id=None, content=None, metadata=None):
        self.sent.append(content)

    async def send_clarify(self, **kwargs):
        self.clarified.append(kwargs["question"])
        return S(success=True)


def _event(text):
    source = S(platform=S(value="discord"), profile="3dprinting", is_bot=False,
               profile_route_rejected=False, user_id="u", chat_id="c", thread_id=None)
    return S(source=source, text=text, internal=False)


def _gateway(adapter):
    return S(_is_user_authorized_for_source=lambda s: True, _delivery_adapter_for=lambda s: adapter,
             _session_key_for_source=lambda s: "session-key")


def test_lookup_dispatch_answers_without_a_printer():
    adapter = FakeAdapter()
    out = asyncio.run(plugin.lookup_dispatch(_event("/print-lookup zmod ifs load"), _gateway(adapter)))
    assert out == {"action": "skip", "reason": "print lookup handled"}
    assert "_INSERT_PRUTOK_IFS" in adapter.sent[-1]
    assert adapter.sent[-1].endswith(knowledge.ADVISORY_NOTE)
    assert adapter.clarified == []


def test_lookup_dispatch_ignores_other_text():
    assert asyncio.run(plugin.lookup_dispatch(_event("/print-lookupx"), _gateway(FakeAdapter()))) is None
    assert asyncio.run(plugin.lookup_dispatch(_event("print-lookup m600"), _gateway(FakeAdapter()))) is None


class _ScriptedPrompts:
    CANCELLED = prompts.CANCELLED

    def __init__(self, answers):
        self.answers = list(answers)

    def register(self, *args):
        pass

    def resolve_gateway_clarify(self, *args):
        return True

    def wait_for_response(self, clarify_id, timeout=None):
        return self.answers.pop(0) if self.answers else None


def test_troubleshoot_dispatch_walks_the_clog_flow_and_sends_nothing():
    adapter = FakeAdapter()
    answers = ["Nothing comes out, extruder clicks or grinds", "Path is fine", "Yes, clean stream"]
    with mock.patch.object(prompts, "gateway", return_value=_ScriptedPrompts(answers)):
        out = asyncio.run(plugin.troubleshoot_dispatch(_event("/print-troubleshoot clog"), _gateway(adapter)))
    assert out == {"action": "skip", "reason": "troubleshoot handled"}
    joined = "\n".join(adapter.sent)
    assert "safety first" in joined and "burn" in joined
    assert "/print-coldpull" in joined  # the action is a pointer to the guarded command, not an action here
    assert "walkthrough complete" in adapter.sent[-1]
    assert adapter.sent[-1].endswith(knowledge.ADVISORY_NOTE)
    assert len(adapter.clarified) == 3  # three diagnostic questions, no other prompts


def test_troubleshoot_dispatch_can_be_stopped_at_the_first_question():
    adapter = FakeAdapter()
    with mock.patch.object(prompts, "gateway", return_value=_ScriptedPrompts([plugin.TROUBLESHOOT_STOP_LABEL])):
        out = asyncio.run(plugin.troubleshoot_dispatch(_event("/print-troubleshoot heat-creep"), _gateway(adapter)))
    assert out["reason"] == "troubleshoot handled"
    assert "Troubleshooting stopped" in adapter.sent[-1]


def test_troubleshoot_dispatch_lists_flows_without_an_argument():
    adapter = FakeAdapter()
    out = asyncio.run(plugin.troubleshoot_dispatch(_event("/print-troubleshoot"), _gateway(adapter)))
    assert out["reason"] == "troubleshoot usage shown"
    for flow_id in ("first-layer", "clog", "heat-creep", "bed-level", "ringing"):
        assert f"/print-troubleshoot {flow_id}" in adapter.sent[-1]
    assert adapter.clarified == []
