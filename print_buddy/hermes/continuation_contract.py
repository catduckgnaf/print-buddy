from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping
import secrets
import threading


class ContinuationStartGate:
    """Single-use, exact-artifact continuation approval for a Discord button adapter.

    The adapter must bind the returned opaque token to its button callback and call
    ``confirm`` only after the user explicitly confirms the bed is clear. The
    start function is invoked at most once, and a failed or uncertain start is not
    replayable with that token.
    """

    def __init__(self):
        self._pending: dict[str, str] = {}
        self._lock = threading.Lock()

    def prepare(self, exact_artifact: str) -> str:
        if not exact_artifact or Path(exact_artifact).name != exact_artifact:
            raise ValueError("continuation requires an exact artifact basename")
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._pending[token] = exact_artifact
        return token

    def confirm(self, token: str, exact_artifact: str, bed_is_clear: bool,
                start_exact_artifact: Callable[[str], Any]) -> Any:
        with self._lock:
            bound_artifact = self._pending.pop(token, None)
        if bound_artifact is None:
            raise ValueError("confirmation expired, was cancelled, or was already used")
        if bound_artifact != exact_artifact:
            raise ValueError("confirmation does not match the exact prepared artifact")
        if bed_is_clear is not True:
            raise ValueError("fresh bed-clear confirmation is required")
        # Consume before side effect. Any uncertain result must be reconciled, not replayed.
        return start_exact_artifact(bound_artifact)


def build_continuation_contract(plan: Mapping[str, Any], completed_artifact: str | None = None) -> dict[str, Any] | None:
    """Build sanitized JSON data for UI surfaces; never include paths or hashes."""
    from .print_records import _plan_parts, _first

    parts = _plan_parts(plan.get("parts"))
    if not parts:
        return None
    required = [p for p in parts if not (p.get("optional") is True or p.get("required") is False)
                and not (p.get("alternative_group") and p.get("selected") is not True)]

    def where(part):
        return {"run": _first(part, "run", "run_id"), "plate": _first(part, "plate", "plate_id")}

    completed = []
    remaining = []
    for part in required:
        quantity = part["quantity"]
        done = quantity if part.get("status") == "completed" else part["completed_quantity"]
        if done:
            completed.append({"label": part["label"], "quantity": min(done, quantity), **where(part)})
        if done < quantity:
            remaining.append((part, quantity - done))
    if not remaining:
        return {"schema": "print_continuation_v1", "completed_parts": completed,
                "next_part": None, "remaining_parts": [], "job_complete": True,
                "start_option": None}

    next_part, next_count = remaining[0]
    next_item = {"label": next_part["label"], "quantity": next_count, **where(next_part)}
    safe_parts = []
    for part, count in remaining:
        item = {"label": part["label"], "quantity": count, **where(part)}
        estimate = part.get("estimated_part_seconds")
        if isinstance(estimate, (int, float)) and not isinstance(estimate, bool) and estimate >= 0:
            item["estimated_part_seconds"] = estimate
        safe_parts.append(item)
    artifact = str(next_part.get("gcode_file") or "")
    exact = bool(artifact) and Path(artifact).name == artifact
    return {"schema": "print_continuation_v1", "completed_parts": completed,
            "current_artifact": Path(completed_artifact).name if completed_artifact else None,
            "next_part": next_item, "remaining_parts": safe_parts,
            "job_complete": False,
            # Offered only when the plan records an exact basename artifact; never a path.
            "start_option": ({"label": "Start next plate · bed is clear",
                              "requires_fresh_exact_artifact_confirmation": True,
                              "automatic_advance": False} if exact else None)}
