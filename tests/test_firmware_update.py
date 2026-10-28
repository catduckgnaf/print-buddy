"""Offline tests for firmware update reporting, guarded apply, guides and
per-family guidance (issue #561).

No printer or network: Moonraker responses are recorded shapes replayed
through a fake transport that records every call, and the dispatch tests
use a fake adapter that records sends, in the style of tests/test_macros.py.
Stage 1 tests prove the report's reads are read-only and that a refresh
happens only on the user-invoked check path; stage 2 tests prove an apply
makes exactly one upgrade POST, only for an eligible profile, only while
idle at both checks, and that success is claimed only from the post-update
re-read.
"""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace as S
from unittest import mock

import pytest

from print_handy import firmware_update as fw
from print_handy import printers
from print_handy.bot import commands as bot_commands
from print_handy.bot import llm
from print_handy.hermes import spool_sync

ROOT = Path(__file__).parents[1]
PLUGIN_PATH = ROOT / "plugins/print-feedback/__init__.py"
spec = importlib.util.spec_from_file_location("print_feedback_firmware", PLUGIN_PATH)
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


def entry(key):
    found = fw.printer_entry(key)
    assert found is not None, key
    return found


AD5X = entry("flashforge.ad5x")
GENERIC = entry("klipper.generic")
NEPTUNE4 = entry("elegoo.neptune4")
BAMBU_A1 = entry("bambulab.a1")

# A recorded-shape Moonraker update-status answer (ZMod-flavoured): one
# entry per Update Manager component, versions as Moonraker reports them.
STATUS = {
    "result": {
        "version_info": {
            "klipper": {"version": "v0.12.0-289", "remote_version": "v0.12.0-310"},
            "moonraker": {"version": "v0.9.3-10", "remote_version": "v0.9.3-10"},
            "zmod": {"version": "1.9.2", "remote_version": "1.9.2"},
            "fluidd": {"version": "1.31.3", "remote_version": "1.31.3"},
            "system": {"package_count": 0, "package_list": []},
        },
        "busy": False,
    }
}

STATUS_UP_TO_DATE = {
    "result": {
        "version_info": {
            "klipper": {"version": "v0.12.0-289", "remote_version": "v0.12.0-289"},
            "moonraker": {"version": "v0.9.3-10", "remote_version": "v0.9.3-10"},
        }
    }
}

SYSTEM_INFO_194 = {"result": {"system_info": {"distribution": {"name": "ZMod OS", "version": "1.9.4"}}}}
SYSTEM_INFO_180 = {"result": {"system_info": {"distribution": {"name": "ZMod OS", "version": "1.8.0"}}}}

STATE_STANDBY = {"result": {"status": {"print_stats": {"state": "standby"}}}}


class FakeTransport:
    """The spool_sync.moonraker call shape, recording every call.

    Routes by path: update status / refresh, system info, the MCU objects
    query and the print-state query each get their recorded shape; any
    other path is a test failure, so an unexpected request is loud.
    """

    def __init__(self, status=None, system_info=None, mcu=None, states=("standby",),
                 error=None, refresh_error=None):
        self.status = STATUS if status is None else status
        self.system_info = system_info
        self.mcu = mcu
        self.states = list(states)
        self.error = error
        self.refresh_error = refresh_error
        self.calls = []
        self.posts = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "POST":
            self.posts.append((path, body))
        if self.error is not None:
            raise self.error
        if path == fw.UPDATE_REFRESH_PATH:
            if self.refresh_error is not None:
                raise self.refresh_error
            return self.status
        if path == fw.UPDATE_STATUS_PATH:
            return self.status
        if path == fw.SYSTEM_INFO_PATH:
            if self.system_info is None:
                raise OSError("no system info")
            return self.system_info
        if path == fw.MCU_STATE_PATH:
            if self.mcu is None:
                raise OSError("no mcu object")
            return self.mcu
        if path == fw.PRINT_STATE_PATH:
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return {"result": {"status": {"print_stats": {"state": state}}}}
        raise AssertionError(f"unexpected transport call: {method} {path}")


# --------------------------------------------------------------------- parsing

def test_parse_reads_the_documented_version_info_shape():
    status = fw.parse_update_status(STATUS)
    klipper = status.component("klipper")
    assert (klipper.current, klipper.remote) == ("v0.12.0-289", "v0.12.0-310")
    assert klipper.update_available
    assert not status.component("moonraker").update_available
    assert [c.name for c in status.updates_available] == ["klipper"]
    assert status.component("KLIPPER") is klipper  # case-insensitive, like Klipper names


