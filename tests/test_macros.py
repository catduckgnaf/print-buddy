"""Offline tests for live macro discovery and the /print-macros handler (issue #291, stage 1).

No printer or network: discovery runs against recorded Moonraker response
shapes through a fake transport, and the dispatch tests use a fake adapter
that records sends, in the style of the /print-lookup tests in
tests/test_knowledge.py. The fake transport records every call so the tests
can prove the only request ever made is one read-only GET.
"""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace as S
from unittest import mock

import pytest

from print_buddy import knowledge, macros, printers
from print_buddy.hermes import spool_sync

ROOT = Path(__file__).parents[1]
PLUGIN_PATH = ROOT / "plugins/print-feedback/__init__.py"
spec = importlib.util.spec_from_file_location("print_feedback_macros", PLUGIN_PATH)
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

# A recorded-shape Moonraker answer: one "gcode_macro <NAME>" object per macro
# in the printer's config, mixed in with the ordinary Klipper objects.
OBJECTS = {
    "result": {
        "objects": [
            "toolhead", "extruder", "heater_bed", "fan", "virtual_sdcard",
            "gcode_macro PRINT_START", "gcode_macro PRINT_END",
            "gcode_macro START_PRINT", "gcode_macro WIPE_NOZZLE_CUSTOM",
            "gcode_macro _PARK_HELPERS", "gcode_macro _PRINT_BUDDY_VARS",
            "bed_mesh", "gcode_move",
        ]
    }
}


class FakeTransport:
    """The spool_sync.moonraker call shape, recording every call."""

    def __init__(self, payload=None, error=None):
        self.payload = OBJECTS if payload is None else payload
        self.error = error
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.error is not None:
            raise self.error
        return self.payload


# --------------------------------------------------------------------- parsing

def test_parse_reads_the_result_objects_shape():
    assert macros.parse_macro_names(OBJECTS) == [
        "PRINT_START", "PRINT_END", "START_PRINT", "WIPE_NOZZLE_CUSTOM",
        "_PARK_HELPERS", "_PRINT_BUDDY_VARS"]


def test_parse_accepts_result_list_and_bare_list_shapes():
    shapes = ({"result": ["gcode_macro A_MACRO", "toolhead"]},
              ["gcode_macro A_MACRO", "toolhead"],
              {"result": {"objects": ["gcode_macro A_MACRO", "toolhead"]}})
    for payload in shapes:
        assert macros.parse_macro_names(payload) == ["A_MACRO"]


def test_parse_dedupes_and_skips_a_nameless_macro_object():
    payload = {"result": {"objects": ["gcode_macro", "gcode_macro DUP", "gcode_macro DUP"]}}
    assert macros.parse_macro_names(payload) == ["DUP"]


@pytest.mark.parametrize("payload", [
    None, "nope", 42, {}, {"result": None}, {"result": "PRINT_START"},
    {"result": {"objects": "PRINT_START"}}, {"result": {"status": {}}},
    {"result": {"objects": ["gcode_macro OK", 7]}},
])
def test_parse_rejects_malformed_responses(payload):
    with pytest.raises(macros.MacroError):
        macros.parse_macro_names(payload)


# --------------------------------------------------------------- classification

@pytest.fixture(scope="module")
def registry():
    return knowledge.load_registry()


def test_classify_splits_known_printer_defined_and_internal(registry):
    listing = macros.classify(
        ["PRINT_START", "START_PRINT", "WIPE_NOZZLE_CUSTOM", "_PARK_HELPERS"], registry=registry)
    known = {name: entry for name, entry in listing.known}
    assert set(known) == {"PRINT_START", "START_PRINT"}
    assert known["PRINT_START"].id == "klipper.print-start"
    assert known["START_PRINT"].id == "zmod.start-print"
    assert listing.printer_defined == ("WIPE_NOZZLE_CUSTOM",)
    assert listing.internal == ("_PARK_HELPERS",)


def test_classify_matches_case_insensitively(registry):
    listing = macros.classify(["print_start"], registry=registry)
    assert [name for name, _ in listing.known] == ["print_start"]


def test_classify_never_calls_commands_or_errors_known_macros(registry):
    # BED_MESH_CALIBRATE and SAVE_CONFIG are registry *commands*, not macros:
    # a printer defining macros with those names is printer-defined, not known.
    listing = macros.classify(["BED_MESH_CALIBRATE", "SAVE_CONFIG"], registry=registry)
    assert listing.known == ()
    assert listing.printer_defined == ("BED_MESH_CALIBRATE", "SAVE_CONFIG")


# ------------------------------------------------------------------- discovery

def test_discover_makes_exactly_one_read_only_get():
    transport = FakeTransport()
    listing = macros.discover(transport)
    assert transport.calls == [("GET", "/printer/objects/list", None)]
    assert {name for name, _ in listing.known} == {"PRINT_START", "PRINT_END", "START_PRINT"}
    assert listing.printer_defined == ("WIPE_NOZZLE_CUSTOM",)
    assert listing.internal == ("_PARK_HELPERS", "_PRINT_BUDDY_VARS")


def test_discover_wraps_transport_failures():
    with pytest.raises(macros.MacroError):
        macros.discover(FakeTransport(error=OSError("unreachable")))


