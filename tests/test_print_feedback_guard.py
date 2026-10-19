"""Offline tests for the print-feedback plugin's clarify cap, repeat guard and hook registration.

The fuller guard, dispatch and workflow tests live in tests/hermes/. This file keeps the original small
guard assertions, now against the live plugin API.
"""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

PLUGIN_PATH = Path(__file__).parents[1] / "plugins/print-feedback/__init__.py"
spec = importlib.util.spec_from_file_location("print_feedback", PLUGIN_PATH)
assert spec is not None and spec.loader is not None
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


def session(profile="3dprinting", platform="discord"):
    values = {"HERMES_SESSION_PROFILE": profile, "HERMES_SESSION_PLATFORM": platform}
    return mock.patch.object(plugin, "_session", side_effect=lambda key: values.get(key, ""))


class GuardTests(unittest.TestCase):
    def setUp(self):
        plugin._tool_turns.clear()

    def invoke(self, command="status", *, profile="3dprinting", session_id="s", turn="t"):
        with session(profile):
            return plugin.guard_terminal_loop(
                tool_name="terminal", args={"command": command}, session_id=session_id, turn_id=turn)

    def test_third_duplicate_command_is_blocked_per_turn(self):
        self.assertIsNone(self.invoke())
        self.assertIsNone(self.invoke())
        self.assertEqual("block", self.invoke()["action"])

    def test_distinct_commands_and_new_turn_are_not_blocked(self):
        for i in range(50):
            self.assertIsNone(self.invoke(f"command-{i}"))
        self.assertIsNone(self.invoke(session_id="s", turn="next"))

    def test_other_profile_and_missing_identity_are_ignored(self):
        self.assertIsNone(self.invoke(profile="default"))
        self.assertIsNone(self.invoke(turn=""))

    def test_clarify_choices_are_capped_without_losing_other_path(self):
        args = {"questions": [{"question": "Pick", "choices": list("abcdef")}],
                "other": "preserved"}
        with session():
            result = plugin.cap_discord_clarifications(tool_name="clarify", args=args)
        self.assertEqual("modify", result["action"])
        self.assertEqual(list("abcd"), result["args"]["questions"][0]["choices"])
        self.assertIn("Other", result["args"]["questions"][0]["question"])
        self.assertEqual("preserved", result["args"]["other"])

    def test_small_choice_list_and_non_discord_are_unchanged(self):
        args = {"questions": [{"question": "Pick", "choices": ["yes", "no"]}]}
        with session():
            self.assertIsNone(plugin.cap_discord_clarifications(tool_name="clarify", args=args))
        with session(profile="printer"):
            self.assertIsNone(plugin.cap_discord_clarifications(tool_name="clarify", args=args))
        with session(platform="matrix"):
            self.assertIsNone(plugin.cap_discord_clarifications(tool_name="clarify", args=args))

    def test_registers_the_hooks_declared_in_plugin_yaml(self):
        ctx = mock.Mock()
        plugin.register(ctx)
        hooks = {call.args[0] for call in ctx.register_hook.call_args_list}
        declared = {line.split("- ", 1)[1].strip() for line in
                    PLUGIN_PATH.with_name("plugin.yaml").read_text().splitlines() if line.startswith("  - ")}
        self.assertEqual(declared, hooks)
        pre_tool = [call.args[1] for call in ctx.register_hook.call_args_list if call.args[0] == "pre_tool_call"]
        self.assertEqual([plugin.cap_discord_clarifications, plugin.guard_terminal_loop], pre_tool)
        self.assertEqual("discord", ctx.register_platform_handler.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
