"""Named objects on a Moonraker plate, and one confirmed exclude (#620).

Stage 1 lists objects whose G-code carries EXCLUDE_OBJECT_DEFINE. A file
without that metadata produces no line, not an error.

Stage 2 builds the Moonraker exclude call only after confirm. The last
remaining object is not an exclude, confirmed or not: the caller must use
the existing cancel confirm. A refused or unconfirmed name never produces
a call, so a failed or skipped exclude cannot be reported as done.
"""
from __future__ import annotations

import re
from pathlib import Path

_DEFINE = re.compile(r"^EXCLUDE_OBJECT_DEFINE\s+NAME=(\S+)", re.M)


def object_names(text: str) -> list[str]:
    """Object names in slicer order. Empty when the file has no exclude metadata."""
    names: list[str] = []
    for match in _DEFINE.finditer(text or ""):
        name = match.group(1).strip().strip('"').strip("'")
        if name and name not in names:
            names.append(name)
    return names


def objects_line(names) -> str:
    """The progress-post line, or "" when there is nothing to list."""
    if not names:
        return ""
    return "Objects still printing: " + ", ".join(names)


def objects_line_for_path(path) -> str:
    """Read one G-code. A missing or unreadable file is the same as no metadata."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return ""
    return objects_line(object_names(text))


def exclude_plan(names, target, *, confirmed: bool, remaining=None) -> dict:
    """What to do with one named object. ``body`` is set only for a confirmed exclude.

    The body is a Moonraker ``printer.gcode.script`` call whose script is
    ``EXCLUDE_OBJECT NAME=<target>``. The last remaining object returns
    ``cancel_print`` and no body.
    """
    left = list(names if remaining is None else remaining)
    target = str(target or "")
    if target not in left:
        return {"action": "refuse", "name": target,
                "reason": f"{target} is not an object still printing on this plate", "body": None}
    after = [name for name in left if name != target]
    if not after:
        return {"action": "cancel_print", "name": target,
                "reason": "That is the last object. Cancel the whole print instead.", "body": None}
    if any(ch in target for ch in "\r\n;\"'\\"):
        return {"action": "refuse", "name": target,
                "reason": f"{target} cannot be excluded from chat", "body": None}
    if not confirmed:
        return {"action": "confirm", "name": target,
                "reason": f"Cancel {target} and keep printing the rest?", "body": None}
    return {
        "action": "exclude",
        "name": target,
        "reason": f"Excluding {target}.",
        "body": {"jsonrpc": "2.0", "method": "printer.gcode.script",
                 "params": {"script": f"EXCLUDE_OBJECT NAME={target}"}},
    }
