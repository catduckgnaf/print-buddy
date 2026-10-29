"""Offer the next plate when the empty-bed check says the bed is clear (#621).

The offer is a message. It does not start a print. Confirm is still
``/print-next``, which keeps the bed-clear button. One offer per plate,
and one "not clear" note per plate. No camera verdict means no message.
"""
from __future__ import annotations

import json
import time

from . import _config

CHECK_S = 300
STATE = _config.state_file("PRINT_HANDY_NEXT_PLATE_OFFER", "next_plate_offer.json")


def decide(label, verdict, *, said, plan_id) -> dict:
    """What to say for one observation. ``said`` is a set of actions already posted.

    ``verdict`` None means there is no camera result. That is not an empty bed.
    """
    if not label:
        return {"action": "none", "text": ""}
    if verdict is None:
        return {"action": "none", "text": ""}
    if verdict == "empty_idle":
        if "offer" in said:
            return {"action": "none", "text": ""}
        return {
            "action": "offer",
            "text": (f"Bed looks clear. Send {label}?\n"
                     f"Use `/print-next {plan_id}` to start it. Nothing starts until you confirm. "
                     "Ignore this to leave the queue alone."),
        }
    if "not_clear" in said:
        return {"action": "none", "text": ""}
    return {
        "action": "not_clear",
        "text": ("The bed does not look clear, so the next plate is not offered. "
                 f"Use `/print-next {plan_id}` when it is clear."),
    }


def _load() -> dict:
    try:
        data = json.loads(STATE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data))


def remember(plan_id: str) -> None:
    """A multi-plate job finished a plate and still has another queued."""
    data = _load()
    if data.get("plan_id") != plan_id:
        data = {"plan_id": plan_id, "said": [], "checked_at": 0}
    _save(data)


def due(now=None) -> bool:
    data = _load()
    if not data.get("plan_id"):
        return False
    now = time.time() if now is None else now
    return now - float(data.get("checked_at") or 0) >= CHECK_S


def observe(verdict, now=None) -> str:
    """Apply one camera verdict. Returns the message to post, or ""."""
    data = _load()
    plan_id = data.get("plan_id")
    if not plan_id:
        return ""
    now = time.time() if now is None else now
    data["checked_at"] = now
    label = ""
    try:
        from . import print_next
        from .print_records import remaining_plate_choices
        plan = print_next.load_plan(plan_id)
        parts = remaining_plate_choices(plan)
        if parts:
            label = print_next.plate_choice_label(parts[0])
        else:
            data["plan_id"] = ""
    except Exception:
        label = ""
    said = set(data.get("said") or [])
    choice = decide(label, verdict, said=said, plan_id=str(plan_id))
    if choice["action"] != "none":
        said.add(choice["action"])
        data["said"] = sorted(said)
    _save(data)
    return choice["text"]
