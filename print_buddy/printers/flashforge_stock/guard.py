"""Stock Flashforge G-code guard.

Stock Adventurer firmware runs the slicer's own start and end G-code. It does not run
Klipper macros. A START_PRINT, END_PRINT, PRINT_START, PRINT_END, or any other bare
word that is not a G, M, or T code is another vendor's start code and must never be
uploaded. The check is line by line and stops after three examples, matching the Bambu
guard's shape.
"""
from __future__ import annotations

import re

_GCODE_WORD = re.compile(r"^[GMT]\d+(?:\.\d+)?$", re.IGNORECASE)
_FORBIDDEN = ("START_PRINT", "END_PRINT", "PRINT_START", "PRINT_END", "CHANGE_ZCOLOR", "LOAD_ZOFFSET")


def stock_gcode_problems(text: str) -> list[str]:
    """Reasons this G-code must not reach stock Flashforge firmware; empty when none."""
    foreign = []
    for number, line in enumerate(str(text or "").splitlines(), 1):
        command = line.split(";", 1)[0].strip()
        if not command:
            continue
        word = command.split()[0]
        if word.upper() in _FORBIDDEN or not _GCODE_WORD.match(word):
            foreign.append(f"line {number}: {command[:60]}")
            if len(foreign) == 3:
                break
    if not foreign:
        return []
    return ["G-code for stock Flashforge contains Klipper or ZMod commands: " + "; ".join(foreign)]
