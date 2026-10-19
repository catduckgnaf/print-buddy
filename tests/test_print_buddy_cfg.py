"""Render PRINT_BUDDY the way Klipper's Jinja2 does.

No printer, no Moonraker, no network. Klipper's environment uses {% %} for
blocks and a single { } for expressions, including action_respond_info.
"""

from __future__ import annotations

import pathlib
import unittest

import jinja2


ROOT = pathlib.Path(__file__).resolve().parents[1]
CFG = (ROOT / "print_buddy.cfg").read_text()


def macro_body() -> str:
    marker = "[gcode_macro PRINT_BUDDY]\n"
    start = CFG.index(marker)
    body = CFG[start:]
    gcode_at = body.index("gcode:\n")
    return body[gcode_at + len("gcode:\n") :]


class Printer:
    def __init__(self, slots):
        self.slots = slots

    def __getitem__(self, key):
        if key != "gcode_macro _PRINT_BUDDY_VARS":
            raise KeyError(key)
        return self

    def __getattr__(self, name):
        return self.slots[name]


def render(params, slots):
    env = jinja2.Environment("{%", "%}", "{", "}")
    messages = []

    def action_respond_info(message):
        messages.append(message)
        return ""

    env.globals["action_respond_info"] = action_respond_info
    out = env.from_string(macro_body()).render(params=params, printer=Printer(slots))
    if "action_respond_info" in out:
        raise AssertionError("action was not executed:\n" + out)
    if not messages:
        raise AssertionError("template produced no message:\n" + out)
    return messages


BASE = {
    "slot1_color": "black",
    "slot1_material": "PETG",
    "slot2_color": 0,
    "slot2_material": 0,
    "slot3_color": "Black",
    "slot3_material": "petg",
    "slot4_color": "black",
    "slot4_material": "PLA",
}


class PrintBuddyReportTest(unittest.TestCase):
    def test_same_color_and_material_is_reported(self):
        messages = render({"SLOT": "1"}, BASE)
        self.assertEqual(len(messages), 1)
        self.assertIn("slot 3", messages[0])
        self.assertNotIn("slot 4", messages[0])
        self.assertNotIn("slot 2", messages[0])
        self.assertIn("does not", messages[0])

    def test_different_material_is_not_a_match(self):
        messages = render({"SLOT": "4"}, BASE)
        self.assertIn("no other slot", messages[0])

    def test_unset_slot_asks_for_both_fields(self):
        messages = render({"SLOT": "2"}, BASE)
        self.assertIn("no color and material", messages[0])

    def test_explicit_color_and_material_skip_no_loaded_slot(self):
        messages = render({"COLOR": "black", "MATERIAL": "PETG"}, BASE)
        self.assertIn("slot 1,3", messages[0])

    def test_blank_explicit_values_do_not_match_everything(self):
        messages = render({"COLOR": "0", "MATERIAL": "0"}, BASE)
        self.assertIn("no color and material", messages[0])

    def test_scripts_exist_and_do_not_edit_printer_config(self):
        for name in ("install.sh", "uninstall.sh", "update.sh"):
            text = (ROOT / name).read_text()
            self.assertTrue(text.startswith("#!/bin/sh\n"), name)
            self.assertNotIn("printer.base.cfg", text)
            self.assertNotIn("SET_EXTRUDER_SLOT", text)
            self.assertNotIn("plugins/print-feedback", text)

    def test_install_does_not_ship_the_discord_hook(self):
        install = (ROOT / "install.sh").read_text()
        self.assertNotIn("pre_tool_call", install)
        self.assertNotIn("__init__.py", install)


if __name__ == "__main__":
    unittest.main()
