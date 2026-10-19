#!/usr/bin/env python3
"""Durable Print Bitch completion records and safe session cleanup.

The watcher supplies confirmed Moonraker data and, when available, a JSON
context sidecar through PRINT_BITCH_CONTEXT_PATH. The sidecar is the only
source for user confirmation, source selection, author-directed supports, and
Discord session identity. Missing values stay blank or are marked unavailable.
No slicing, support generation, printer control, or gateway operation happens
here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import _config

VAULT_ROOT = _config.records_vault()
PRINTS_DIR = VAULT_ROOT / "Prints"
PLANS_DIR = VAULT_ROOT / "Plans"
DEFAULT_CHAT_ID = _config.discord_chat_id()
CLEANUP_DELAY_SECONDS = 5 * 60
NATIVE_PRINT_OPTIONS = (
    "Bed clear: upload and start print",
    "Not clear: do not upload or start",
    "Keep sliced only",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


ET = _config.tz()  # the configured display timezone (discord.timezone); the name is historical
TERMINAL_STATUS = {"complete": ("completed", True), "cancelled": ("cancelled", False), "error": ("failed", False), "printing": ("printing", None)}


def et_text(value: Any) -> str | None:
    """Render an ISO UTC stamp in the configured display timezone for the human facing note."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).strftime("%Y-%m-%d %I:%M %p %Z")


def _hm(seconds: Any) -> str | None:
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return None
    return f"{total // 3600}h {total % 3600 // 60}m"


def _grams(mm: Any, context: Mapping[str, Any]) -> float | None:
    try:
        d, rho = float(context["filament_diameter_mm"]), float(context["filament_density"])
        return round(float(mm) * 3.141592653589793 * (d / 2) ** 2 * rho / 1000, 1)
    except (KeyError, TypeError, ValueError):
        return None


