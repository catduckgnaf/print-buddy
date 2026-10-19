#!/usr/bin/env python3
"""Deterministic Discord presentation contract shared with HA owner.

Every print message (post slice summary, start, complete, cancel, failure) is rendered
here from JOB.json and G-code metadata. Hashes and file names stay internal.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import _config

_HASH = re.compile(r"[0-9a-f]{32,}", re.I)
_TIME = re.compile(r"^; estimated printing time \(normal mode\) = (.+)$", re.M)
ARCHIVE = _config.archive_dir()
CONTEXT_PATH = _config.state_file("PRINT_BITCH_CONTEXT_PATH", "print_bitch_context.json")
WARMUP_S = 5 * 60
ET = _config.tz()  # the configured display timezone (discord.timezone); the name is historical
VERBS = {"started": "Print started", "slice": "Print preparing", "complete": "Print complete", "cancelled": "Print cancelled",
         "error": "Print stopped with an error", "paused": "Print paused"}


def scrub(text):
    """Last line of defence: no hex run of 32+ characters ever reaches Discord."""
    return _HASH.sub("", str(text))


def safe_label(value, fallback="Print"):
    text = Path(str(value or "")).name
    text = re.sub(r"\.(?:gcode|3mf|stl|json)$", "", text, flags=re.I)
    text = re.sub(r"[_-]?[0-9a-f]{32,}", "", text, flags=re.I).replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip(" .-/\\")
    return text or fallback


def parse_duration(text):
    """'1d 2h 3m 4s' -> seconds, or None."""
    if not text:
        return None
    found = re.findall(r"(\d+)\s*([dhms])", str(text))
    if not found:
        return None
    mult = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(int(n) * mult[u] for n, u in found)


def human(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m}m" if h else f"{m}m"


def finish_text(seconds, now=None):
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return None
    now = now or datetime.now(ET)
    return (now + timedelta(seconds=seconds + WARMUP_S)).strftime("%-I:%M %p %a ") + _config.tz_label(now)


def gcode_metadata(gcode):
    try:
        with open(gcode, errors="ignore") as handle:
            text = handle.read()
    except OSError:
        return None, None
    match = _TIME.search(text)
    filament = re.search(r"^;\s*total filament used \[g\]\s*=\s*([\d.]+)", text, re.M)
    return (parse_duration(match.group(1)) if match else None,
            float(filament.group(1)) if filament else None)


def gcode_seconds(gcode):
    return gcode_metadata(gcode)[0]


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _part_names(job, keys=None):
    names = []
    for part in (job.get("color_manifest") or {}).get("parts") or []:
        if keys is not None and part.get("key") not in keys:
            continue
        name = re.sub(r"\.(stl|3mf|obj|step|stp)$", "", safe_label(part.get("name"), ""), flags=re.I)
        if name:
            names.append(name)
    counts = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return [f"{n}× {name}" if n > 1 else name for name, n in counts.items()]


def _filament(job, keys=None, slot=None):
    """(slot, color, material) from the saved decisions; None fields when unknown."""
    dec = job.get("color_decisions") or {}
    sel = job.get("filament_selection") or dec.get("selection")
    if not sel and isinstance(dec.get("choices"), dict):
        pool = [v for k, v in dec["choices"].items() if keys is None or k in keys] or list(dec["choices"].values())
        sel = next((v for v in pool if slot is None or v.get("slot") == slot), None) or (pool[0] if pool else None)
    sel = sel or {}
    return sel.get("slot", slot), sel.get("color"), sel.get("material")


def plates_of(job):
    """One dict per sliced plate: gcode, parts, slot, color, material, seconds, plate_id."""
    rows = []
    derived = job.get("derived_plates") or []
    for row in derived:
        slot, color, material = _filament(job, set(row.get("part_keys") or []), row.get("slot"))
        rows.append({"gcode": row.get("gcode"), "plate": row.get("plate_id"),
                     "parts": _part_names(job, set(row.get("part_keys") or [])),
                     "slot": slot, "color": color, "material": material})
    if not rows and job.get("gcode"):
        slot, color, material = _filament(job)
        rows.append({"gcode": job["gcode"], "plate": None, "parts": _part_names(job),
                     "slot": slot, "color": color, "material": material})
    for row in rows:
        row["seconds"], row["filament_g"] = gcode_metadata(row["gcode"]) if row.get("gcode") else (None, None)
    return rows


def _title(job):
    if job.get("title"):
        return safe_label(job["title"])
    return safe_label(Path(str(job.get("downloaded_file") or "")).stem, "Print")


def _job_files(archive):
    for path in sorted(Path(archive).glob("*/JOB.json")):
        try:
            yield path, {**json.loads(path.read_text()), '_job_path': str(path.resolve())}
        except (OSError, ValueError):
            continue


def find_job(filename, archive=None, context_path=None):
    """Resolve a Moonraker filename to (job dict or None, plate row or None).

    Order: the start-time context sidecar (written by record_start), then JOB.json lookup by
    G-code name. Moonraker names are '<stem>_<sha256>.gcode'; the stem is the local file stem.
    """
    name = Path(str(filename or "")).name
    if not name:
        return None, None
    archive = Path(archive) if archive else ARCHIVE
    original_path = Path(str(filename or "")).expanduser()
    requested_is_path = original_path.is_absolute()
    requested_path = original_path
    try:
        requested_path = requested_path.resolve()
    except OSError:
        pass
    for path, job in _job_files(archive):
        candidates = [(None, job.get("gcode"))] + [(row, row.get("gcode")) for row in job.get("derived_plates") or []]
        for row, gcode in candidates:
            if not gcode:
                continue
            local = Path(gcode)
            hit = local.name == name
            if requested_is_path:
                try:
                    hit = local.resolve() == requested_path
                except OSError:
                    hit = False
            if not hit and local.is_file():
                # model_job.remote_name: optional "<Title>_" prefix, the plate stem, then the full SHA256.
                m = re.fullmatch(rf"(?:.+_)?{re.escape(local.stem)}_([0-9a-f]{{64}}){re.escape(local.suffix)}", name)
                hit = bool(m) and _sha256(local) == m[1]
            if hit:
                plate = next((p for p in plates_of(job) if p.get("gcode") == gcode), None)
                return job, plate
    try:
        ctx = json.loads(Path(context_path or CONTEXT_PATH).read_text())
        entry = (ctx.get("jobs") or {}).get(name)
        if isinstance(entry, dict) and entry.get("title"):
            sl = entry.get("slicer_settings") or {}
            spool = entry.get("active_spool") or {}
            job = {"title": entry["title"], "gcode": sl.get("local_gcode")}
            plate = {"gcode": sl.get("local_gcode"), "plate": None, "parts": [],
                     "slot": None, "color": spool.get("color"), "material": spool.get("material"),
                     "seconds": parse_duration(entry.get("estimated_time"))}
            return job, plate
    except (OSError, ValueError, AttributeError):
        pass
    return None, None


def _print_number(job):
    """Read the permanent job number without assigning one from a listener render."""
    path = job.get('_job_path') if isinstance(job, dict) else None
    if not path:
        return None
    try:
        from . import print_control
        numbers = json.loads(print_control.PRINT_NUMBERS.read_text(encoding='utf-8')).get('numbers') or {}
        number = numbers.get(str(Path(path).resolve()))
        return int(number) if isinstance(number, int) and not isinstance(number, bool) and number > 0 else None
    except (OSError, ValueError, AttributeError, ImportError):
        return None


def format_confirmed_print(*, model, parts=(), plate=None, slot=None, color=None, material=None,
                           filament_g=None, seconds=None, finish=None, kind="started", plates_total=None,
                           print_number=None):
    """Human readable, hash free message for one print event."""
    details = [f"{VERBS.get(kind, VERBS['started'])}: {safe_label(model)}"]
    if print_number:
        details.append(f"Print #{print_number}")
    pieces = [safe_label(part) for part in parts if str(part or "").strip()]
    if pieces:
        details.append("Parts: " + ", ".join(pieces))
    if plate is not None:
        details.append(f"Plate {plate}" + (f" of {plates_total}" if plates_total and plates_total > 1 else ""))
    if slot is not None or color or material:
        prefix = f"Slot {slot}: " if slot is not None else "Filament: "
        details.append(prefix + f"{safe_label(color, 'color unknown')} {safe_label(material, 'material unknown')}")
    if filament_g is not None:
        details.append(f"Filament: {filament_g:g} g")
    if kind in ("started", "slice"):
        details.append(f"Estimated total: ~{human(seconds + WARMUP_S)} (printing: {human(seconds)})"
                       if isinstance(seconds, (int, float)) and seconds >= 0 else "Estimated total: unknown")
        if finish:
            details.append(f"Approx. finish: {finish}")
    return scrub("\n".join(details))


def plate_payload(kind, filename, archive=None, context_path=None):
    """Sanitized structured equivalent of the native plate line for HA consumers."""
    job, plate = find_job(filename, archive, context_path)
    if not job:
        return None
    row = plate or {}
    return {
        "model": _title(job),
        "plate": row.get("plate"),
        "parts": list(row.get("parts") or []),
        "slot": row.get("slot"),
        "color": safe_label(row.get("color"), "") or None,
        "material": safe_label(row.get("material"), "") or None,
        "filament_g": row.get("filament_g"),
        "estimated_seconds": row.get("seconds"),
    }


def format_preparation(job, plate=None):
    """Exact bound job/plate summary used before starting; never re-resolves a filename."""
    row = plate or {}
    return format_confirmed_print(
        model=_title(job or {}), parts=row.get("parts") or (), plate=row.get("plate"),
        slot=row.get("slot"), color=row.get("color"), material=row.get("material"),
        filament_g=row.get("filament_g"), seconds=row.get("seconds"), kind="slice",
        plates_total=len((job or {}).get("derived_plates") or []) or None,
        print_number=_print_number(job or {}))


def format_started(job, plate=None, now=None):
    """Exact bound start summary, avoiding another filename lookup after approval."""
    row = plate or {}
    seconds = row.get("seconds")
    return format_confirmed_print(
        model=_title(job or {}), parts=row.get("parts") or (), plate=row.get("plate"),
        slot=row.get("slot"), color=row.get("color"), material=row.get("material"),
        filament_g=row.get("filament_g"), seconds=seconds,
        finish=finish_text(seconds, now), kind="started",
        plates_total=len((job or {}).get("derived_plates") or []) or None,
        print_number=_print_number(job or {}))


def format_event(kind, filename, now=None, archive=None, context_path=None, extra=None):
    """Message for a Moonraker event on `filename`. Falls back to a scrubbed file label."""
    job, plate = find_job(filename, archive, context_path)
    if not job:
        message = f"{VERBS.get(kind, VERBS['started'])}: {safe_label(filename)}"
    else:
        seconds = (plate or {}).get("seconds")
        total = len(job.get("derived_plates") or []) or None
        message = format_confirmed_print(
            model=_title(job), parts=(plate or {}).get("parts") or (), plate=(plate or {}).get("plate"),
            slot=(plate or {}).get("slot"), color=(plate or {}).get("color"),
            material=(plate or {}).get("material"), filament_g=(plate or {}).get("filament_g"),
            seconds=seconds, finish=finish_text(seconds, now) if kind == "started" else None,
            kind=kind, plates_total=total, print_number=_print_number(job))
    if extra:
        message += "\n" + scrub(extra)
    return scrub(message)


def format_slice_summary(job, now=None):
    """Post slice summary straight from JOB.json: model, parts per plate, filament, estimates."""
    rows = plates_of(job)
    lines = [f"Sliced: {_title(job)}"]
    total = 0
    total_filament = 0.0
    filament_known = True
    known = True
    for row in rows:
        label = f"Plate {row['plate']}" if row.get("plate") is not None else "Plate"
        parts = ", ".join(row["parts"]) or "all parts"
        slot = f"slot {row['slot']}" if row.get("slot") is not None else "slot unknown"
        fil = f"{safe_label(row['color'], 'color unknown')} {safe_label(row['material'], 'material unknown')}, {slot}"
        est = human(row["seconds"]) if row.get("seconds") is not None else "estimate unknown"
        grams = row.get("filament_g")
        amount = f" | {grams:g} g" if grams is not None else ""
        lines.append(f"{label}: {parts} | {fil}{amount} | {est}")
        if grams is None:
            filament_known = False
        else:
            total_filament += grams
        if row.get("seconds") is None:
            known = False
        else:
            total += row["seconds"]
    if rows and filament_known:
        lines.append(f"Total filament: {total_filament:g} g")
    if rows and known:
        lines.append(f"Estimated total: ~{human(total + WARMUP_S)} (printing: {human(total)})")
        lines.append(f"Approx. finish if started now: {finish_text(total, now)}")
    auto_scale = job.get('auto_scale')
    if isinstance(auto_scale, dict):
        original = auto_scale.get('original_mm') or ()
        final = auto_scale.get('final_mm') or ()
        if len(original) == 3 and len(final) == 3:
            original_text = ' x '.join(f'{float(value):g}' for value in original)
            final_text = ' x '.join(f'{float(value):g}' for value in final)
            lines.append(f'Auto-scale: {original_text} mm treated as inches, scaled 25.4x -> {final_text} mm')
    return scrub("\n".join(lines))
