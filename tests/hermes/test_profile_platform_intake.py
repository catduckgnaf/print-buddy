"""#384 verification tail: with the profile's Discord platform enabled, a
dropped model file delivered by the gateway reaches Print Buddy's intake.

The incident could only be verified up to "the adapter connected" — the
original attachment was never replayed. This pins the offline half of the
chain: the gateway hook (model_link_dispatch, the same entry point the
Hermes gateway uses) routes a Discord attachment event into
prepared_intake.prepare_link. The disabled half — intake silently absent —
is pinned as a named failure by the check-surface tests
(tests/test_profile_platform.py, tests/test_doctor.py,
tests/bot/test_health_and_transport.py).
"""
import asyncio
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace as S
from unittest import mock

from print_buddy.core import prepared_intake, printer_state
from print_buddy.hermes import _config

SPEC = importlib.util.spec_from_file_location(
    "print_feedback_384", Path(__file__).parents[2] / "plugins/print-feedback/__init__.py")
assert SPEC is not None and SPEC.loader is not None
plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin)


def test_attachment_reaches_intake_with_platform_enabled(tmp_path):
    previous = copy.deepcopy(_config.cfg())
    data = copy.deepcopy(previous)
    data["paths"]["hermes_home"] = tmp_path / "profile"
    _config.set_override(data)
    try:
        home = _config.hermes_home()
        home.mkdir(parents=True)
        (home / "config.yaml").write_text("platforms:\n  discord:\n    enabled: true\n")
        assert _config.profile_platform_state("discord")[0] == "enabled"

        model = tmp_path / "widget.stl"
        model.write_bytes(b"solid widget\nendsolid widget\n")
        adapter = S()
        gateway = S(_is_user_authorized_for_source=lambda _s: True,
                    _session_key_for_source=lambda _s: "sess",
                    _delivery_adapter_for=lambda _s: adapter)
        source = S(platform=S(value="discord"), profile="3dprinting", user_id="u1",
                   chat_id="c1", thread_id=None, is_bot=False, profile_route_rejected=False)
        event = S(source=source, text="", media_urls=[str(model)], message_id="m1",
                  metadata={}, internal=False)
        sentinel = {"action": "skip", "reason": "intake reached"}
        with mock.patch.object(printer_state, "load", return_value=S()), \
                mock.patch.object(prepared_intake, "prepare_link",
                                  new=mock.AsyncMock(return_value=sentinel)) as prepare:
            outcome = asyncio.run(plugin.model_link_dispatch(event, gateway))
        assert outcome is sentinel
        assert event.metadata["fresh_model_intake_handled"] is True
        prepare.assert_awaited_once()
        assert prepare.await_args.args[0] is event
        assert prepare.await_args.args[1] is adapter
    finally:
        _config.set_override(previous)