def _safe_slug(value: str, fallback: str = "print") -> str:
    value = re.sub(r"[^A-Za-z0-9._]+", "-", str(value or "").strip()).strip(".-")
    return value[:100] or fallback


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _json_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _frontmatter_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def load_context(job_key: str, path: Path | None = None) -> dict[str, Any]:
    """Load the optional Print Bitch confirmation context without guessing.

    Supported sidecar shapes are either one job object, or
    ``{"jobs": {"gcode/path": {...}}}``. A nonmatching or malformed file is
    treated as absent so a bad sidecar cannot stop completion announcements.
    """
    configured = path or _config.state_file("PRINT_BITCH_CONTEXT_PATH", "print_bitch_context.json")
    try:
        payload = json.loads(configured.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    jobs = payload.get("jobs")
    if isinstance(jobs, dict) and isinstance(jobs.get(job_key), dict):
        return dict(jobs[job_key])
    if payload.get("job_key") in (None, job_key):
        return payload
    return {}


def _spool_fields(spool: Any) -> dict[str, Any]:
    if not isinstance(spool, dict):
        return {}
    filament = spool.get("filament") if isinstance(spool.get("filament"), dict) else {}
    vendor = filament.get("vendor") if isinstance(filament.get("vendor"), dict) else {}
    return {
        "spoolman_spool_id": _first(spool, "id", "spool_id"),
        "filament_vendor": _first(spool, "vendor", "vendor_name") or _first(vendor, "name"),
        "filament_material": _first(spool, "material", "material_name") or _first(filament, "material", "name"),
        "filament_color": _first(spool, "color", "color_name") or _first(filament, "color"),
    }


def _safe_label(value, fallback):
    from . import discord_print_summary
    return discord_print_summary.safe_label(value, fallback)


def _resolved_title(filename):
    """Model title for a hashed Moonraker filename, so records never use the hash as a name."""
    try:
        from . import discord_print_summary
        job, _plate = discord_print_summary.find_job(filename)
        return discord_print_summary.safe_label(job["title"]) if job and job.get("title") else None
    except Exception:
        return None


def build_record_data(
    filename: str,
    stats: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    active_spool: Mapping[str, Any] | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    """Build a record from confirmed data only."""
    stats = stats or {}
    metadata = metadata or {}
    context = dict(context or {})
    spool = active_spool or context.get("active_spool") or {}
    spool_fields = _spool_fields(spool)
    slicer_settings = _first(metadata, "slicer_settings", "slicer_settings_json") or context.get("slicer_settings")
    if not isinstance(slicer_settings, (dict, list, str, int, float, bool)):
        slicer_settings = None
    tree_supports = context.get("author_directed_tree_supports")
    if tree_supports is None:
        tree_supports = context.get("tree_supports")
    selected_option = context.get("selected_option")
    if selected_option not in NATIVE_PRINT_OPTIONS:
        selected_option = None
    native = str(_first(stats, "state") or "complete").lower()
    status, success = TERMINAL_STATUS.get(native, (native, None))
    used_mm = _first(stats, "filament_used") or _first(metadata, "filament_used")
    return {
        "status": status,
        "success": success,
        "title": context.get("title") or _resolved_title(filename),
        "started_at": context.get("started_at"),
        "completed_at": None if status == "printing" else (completed_at or utc_now()),
        "hardware": context.get("hardware"),
        "estimated_time": context.get("estimated_time"),
        "estimated_filament_g": context.get("estimated_filament_g"),
        "filament_used_g": _grams(used_mm, context),
        "record_path": context.get("record_path"),
        "source_url": context.get("source_url"),
        "source_platform": context.get("source_platform"),
        "selected_option": selected_option,
        "selection_confirmation": context.get("selection_confirmation") if selected_option else None,
        "printer": context.get("printer") or context.get("printer") or "Klipper 3D Printer",
        "printer_profile": _first(context, "printer_profile") or _first(metadata, "printer_profile", "printer_model"),
        "gcode_file": filename,
        "filament_vendor": spool_fields.get("filament_vendor"),
        "filament_material": spool_fields.get("filament_material"),
        "filament_color": spool_fields.get("filament_color"),
        "spoolman_spool_id": spool_fields.get("spoolman_spool_id"),
        "filament_used_mm": used_mm,
        "print_duration_seconds": _first(stats, "print_duration", "total_duration") or _first(metadata, "print_duration"),
        "slicer_settings": slicer_settings,
        "author_directed_tree_supports": tree_supports,
        "physical_outcome": context.get("physical_outcome"),
        "follow_up": context.get("follow_up"),
        "multipart_plan_id": context.get("multipart_plan_id"),
        "part_id": context.get("part_id") or filename,
        "required_parts": context.get("required_parts"),
        "discord_session_id": context.get("discord_session_id"),
        "discord_chat_id": str(context.get("discord_chat_id") or DEFAULT_CHAT_ID),
        "moonraker_state": native,
        "job_key": context.get("job_key"),
    }


def _record_markdown(data: Mapping[str, Any], cleanup_status: str = "pending") -> str:
    frontmatter = {
        "status": data.get("status"),
        "success": data.get("success"),
        "title": data.get("title"),
        "started_et": et_text(data.get("started_at")),
        "finished_et": et_text(data.get("completed_at")),
        "started_at": data.get("started_at"),
        "completed_at": data.get("completed_at"),
        "source_url": data.get("source_url"),
        "source_platform": data.get("source_platform"),
        "selected_option": data.get("selected_option"),
        "printer": data.get("printer"),
        "printer_profile": data.get("printer_profile"),
        "gcode_file": data.get("gcode_file"),
        "filament_vendor": data.get("filament_vendor"),
        "filament_material": data.get("filament_material"),
        "filament_color": data.get("filament_color"),
        "spoolman_spool_id": data.get("spoolman_spool_id"),
        "filament_used_mm": data.get("filament_used_mm"),
        "print_duration_seconds": data.get("print_duration_seconds"),
        "cleanup_status": cleanup_status,
    }
    settings = data.get("slicer_settings")
    settings_text = "not recorded" if settings is None else json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True)
    lines = ["---"]
    lines.extend(f"{key}: {_frontmatter_value(value)}" for key, value in frontmatter.items())
    lines.extend([
        "---",
        "",
        f"# {data.get('title') or _safe_label(data.get('gcode_file'), 'Completed print')}",
        "",
        "## Date",
        "",
        f"- **Started:** {et_text(data.get('started_at')) or 'not recorded'}",
        f"- **Finished:** {et_text(data.get('completed_at')) or ('in progress' if data.get('status') == 'printing' else 'not recorded')}",
        f"- **Status:** {data.get('status') or 'not recorded'}",
        f"- **Actual duration:** {_hm(data.get('print_duration_seconds')) or 'not recorded'}",
        f"- **Slicer estimate:** {data.get('estimated_time') or 'not recorded'}",
        "",
        "## Hardware",
        "",
        f"- **Printer / nozzle / spool / temps:** {data.get('hardware') or 'not recorded'}",
        f"- **G-code:** `{data.get('gcode_file') or 'not recorded'}`",
        "",
        "## Selected source option",
        "",
        f"- **Selected:** {data.get('selected_option') or 'not recorded'}",
        f"- **Reason / user confirmation:** {data.get('selection_confirmation') or 'not recorded'}",
        f"- **Source:** {data.get('source_platform') or 'not recorded'} {data.get('source_url') or ''}".rstrip(),
        "",
        "## Print settings used",
        "",
        f"- **Printer profile:** {data.get('printer_profile') or 'not recorded'}",
        f"- **Duration (seconds):** {data.get('print_duration_seconds') if data.get('print_duration_seconds') is not None else 'not recorded'}",
        "- **Confirmed slicer settings:**",
        "",
        "```json",
        settings_text,
        "```",
        f"- **Supports:** {_supports_text(data.get('author_directed_tree_supports'))}",
        "",
        "## Material",
        "",
        f"- **Vendor:** {data.get('filament_vendor') or 'not recorded'}",
        f"- **Material:** {data.get('filament_material') or 'not recorded'}",
        f"- **Color:** {data.get('filament_color') or 'not recorded'}",
        f"- **Spoolman spool:** {data.get('spoolman_spool_id') or 'not recorded'}",
        f"- **Used filament (mm):** {data.get('filament_used_mm') if data.get('filament_used_mm') is not None else 'not recorded'}",
        f"- **Used filament (g):** {data.get('filament_used_g') if data.get('filament_used_g') is not None else 'not recorded'}",
        f"- **Slicer filament estimate (g):** {data.get('estimated_filament_g') or 'not recorded'}",
        "",
        "## Result",
        "",
        f"- **Moonraker completion:** {data.get('moonraker_state') or 'not recorded'}",
        f"- **Physical outcome reported by user:** {data.get('physical_outcome') or 'not recorded'}",
        f"- **Follow-up / multipart plan:** {data.get('follow_up') or data.get('multipart_plan_id') or 'not recorded'}",
        "",
        "## Session cleanup",
        "",
        f"- **Status:** {cleanup_status}",
        "- **Occurred at:** not recorded",
        "- **Session:** not recorded",
        "- **Detail:** pending five-minute eligible cleanup",
        "",
    ])
    return "\n".join(lines)


def _supports_text(value: Any) -> str:
    if value is True:
        return "author explicitly required tree supports"
    if value is False:
        return "author explicitly did not require tree supports"
    if value not in (None, ""):
        return str(value)
    return "not recorded; no support decision was inferred"


def _plan_parts(required_parts: Any) -> list[dict[str, Any]]:
    if not isinstance(required_parts, list):
        return []
    result = []
    for item in required_parts:
        if isinstance(item, str) and item.strip():
            result.append({"id": item, "label": item, "status": "planned", "quantity": 1, "completed_quantity": 0})
        elif isinstance(item, dict):
            part_id = _first(item, "id", "part_id", "filename", "name")
            if part_id:
                quantity = item.get("quantity", item.get("required_quantity", 1))
                if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
                    quantity = 1
                completed_quantity = item.get("completed_quantity", 0)
                if isinstance(completed_quantity, bool) or not isinstance(completed_quantity, int):
                    completed_quantity = 0
                completed_quantity = min(max(completed_quantity, 0), quantity)
                part = {"id": str(part_id), "label": item.get("label") or str(part_id),
                        "status": item.get("status") or "planned", "quantity": quantity,
                        "completed_quantity": completed_quantity}
                for key in ("plate_id", "plate", "run_id", "run", "optional", "required",
                            "alternative_group", "selected", "estimated_part_seconds",
                            "plate_estimate_seconds", "estimated_filament_g", "gcode_file", "job_json", "gcode_path"):
                    if key in item:
                        part[key] = item[key]
                if part["status"] == "completed":
                    part["completed_quantity"] = quantity
                result.append(part)
    return result


def remaining_plate_choices(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Remaining required parts the plan can start exactly (recorded JOB.json and G-code path), in plan order."""
    from .print_next import has_exact_start_target, remaining_parts

    return [part for part, _done in remaining_parts(plan) if has_exact_start_target(part)]


def format_multipart_summary(plan: Mapping[str, Any], completed_part_id: str | None = None,
                             picker: bool = False) -> str | None:
    """Render required-part progress by physical plate and run, without guessing estimates.

    ``picker=True`` means the caller posts an interactive plate picker, so no command text is shown.
    """
    raw_parts = plan.get("parts") if isinstance(plan, Mapping) else None
    parts = _plan_parts(raw_parts)
    if not parts:
        return None

    def placement(part: Mapping[str, Any]) -> str:
        run = _first(part, "run", "run_id")
        plate = _first(part, "plate", "plate_id")
        labels = []
        if run is not None:
            labels.append(f"Run {run}")
        if plate is not None:
            labels.append(f"Plate {plate}")
        return ", ".join(labels) if labels else "Run not recorded, plate not recorded"

    required = []
    variants = []
    for part in parts:
        alt_group = part.get("alternative_group")
        chosen = part.get("selected") is True
        optional = part.get("optional") is True or part.get("required") is False
        if optional or (alt_group and not chosen):
            variants.append(part)
        else:
            required.append(part)

    completed_lines = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for part in required:
        quantity = part["quantity"]
        completed = part["completed_quantity"]
        if part.get("status") == "completed":
            completed = quantity
        completed = min(max(completed, 0), quantity)
        if completed:
            completed_lines.append(f"{part['label']} x{completed}")
        if completed < quantity:
            groups.setdefault(placement(part), []).append({**part, "completed_quantity": completed})

    lines = ["**Print continuation:**"]
    if completed_lines:
        lines.append("- Completed required parts: " + "; ".join(completed_lines))
    else:
        lines.append("- Completed required parts: none recorded")

    remaining = [(group, rows) for group, rows in groups.items()]
    if not remaining:
        lines.append("- Remaining required parts: none. Job complete.")
    else:
        next_part = next((part for _, rows in remaining for part in rows), None)
        current_names = set()
        if completed_part_id:
            current_path = Path(str(completed_part_id))
            current_names = {str(completed_part_id), current_path.name, current_path.stem}
            current_names |= {name.replace("_", " ") for name in tuple(current_names)}
        current_part = next((part for part in required
                             if str(part.get("id")) in current_names
                             or str(part.get("label")) in current_names
                             or Path(str(part.get("gcode_file") or "")).name in current_names
                             or Path(str(part.get("last_gcode_file") or "")).name in current_names), None)
        current_plate = placement(current_part) if current_part else None
        if current_part or completed_part_id:
            finished_labels = [part["label"] for part in required
                               if str(part.get("id")) in current_names
                               or str(part.get("label")) in current_names
                               or Path(str(part.get("gcode_file") or "")).name in current_names
                               or Path(str(part.get("last_gcode_file") or "")).name in current_names]
            if finished_labels:
                lines.append("- Current print finished: " + ", ".join(finished_labels))
            if remaining:
                lines.append(f"- Current plate/run finished: {current_plate or 'plate/run not recorded'}")
                lines.append("- Remove the finished pieces and clear the bed before the next plate.")
        if next_part:
            lines.append(f"- Next required part: {next_part['label']} ({placement(next_part)})")
        lines.append("- All remaining required parts:")
        known_total = 0
        unknown_groups = []
        for group, rows in remaining:
            lines.append(f"  - {group}:")
            per_part_estimates = [part.get("estimated_part_seconds") for part in rows]
            if all(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
                   for value in per_part_estimates):
                estimate = sum(value * (part["quantity"] - part["completed_quantity"])
                               for part, value in zip(rows, per_part_estimates))
                estimate_label = f"part estimates ~{_hm(estimate)}"
                known_total += estimate
            else:
                shared = [float(value) for part in rows
                          if isinstance((value := part.get("plate_estimate_seconds")), (int, float))
                          and not isinstance(value, bool) and value >= 0]
                if len(shared) == len(rows) and shared:
                    estimate = max(shared)
                    estimate_label = f"shared plate estimate ~{_hm(estimate)}; these pieces share the plate"
                    known_total += estimate
                elif len(shared) == 1:
                    estimate = shared[0]
                    estimate_label = f"shared plate estimate ~{_hm(estimate)}; these pieces share the plate"
                    known_total += estimate
                elif shared:
                    estimate_label = "shared plate estimate inconsistent; duration unknown"
                    unknown_groups.append(group)
                else:
                    estimate_label = "duration unknown"
                    unknown_groups.append(group)
            lines.append(f"    - {estimate_label}")
            for part in rows:
                remaining_count = part["quantity"] - part["completed_quantity"]
                part_estimate = part.get("estimated_part_seconds")
                if part_estimate is None:
                    estimate_detail = ""
                elif isinstance(part_estimate, (int, float)) and not isinstance(part_estimate, bool) and part_estimate >= 0:
                    estimate_detail = f"; per-part estimate ~{_hm(part_estimate)}"
                else:
                    estimate_detail = "; per-part estimate unknown"
                lines.append(f"    - {part['label']}: {remaining_count} remaining{estimate_detail}")
        if unknown_groups:
            lines.append("- Combined remaining duration incomplete; unknown estimate for " + "; ".join(unknown_groups))
        else:
            lines.append(f"- Combined remaining duration: ~{_hm(known_total)}")
        next_artifact = str(next_part.get("gcode_file") or "") if next_part else ""
        exact_target = bool(next_part and next_part.get("job_json") and next_part.get("gcode_path"))
        plan_id = plan.get("plan_id") if isinstance(plan, Mapping) else None
        if exact_target and plan_id and picker:
            lines.append("- Start option: choose the next plate from the picker below, then tap Confirm bed is clear & print. "
                         "One tap starts that exact plate once. No automatic advance.")
        elif exact_target and plan_id:
            lines.append(f"- Start option: type `/print-next {plan_id}` for a Start next plate · bed is clear button. "
                         "One tap starts this exact plate once. No automatic advance.")
        elif next_artifact and Path(next_artifact).name == next_artifact:
            lines.append("- Start option: Start next plate · bed is clear; require a fresh confirmation for this exact artifact. No automatic advance.")

    if variants:
        lines.append("- Optional or alternative variants (not required): " + "; ".join(
            f"{part['label']} ({'optional' if part.get('optional') is True or part.get('required') is False else 'alternative set ' + str(part.get('alternative_group'))})"
            for part in variants))
    return "\n".join(lines)


def _bind_same_job_plates(parts: list[dict[str, Any]], data: Mapping[str, Any]) -> None:
    """Record exact start targets for parts that are plates of the job just printed.

    Only the JOB.json that owns the completed G-code is consulted, and a part is
    bound only when its basename matches exactly one plate in that job.
    """
    settings = data.get("slicer_settings")
    local = settings.get("local_gcode") if isinstance(settings, Mapping) else None
    if not local:
        return
    job_path = next((parent / "JOB.json" for parent in Path(str(local)).parents
                     if (parent / "JOB.json").is_file()), None)
    if job_path is None:
        return
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    plates = [str(row["gcode"]) for row in job.get("derived_plates") or []
              if isinstance(row, dict) and row.get("gcode")]
    if job.get("gcode") and str(job["gcode"]) not in plates:
        plates.append(str(job["gcode"]))
    for part in parts:
        name = str(part.get("gcode_file") or "")
        if part.get("job_json") or not name or Path(name).name != name:
            continue
        matches = [plate for plate in plates if Path(plate).name == name]
        if len(matches) == 1:
            part["job_json"] = str(job_path)
            part["gcode_path"] = matches[0]


def update_multipart_plan(data: Mapping[str, Any]) -> tuple[str | None, bool]:
    plan_id = data.get("multipart_plan_id")
    required = _plan_parts(data.get("required_parts"))
    if not plan_id and not required:
        return None, True
    if not plan_id:
        plan_id = _safe_slug(data.get("gcode_file"), "print-plan")
    plan_id = _safe_slug(str(plan_id), "print-plan")
    json_path = PLANS_DIR / f"{plan_id}.json"
    try:
        existing = json.loads(json_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        existing = {}
    parts = existing.get("parts") if isinstance(existing, dict) else None
    if not isinstance(parts, list) or required:
        by_id = {str(part.get("id")): part for part in (parts or []) if isinstance(part, dict) and part.get("id")}
        for part in required:
            existing_part = by_id.setdefault(str(part["id"]), part)
            # Exact start targets may arrive after the plan was first written.
            for key in ("job_json", "gcode_path", "gcode_file"):
                if part.get(key) and not existing_part.get(key):
                    existing_part[key] = part[key]
        parts = list(by_id.values())
    current_id = str(data.get("part_id") or data.get("gcode_file"))
    current_artifact = Path(str(data.get("gcode_file") or "")).stem
    completed_units = data.get("completed_quantity", data.get("part_quantity", 1))
    if isinstance(completed_units, bool) or not isinstance(completed_units, int) or completed_units < 1:
        completed_units = 1
    matched = False
    for part in parts:
        matches_id = str(part.get("id")) == current_id or str(part.get("label")) == current_id
        artifact_names = {str(part.get(key) or "") for key in ("gcode_file", "last_gcode_file")}
        artifact_names |= {Path(name).name for name in tuple(artifact_names) if name}
        artifact_stems = {Path(name).stem for name in artifact_names if name}
        matches_artifact = bool(current_artifact) and (str(data.get("gcode_file")) in artifact_names or current_artifact in artifact_stems)
        if matches_id or matches_artifact:
            quantity = part.get("quantity", 1)
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
                quantity = 1
            already_completed = part.get("completed_quantity", 0)
            if isinstance(already_completed, bool) or not isinstance(already_completed, int):
                already_completed = 0
            part["quantity"] = quantity
            part["completed_quantity"] = min(quantity, max(0, already_completed) + completed_units)
            part["status"] = "completed" if part["completed_quantity"] >= quantity else "planned"
            part["completed_at"] = data.get("completed_at")
            part["last_gcode_file"] = data.get("gcode_file")
            matched = True
    if not matched and parts:
        artifact_matches = [part for part in parts
                            if current_artifact and Path(str(part.get("id") or "")).stem == current_artifact]
        if len(artifact_matches) == 1:
            part = artifact_matches[0]
            quantity = part.get("quantity", 1)
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
                quantity = 1
            already_completed = part.get("completed_quantity", 0)
            if isinstance(already_completed, bool) or not isinstance(already_completed, int):
                already_completed = 0
            part["quantity"] = quantity
            part["completed_quantity"] = min(quantity, max(0, already_completed) + completed_units)
            part["status"] = "completed" if part["completed_quantity"] >= quantity else "planned"
            part["completed_at"] = data.get("completed_at")
            part["last_gcode_file"] = data.get("gcode_file")
            matched = True
    if not matched and parts and len(parts) == 1:
        quantity = parts[0].get("quantity", 1)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            quantity = 1
        already_completed = parts[0].get("completed_quantity", 0)
        if isinstance(already_completed, bool) or not isinstance(already_completed, int):
            already_completed = 0
        parts[0]["quantity"] = quantity
        parts[0]["completed_quantity"] = min(quantity, max(0, already_completed) + completed_units)
        parts[0]["status"] = "completed" if parts[0]["completed_quantity"] >= quantity else "planned"
        parts[0]["completed_at"] = data.get("completed_at")
        parts[0]["last_gcode_file"] = data.get("gcode_file")
    _bind_same_job_plates(parts, data)
    payload = {
        "plan_id": plan_id,
        "source_url": data.get("source_url"),
        "source_platform": data.get("source_platform"),
        "updated_at": data.get("completed_at"),
        "parts": parts,
    }
    _atomic_write(json_path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    md_lines = ["# Print plan", "", f"Plan ID: `{plan_id}`", "", "| Part | Status | G-code |", "| --- | --- | --- |"]
    md_lines.extend(f"| {part.get('label', part.get('id'))} | {part.get('status', 'planned')} | {part.get('gcode_file', '')} |" for part in parts)
    _atomic_write(PLANS_DIR / f"{plan_id}.md", "\n".join(md_lines) + "\n")
    return plan_id, bool(parts) and all(part.get("status") == "completed" for part in parts)


def plan_is_complete(plan_id: str) -> bool:
    path = PLANS_DIR / f"{_safe_slug(plan_id)}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    parts = payload.get("parts") if isinstance(payload, dict) else None
    return bool(parts) and all(part.get("status") == "completed" for part in parts)


def write_completed_record(data: Mapping[str, Any]) -> dict[str, Any]:
    """Write one idempotent record and its multipart plan, then return cleanup facts."""
    plan_id, eligible = update_multipart_plan(data)
    record_key = f"{data.get('job_key') or data.get('completed_at')}:{data.get('gcode_file')}"
    digest = hashlib.sha256(record_key.encode("utf-8")).hexdigest()[:8]
    stamp = str(data.get("started_at") or data.get("completed_at") or utc_now())
    filename = f"{stamp.replace(':', '').replace('-', '')[:15]}-{_safe_slug(Path(str(data.get('gcode_file') or 'print')).stem)}-{digest}.md"
    path = PRINTS_DIR / filename
    started = Path(str(data.get("record_path") or ""))
    if data.get("record_path") and started.parent == PRINTS_DIR:
        path = started
    # A start note (status printing) is finalized in place; a final note is immutable.
    if not path.exists() or 'status: "printing"' in path.read_text(encoding="utf-8"):
        _atomic_write(path, _record_markdown(data))
    return {
        "record_path": str(path),
        "plan_id": plan_id,
        "cleanup_eligible": eligible,
        "discord_session_id": data.get("discord_session_id"),
        "discord_chat_id": data.get("discord_chat_id") or DEFAULT_CHAT_ID,
    }


def write_start_record(context: Mapping[str, Any]) -> str:
    """Create the in-progress note for a just-started print and return its path."""
    data = build_record_data(str(context["job_key"]), stats={"state": "printing"}, context=context)
    record_key = f"{data.get('job_key')}:{data.get('gcode_file')}"
    digest = hashlib.sha256(record_key.encode("utf-8")).hexdigest()[:8]
    stamp = str(data.get("started_at") or utc_now())
    path = PRINTS_DIR / f"{stamp.replace(':', '').replace('-', '')[:15]}-{_safe_slug(Path(str(data.get('gcode_file') or 'print')).stem)}-{digest}.md"
    # No multipart plan update here: a start must never mark a part complete.
    _atomic_write(path, _record_markdown(data))
    return str(path)


def update_cleanup_record(record_path: str, status: str, session_id: str | None = None, detail: str = "") -> None:
    path = Path(record_path)
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return
    marker = "## Session cleanup"
    prefix = content.split(marker, 1)[0].rstrip()
    section = [
        marker,
        "",
        f"- **Status:** {status}",
        f"- **Occurred at:** {utc_now() if status == 'archived' else 'not recorded'}",
        f"- **Session:** {session_id or 'not recorded'}",
        f"- **Detail:** {detail or 'not recorded'}",
        "",
    ]
    _atomic_write(path, prefix + "\n\n" + "\n".join(section))


def _profile_home() -> Path:
    # Pinned: HERMES_HOME in cron is the multiplex launch profile, not 3dprinting.
    return _config.pinned_hermes_home()


def discover_discord_session(chat_id: str, not_before: float | None = None, db_path: Path | None = None) -> tuple[str | None, str]:
    """Return one unarchived recent session, or an explicit ambiguity reason."""
    path = db_path or (_profile_home() / "state.db")
    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, started_at, last_activity_at FROM sessions "
                "WHERE source = 'discord' AND chat_id = ? AND archived = 0 "
                "AND (? IS NULL OR COALESCE(last_activity_at, started_at) >= ?) "
                "ORDER BY COALESCE(last_activity_at, started_at) DESC",
                (str(chat_id), not_before, not_before),
            ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        return None, f"session lookup failed: {exc}"
    if not rows:
        return None, "no unarchived Discord session matched the confirmed channel"
    if len(rows) > 1:
        return None, f"refusing cleanup because {len(rows)} unarchived sessions matched the channel"
    return str(rows[0]["id"]), "unique channel session matched"


def archive_discord_session(
    session_id: str,
    chat_id: str,
    *,
    dry_run: bool = False,
    db_path: Path | None = None,
) -> tuple[bool, str]:
    """Archive exactly one verified session through Hermes' SessionDB API.

    This is a reversible soft archive. It never deletes messages and refuses a
    session whose source or channel does not match the intended Discord route.
    """
    path = db_path or (_profile_home() / "state.db")
    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, source, chat_id, archived FROM sessions WHERE id = ?",
                (str(session_id),),
            ).fetchone()
            if row is None:
                return False, "session no longer exists"
            if row["source"] != "discord" or str(row["chat_id"]) != str(chat_id):
                return False, "session route did not match the confirmed Discord channel"
            if row["archived"]:
                return True, "session was already archived"
        if dry_run:
            return True, f"dry run would archive session {session_id}"
        _config.add_hermes_agent_to_path()
        from hermes_state import SessionDB  # type: ignore
        db = SessionDB(path)
        try:
            changed = bool(db.set_session_archived(str(session_id), True))
        finally:
            close = getattr(db, "close", None)
            if callable(close):
                close()
        return (changed, "session archived through SessionDB" if changed else "session archive made no change")
    except (OSError, sqlite3.Error, ImportError, RuntimeError) as exc:
        return False, f"session archive failed: {exc}"


def native_option_labels() -> tuple[str, str, str]:
    """Canonical Discord picker labels; callers must render these as buttons."""
    return NATIVE_PRINT_OPTIONS