def test_discover_rejects_a_malformed_response():
    with pytest.raises(macros.MacroError):
        macros.discover(FakeTransport(payload={"result": {"status": {}}}))


# ------------------------------------------------------------------ formatting

def test_listing_text_shows_registry_safety_and_no_invented_descriptions(registry):
    listing = macros.classify(["PRINT_START", "WIPE_NOZZLE_CUSTOM", "_PARK_HELPERS"], registry=registry)
    text = macros.listing_text(listing)
    entry = next(e for e in registry.firmware_entries if e.id == "klipper.print-start")
    assert "**PRINT_START**" in text and entry.description in text
    assert f"Safety: {entry.safety}" in text
    assert "WIPE_NOZZLE_CUSTOM" in text
    assert "no description for these" in text
    assert "_PARK_HELPERS" in text and "not operator macros" in text
    assert text.endswith(macros.READ_ONLY_NOTE)


def test_listing_text_for_a_printer_with_no_macros():
    text = macros.listing_text(macros.MacroListing())
    assert "no macros" in text and text.endswith(macros.READ_ONLY_NOTE)


def test_not_moonraker_text_is_plain_and_names_the_connection():
    text = macros.not_moonraker_text("bambulab_lan")
    assert "no Moonraker macro namespace" in text and "bambulab_lan" in text
    assert text.endswith("Nothing was sent to the printer.")


# --------------------------------------------------------------------- handler

class FakeAdapter:
    """Records everything the dispatch tries to show the user; has no printer API at all."""

    def __init__(self):
        self.sent = []

    async def send(self, chat_id=None, content=None, metadata=None):
        self.sent.append(content)


def _event(text):
    source = S(platform=S(value="discord"), profile="3dprinting", is_bot=False,
               profile_route_rejected=False, user_id="u", chat_id="c", thread_id=None)
    return S(source=source, text=text, internal=False)


def _gateway(adapter):
    return S(_is_user_authorized_for_source=lambda s: True, _delivery_adapter_for=lambda s: adapter)


def _configured(connection):
    return mock.patch.object(printers, "current", return_value=S(connection=connection))


def test_macros_dispatch_lists_the_discovered_macros():
    adapter = FakeAdapter()
    transport = FakeTransport()
    with _configured("moonraker"), mock.patch.object(spool_sync, "moonraker", transport):
        out = asyncio.run(plugin.macros_dispatch(_event("/print-macros"), _gateway(adapter)))
    assert out == {"action": "skip", "reason": "print macros handled"}
    assert transport.calls == [("GET", "/printer/objects/list", None)]
    message = adapter.sent[-1]
    assert "**PRINT_START**" in message and "WIPE_NOZZLE_CUSTOM" in message
    assert "_PARK_HELPERS" in message and message.endswith(macros.READ_ONLY_NOTE)


def test_macros_dispatch_explains_non_moonraker_printers_without_calling_out():
    adapter = FakeAdapter()
    transport = FakeTransport()
    with _configured("bambulab_lan"), mock.patch.object(spool_sync, "moonraker", transport):
        out = asyncio.run(plugin.macros_dispatch(_event("/print-macros"), _gateway(adapter)))
    assert out == {"action": "skip", "reason": "print macros not applicable to this printer"}
    assert transport.calls == []
    assert "no Moonraker macro namespace" in adapter.sent[-1]


@pytest.mark.parametrize("connection", ["prusalink", "elegoo_sdcp", "flashforge_stock", "octoprint"])
def test_macros_dispatch_gates_every_non_moonraker_connection(connection):
    adapter = FakeAdapter()
    transport = FakeTransport()
    with _configured(connection), mock.patch.object(spool_sync, "moonraker", transport):
        out = asyncio.run(plugin.macros_dispatch(_event("/print-macros"), _gateway(adapter)))
    assert out["reason"] == "print macros not applicable to this printer"
    assert transport.calls == []


def test_macros_dispatch_reports_an_unreachable_moonraker_and_sends_nothing():
    adapter = FakeAdapter()
    transport = FakeTransport(error=OSError("unreachable"))
    with _configured("moonraker"), mock.patch.object(spool_sync, "moonraker", transport):
        out = asyncio.run(plugin.macros_dispatch(_event("/print-macros"), _gateway(adapter)))
    assert out == {"action": "skip", "reason": "print macros handled"}
    assert adapter.sent[-1] == macros.COULD_NOT_READ_TEXT
    # The one attempted call was the read-only GET; no macro was ever posted.
    assert transport.calls == [("GET", "/printer/objects/list", None)]


def test_macros_dispatch_reports_a_malformed_response_the_same_way():
    adapter = FakeAdapter()
    transport = FakeTransport(payload={"error": {"message": "nope"}})
    with _configured("moonraker"), mock.patch.object(spool_sync, "moonraker", transport):
        asyncio.run(plugin.macros_dispatch(_event("/print-macros"), _gateway(adapter)))
    assert adapter.sent[-1] == macros.COULD_NOT_READ_TEXT


def test_macros_dispatch_ignores_other_text():
    assert asyncio.run(plugin.macros_dispatch(_event("/print-macrosx"), _gateway(FakeAdapter()))) is None
    assert asyncio.run(plugin.macros_dispatch(_event("print-macros"), _gateway(FakeAdapter()))) is None