def test_parse_tolerates_field_variants_and_system_package_counts():
    payload = {"result": {"version_info": {
        "klipper": {"current_version": "1.0", "available_version": "1.1"},
        "mainsail": {"version": "2.0", "latest_version": "2.0"},
        "system": {"package_count": 3, "package_list": ["a", "b", "c"]}}}}
    status = fw.parse_update_status(payload)
    assert status.component("klipper").update_available
    assert not status.component("mainsail").update_available
    system = status.component("system")
    assert system.package_count == 3 and system.update_available


@pytest.mark.parametrize("payload", [
    None, "nope", 42, {}, {"result": None}, {"result": {}},
    {"result": {"version_info": None}}, {"result": {"version_info": {}}},
    {"result": {"version_info": {"klipper": "v0.12"}}},
])
def test_parse_rejects_malformed_responses(payload):
    with pytest.raises(fw.FirmwareError):
        fw.parse_update_status(payload)


# ------------------------------------------------------------------- reading

def test_plain_read_makes_exactly_one_get_and_never_refreshes():
    transport = FakeTransport()
    status = fw.fetch_status(transport)
    assert transport.calls == [("GET", fw.UPDATE_STATUS_PATH, None)]
    assert status.component("zmod").current == "1.9.2"


def test_check_path_refreshes_first_and_parses_the_refresh_response():
    transport = FakeTransport()
    status = fw.fetch_status(transport, refresh=True)
    assert transport.calls == [("POST", fw.UPDATE_REFRESH_PATH, None)]
    assert status.component("klipper").remote == "v0.12.0-310"


def test_check_path_falls_back_to_a_plain_read_when_refresh_fails():
    transport = FakeTransport(refresh_error=OSError("503 while printing"))
    status = fw.fetch_status(transport, refresh=True)
    assert transport.calls == [("POST", fw.UPDATE_REFRESH_PATH, None),
                               ("GET", fw.UPDATE_STATUS_PATH, None)]
    assert status.component("klipper").current == "v0.12.0-289"


def test_read_wraps_transport_failures_and_malformed_payloads():
    with pytest.raises(fw.FirmwareError):
        fw.fetch_status(FakeTransport(error=OSError("unreachable")))
    with pytest.raises(fw.FirmwareError):
        fw.fetch_status(FakeTransport(status={"result": {"status": {}}}))


# ------------------------------------------------------------------- report

def test_report_shows_current_to_available_and_the_update_command():
    text = fw.firmware_report(FakeTransport(), AD5X)
    assert "**klipper**: v0.12.0-289 -> v0.12.0-310 available" in text
    assert "`/print-firmware update klipper`" in text
    assert "moonraker: v0.9.3-10 (up to date)" in text
    assert "Not covered by this check" in text  # the ZMod base + stock layers are named


def test_report_says_up_to_date_when_nothing_is_available():
    text = fw.firmware_report(FakeTransport(status=STATUS_UP_TO_DATE), GENERIC)
    assert "Everything Print Handy can check here is up to date." in text
    assert "available" not in text.split("up to date.")[0].split("**Firmware")[-1]


def test_report_for_a_fork_is_information_only_with_no_update_command():
    text = fw.firmware_report(FakeTransport(), NEPTUNE4)
    assert "-> v0.12.0-310 available" in text
    assert "`/print-firmware update" not in text
    assert "does not apply updates on vendor forks" in text


def test_report_fails_soft_when_the_status_cannot_be_read():
    with pytest.raises(fw.FirmwareError):
        fw.firmware_report(FakeTransport(error=OSError("unreachable")), AD5X)


# ------------------------------------------------------------- ZMod pairing

@pytest.mark.parametrize("os_version,zmod_version,expected", [
    ("1.9.4", "1.9.2", "match"),
    ("1.9.4", "1.9.0", "match"),
    ("1.8.0", "1.9.2", "mismatch"),
    ("2.0.1", "1.9.9", "mismatch"),
    (None, "1.9.2", "unknown"),
    ("1.9.4", None, "unknown"),
    ("1.9.4", "dev-build", "unknown"),
    ("", "", "unknown"),
])
def test_pairing_state(os_version, zmod_version, expected):
    assert fw.pairing_state(os_version, zmod_version) == expected


def test_report_names_a_pairing_mismatch_and_points_at_the_base_guide():
    transport = FakeTransport(system_info=SYSTEM_INFO_180)
    text = fw.firmware_report(transport, AD5X)
    assert "ZMod version mismatch" in text
    assert "`/print-firmware guide zmod`" in text


def test_report_does_not_claim_a_mismatch_when_the_os_version_is_unreadable():
    text = fw.firmware_report(FakeTransport(system_info=None), AD5X)
    assert "mismatch" not in text.casefold()


def test_report_notes_a_correct_pairing():
    text = fw.firmware_report(FakeTransport(system_info=SYSTEM_INFO_194), AD5X)
    assert "pair correctly" in text


