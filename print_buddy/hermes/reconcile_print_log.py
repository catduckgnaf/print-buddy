#!/usr/bin/env python3
"""Nightly print log catch up. Moonraker job history is the source of truth.

Any finished Moonraker job in the lookback window with no matching Obsidian print
note gets one written from history (start, end, duration, filament, outcome). A
note matches when gcode_file is the same and started_at is within 10 minutes.
No AI agent, no Discord posts. Prints one line per action; exit 1 on failure.
"""

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

from . import moonraker_discord_announcements as ann
from .print_records import PRINTS_DIR

# Moonraker history status -> Klipper print_stats state used by build_record_data.
STATUS = {"completed": "complete", "cancelled": "cancelled"}  # everything else is an error
FIELD = re.compile(r'^(gcode_file|started_at):\s*"?([^"\n]*)"?\s*$', re.M)


def existing_notes():
    notes = []
    for path in PRINTS_DIR.glob("*.md"):
        head = path.read_text(encoding="utf-8", errors="replace").split("\n---", 1)[0]
        fields = dict(FIELD.findall(head))
        try:
            started = datetime.strptime(fields.get("started_at", ""), "%Y-%m-%dT%H:%M:%SZ")
            started = started.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            started = None
        notes.append((Path(fields.get("gcode_file", "")).name, started))
    return notes


def has_note(notes, filename, start):
    name = Path(filename).name
    return any(n == name and (s is None or abs(s - start) <= 600) for n, s in notes)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=48)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    since = datetime.now(timezone.utc).timestamp() - args.hours * 3600
    try:
        result = ann.get_json(f"/server/history/list?limit=100&order=desc&since={since:.0f}")
    except Exception as exc:
        print(f"print log: Moonraker history unavailable: {exc}")
        return 1
    jobs = (result.get("result") or {}).get("jobs") or []
    notes = existing_notes()
    failed = 0
    for job in jobs:
        status, filename, start, end = job.get("status"), job.get("filename"), job.get("start_time"), job.get("end_time")
        if not filename or not start or status in (None, "in_progress") or has_note(notes, filename, start):
            continue
        if args.dry_run:
            print(f"print log: would add {filename} ({status}) started {iso(start)}")
            continue
        stats = {"state": STATUS.get(status, "error"), "print_duration": job.get("print_duration"),
                 "filament_used": job.get("filament_used")}
        ctx = ann.load_context(filename)
        ctx.setdefault("started_at", iso(start))
        try:
            data = ann.build_record_data(filename, stats=stats, metadata={}, context=ctx,
                                         completed_at=iso(end) if end else None)
            data["moonraker_state"] = status
            path = ann.write_completed_record(data).get("record_path")
            notes.append((Path(filename).name, start))
            print(f"print log: added missing note for {filename} ({status}) -> {path}")
        except Exception as exc:
            failed += 1
            print(f"print log: could not write note for {filename} ({status}): {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