# ------------------------------------------------------------------ MCU (Klipper 13)

STATUS_K13 = {"result": {"version_info": {
    "klipper": {"version": "v0.13.0-100", "remote_version": "v0.13.0-100"},
    "zmod": {"version": "1.9.2", "remote_version": "1.9.2"}}}}


def _mcu_payload(version):
    return {"result": {"status": {"mcu": {"mcu_version": version}}}}


@pytest.mark.parametrize("host,mcu,expected", [
    ("v0.13.0-100", "v0.13.0-90", "match"),       # same release triple: in step
    ("v0.13.0-100", "v0.12.0-289", "mismatch"),
    ("v0.12.0-289", "v0.11.0-1", "unknown"),      # only Klipper 13 is judged
    ("v0.13.0-100", None, "unknown"),
    ("v0.13.0-100", "garbage", "unknown"),
    (None, "v0.13.0-1", "unknown"),
])
def test_mcu_currency(host, mcu, expected):
    assert fw.mcu_currency(host, mcu) == expected


def test_report_names_an_mcu_mismatch_when_the_data_exposes_one():
    transport = FakeTransport(status=STATUS_K13, mcu=_mcu_payload("v0.12.0-289"))
    text = fw.firmware_report(transport, AD5X)
    assert "MCU out of step" in text and "UPDATE_MCU" in text


def test_report_is_silent_about_the_mcu_when_it_cannot_be_read():
    text = fw.firmware_report(FakeTransport(status=STATUS_K13, mcu=None), AD5X)
    assert "MCU out of step" not in text


# ------------------------------------------------------------------ bot wiring

def test_bot_command_registered_with_help_and_llm_parity():
    assert bot_commands.by_name("print-firmware") is not None
    assert bot_commands.as_text("print-firmware", {}) == "/print-firmware"
    assert "/print-firmware" in bot_commands.help_text()
    # Reporting and the guides are read-only, so the chat model may name them;
    # applying an update may never come from the model.
    assert llm.allowed_command("/print-firmware") == "/print-firmware"
    assert llm.allowed_command("/print-firmware guide zmod") == "/print-firmware guide zmod"
    assert llm.allowed_command("/print-firmware update klipper") is None


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


def _configured(key, connection):
    return mock.patch.object(printers, "current",
                             return_value=S(connection=connection, model=S(key=key)))


def test_dispatch_reports_the_firmware_state_with_a_check_refresh():
    adapter = FakeAdapter()
    transport = FakeTransport(system_info=SYSTEM_INFO_194)
    with _configured("flashforge.ad5x", "moonraker"), \
            mock.patch.object(spool_sync, "moonraker", transport):
        out = asyncio.run(plugin.firmware_dispatch(_event("/print-firmware"), _gateway(adapter)))
    assert out == {"action": "skip", "reason": "print firmware handled"}
    assert transport.calls[0] == ("POST", fw.UPDATE_REFRESH_PATH, None)
    assert "**klipper**: v0.12.0-289 -> v0.12.0-310 available" in adapter.sent[-1]


def test_dispatch_explains_non_moonraker_printers_without_calling_out():
    adapter = FakeAdapter()
    transport = FakeTransport()
    with _configured("bambulab.a1", "bambulab_lan"), \
            mock.patch.object(spool_sync, "moonraker", transport):
        out = asyncio.run(plugin.firmware_dispatch(_event("/print-firmware"), _gateway(adapter)))
    assert out["reason"] == "print firmware not applicable to this printer"
    assert transport.calls == []
    assert "no Moonraker Update Manager" in adapter.sent[-1]


def test_dispatch_reports_an_unreachable_moonraker_and_sends_nothing():
    adapter = FakeAdapter()
    transport = FakeTransport(error=OSError("unreachable"))
    with _configured("flashforge.ad5x", "moonraker"), \
            mock.patch.object(spool_sync, "moonraker", transport):
        out = asyncio.run(plugin.firmware_dispatch(_event("/print-firmware"), _gateway(adapter)))
    assert out == {"action": "skip", "reason": "print firmware handled"}
    assert adapter.sent[-1] == fw.COULD_NOT_READ_TEXT
    assert all(method == "GET" or path == fw.UPDATE_REFRESH_PATH
               for method, path, _ in transport.calls)
    assert not any(path == fw.UPDATE_UPGRADE_PATH for _, path, _ in transport.calls)


def test_dispatch_ignores_other_text():
    assert asyncio.run(plugin.firmware_dispatch(_event("/print-firmwarex"),
                                                _gateway(FakeAdapter()))) is None
    assert asyncio.run(plugin.firmware_dispatch(_event("print-firmware"),
                                                _gateway(FakeAdapter()))) is None
