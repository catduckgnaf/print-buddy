import importlib.util
import json
import sqlite3

import pytest
import sys
from pathlib import Path

from print_buddy.hermes import print_records as records
from print_buddy.hermes import moonraker_discord_announcements as watcher


def test_batch_copy_and_multipart_guards(monkeypatch, tmp_path):
    monkeypatch.setattr(watcher, "plan_is_complete", lambda value: value == "done")
    monkeypatch.setattr(watcher, "_queued_jobs", lambda: [])
    assert watcher._batch_fully_complete({"total_copies": 3, "copy_index": 1}) is False
    assert watcher._batch_fully_complete({"total_copies": 3, "copy_index": 3, "multipart_plan_id": "pending"}) is False
    assert watcher._batch_fully_complete({"total_copies": 3, "copy_index": 3, "multipart_plan_id": "done"}) is True
    monkeypatch.setattr(watcher, "_queued_jobs", lambda: [{"job_id": "next"}])
    assert watcher._batch_fully_complete({"total_copies": 1, "copy_index": 1}) is False


@pytest.mark.usefixtures("hermes_agent")
def test_silent_reset_promotes_session_without_gateway_reply(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, chat_id TEXT, archived INTEGER, started_at REAL, last_activity_at REAL, ended_at REAL, end_reason TEXT, parent_session_id TEXT, reset_generation INTEGER DEFAULT 0)")
        conn.execute("INSERT INTO sessions (id, source, chat_id, archived, started_at, last_activity_at, ended_at, end_reason) VALUES ('s1', 'discord', '100000000000000001', 0, 1, 2, NULL, NULL)")
        conn.commit()
    monkeypatch.setattr(watcher, "PROFILE_HOME", tmp_path)
    ok, detail = watcher.silently_reset_discord_session("100000000000000001", "s1")
    assert ok is True
    assert "silently" in detail
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT end_reason FROM sessions WHERE id='s1'").fetchone()[0] == "print_complete_auto_reset"

def test_record_keeps_unavailable_values_blank():
    data = records.build_record_data(
        "part.gcode",
        stats={"state": "complete", "print_duration": 42.0},
        metadata={},
        context={"selected_option": records.NATIVE_PRINT_OPTIONS[0]},
    )
    assert data["print_duration_seconds"] == 42.0
    assert data["source_url"] is None
    assert data["author_directed_tree_supports"] is None
    assert data["spoolman_spool_id"] is None


def test_multipart_summary_tracks_multiple_parts_shared_plates_runs_and_estimates():
    summary = records.format_multipart_summary({"parts": [
        {"id": "frame", "label": "Frame", "status": "completed", "quantity": 1,
         "run_id": 1, "plate_id": 1, "gcode_file": "Frame.gcode", "last_gcode_file": "Frame.gcode"},
        {"id": "clip", "label": "Clip", "quantity": 3, "completed_quantity": 0,
         "run_id": 1, "plate_id": 1, "estimated_part_seconds": 3600},
        {"id": "lid", "label": "Lid", "quantity": 1, "completed_quantity": 0,
         "run_id": 2, "plate_id": 1, "plate_estimate_seconds": 3600, "gcode_file": "lid-next.gcode"},
        {"id": "case", "label": "Case", "quantity": 2, "completed_quantity": 0,
         "run_id": 2, "plate_id": 1, "plate_estimate_seconds": 3600},
        {"id": "base", "label": "Base", "quantity": 1, "completed_quantity": 0, "run_id": 3, "plate_id": 1},
        {"id": "blue", "label": "Blue variant", "optional": True},
        {"id": "red", "label": "Red variant", "alternative_group": "color", "selected": False},
    ]}, "Frame.gcode")
    assert "Current print finished: Frame" in summary
    assert "Current plate/run finished: Run 1, Plate 1" in summary
    assert "Remove the finished pieces and clear the bed before the next plate." in summary
    assert "Next required part: Clip" in summary
    assert "Clip: 3 remaining; per-part estimate ~1h 0m" in summary
    assert "Lid: 1 remaining" in summary and "Run 2, Plate 1" in summary
    assert "Case: 2 remaining" in summary
    assert "shared plate estimate ~1h 0m; these pieces share the plate" in summary
    assert "All remaining required parts" in summary and "Base: 1 remaining" in summary
    assert "Combined remaining duration incomplete" in summary
    assert "Blue variant (optional)" in summary and "Red variant (alternative set color)" in summary
    assert "exact next artifact: lid-next.gcode" not in summary
    assert "Start option:" not in summary


def test_multipart_summary_allows_exact_next_artifact_and_empty_remainder():
    summary = records.format_multipart_summary({"parts": [
        {"id": "done", "label": "Finished widget", "status": "completed", "quantity": 2},
        {"id": "next", "label": "Next widget", "quantity": 1, "gcode_file": "next-widget.gcode",
         "plate_id": 3, "run_id": 2, "estimated_part_seconds": 1800},
    ]})
    assert "Start option: Start next plate · bed is clear; require a fresh confirmation for this exact artifact. No automatic advance." in summary
    assert "Combined remaining duration: ~0h 30m" in summary
    complete = records.format_multipart_summary({"parts": [
        {"id": "only", "label": "Only part", "status": "completed", "quantity": 1, "gcode_file": "only.gcode"},
    ]}, "only.gcode")
    assert "Remaining required parts: none. Job complete." in complete
    assert "Start option:" not in complete


def test_multipart_summary_tracks_current_plate_and_sanitized_remaining_plan():
    summary = records.format_multipart_summary({"parts": [
        {"id": "frame", "label": "Frame", "status": "completed", "quantity": 1,
         "run_id": 1, "plate_id": 1, "gcode_file": "frame.gcode", "last_gcode_file": "frame.gcode"},
        {"id": "clip", "label": "Clip", "quantity": 2, "completed_quantity": 0,
         "run_id": 2, "plate_id": 3, "plate_estimate_seconds": 1800, "gcode_file": "private/clip-deadbeef.gcode"},
        {"id": "lid", "label": "Lid", "quantity": 1, "completed_quantity": 0,
         "run_id": 3, "plate_id": 4, "gcode_file": "private/lid.gcode"},
    ]}, "frame.gcode")
    assert "Current print finished: Frame" in summary
    assert "Current plate/run finished: Run 1, Plate 1" in summary
    assert "Remove the finished pieces and clear the bed before the next plate." in summary
    assert "Next required part: Clip (Run 2, Plate 3)" in summary
    assert "Start option:" not in summary
    assert "Clip: 2 remaining" in summary and "Lid: 1 remaining" in summary
    assert "Combined remaining duration incomplete" in summary
    assert "deadbeef" not in summary


def test_multipart_plan_defers_until_every_part(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "PLANS_DIR", tmp_path / "Plans")
    monkeypatch.setattr(records, "PRINTS_DIR", tmp_path / "Prints")
    base = {
        "completed_at": "2026-09-20T15:00:00Z",
        "gcode_file": "part-a.gcode",
        "multipart_plan_id": "dragon",
        "part_id": "a",
        "required_parts": ["a", "b"],
        "status": "completed",
    }
    first = records.write_completed_record(base)
    assert first["cleanup_eligible"] is False
    plan = json.loads((tmp_path / "Plans" / "dragon.json").read_text())
    assert {part["status"] for part in plan["parts"]} == {"completed", "planned"}
    assert [(part["id"], part["completed_quantity"]) for part in plan["parts"]] == [("a", 1), ("b", 0)]
    again = records.write_completed_record(dict(base, gcode_file="a.gcode", part_id=None))
    assert again["cleanup_eligible"] is False
    plan = json.loads((tmp_path / "Plans" / "dragon.json").read_text())
    assert [(part["id"], part["completed_quantity"]) for part in plan["parts"]] == [("a", 1), ("b", 0)]


def test_archive_dry_run_targets_one_verified_session(tmp_path):
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, chat_id TEXT, archived INTEGER, started_at REAL, last_activity_at REAL)")
        conn.execute("INSERT INTO sessions VALUES ('s1', 'discord', '100000000000000001', 0, 1, 2)")
        conn.execute("INSERT INTO sessions VALUES ('other', 'discord', 'different', 0, 1, 2)")
        conn.commit()
    matched, reason = records.discover_discord_session("100000000000000001", db_path=db_path)
    assert matched == "s1"
    assert "matched" in reason
    ok, reason = records.archive_discord_session("s1", "100000000000000001", dry_run=True, db_path=db_path)
    assert ok is True
    assert "dry run" in reason
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT archived FROM sessions WHERE id = 's1'").fetchone()[0] == 0


def test_archive_refuses_ambiguous_channel(tmp_path):
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, chat_id TEXT, archived INTEGER, started_at REAL, last_activity_at REAL)")
        conn.executemany(
            "INSERT INTO sessions VALUES (?, 'discord', '100000000000000001', 0, 1, ?)",
            [("s1", 2), ("s2", 3)],
        )
        conn.commit()
    matched, reason = records.discover_discord_session("100000000000000001", db_path=db_path)
    assert matched is None
    assert "refusing cleanup" in reason


def test_watcher_records_mocked_moonraker_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "PRINTS_DIR", tmp_path / "Prints")
    monkeypatch.setattr(records, "PLANS_DIR", tmp_path / "Plans")
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watcher, "PROFILE_HOME", tmp_path / "profile")
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps({"jobs": {"part.gcode": {
        "selected_option": records.NATIVE_PRINT_OPTIONS[0],
        "discord_session_id": "session-1",
        "discord_chat_id": "100000000000000001",
    }}}))
    monkeypatch.setenv("PRINT_BITCH_CONTEXT_PATH", str(context_path))
    responses = iter((
        {"job": {"file": {"path": "part.gcode", "display": "part.gcode"}}, "progress": {"completion": 25}, "state": "Printing", "stats": {"state": "printing"}},
        {"job": {"file": {"path": "part.gcode", "display": "part.gcode"}}, "progress": {"completion": 100}, "state": "Completed", "stats": {"state": "complete", "print_duration": 30}},
    ))
    monkeypatch.setattr(watcher, "get_job", lambda: next(responses))
    monkeypatch.setattr(watcher, "get_file_metadata", lambda filename: {"slicer_settings": {"layer_height": 0.2}})
    monkeypatch.setattr(watcher, "get_active_spool", lambda: {})
    assert watcher.main() == 0
    assert watcher.main() == 0
    assert len(list((tmp_path / "Prints").glob("*.md"))) == 1
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["record_written"] is True
    assert state["pending_cleanups"][0]["cleanup_due_at"] > 0

def _session_db(tmp_path, rows):
    db_path = tmp_path / "state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, chat_id TEXT, archived INTEGER, started_at REAL, last_activity_at REAL, ended_at REAL, end_reason TEXT, parent_session_id TEXT, reset_generation INTEGER DEFAULT 0)")
        for sid, archived, act in rows:
            conn.execute("INSERT INTO sessions (id, source, chat_id, archived, started_at, last_activity_at) VALUES (?, 'discord', '100000000000000001', ?, 1000, ?)", (sid, archived, act))
        conn.commit()
    return db_path


def _reasons(db_path):
    with sqlite3.connect(db_path) as conn:
        return dict(conn.execute("SELECT id, end_reason FROM sessions").fetchall())


def _patch_idle(monkeypatch, tmp_path, now, plans=()):
    monkeypatch.setattr(watcher, "PROFILE_HOME", tmp_path)
    monkeypatch.setattr(watcher, "_queued_jobs", lambda: [])
    monkeypatch.setattr(watcher, "_open_multipart_plans", lambda: set(plans))
    monkeypatch.setattr(watcher, "_daily_boundary_epoch", lambda now=None: 50_000.0)
    monkeypatch.setattr("time.time", lambda: now)


@pytest.mark.usefixtures("hermes_agent")
def test_post_print_quiet_reset_after_two_hours(tmp_path, monkeypatch):
    now = 100_000.0
    db = _session_db(tmp_path, [("quiet", 0, now - 7300), ("chatty", 0, now - 60)])
    _patch_idle(monkeypatch, tmp_path, now)
    ok, detail, disarm = watcher.check_and_reset_idle_discord_session(armed_at=now - 7300)
    assert ok is True and disarm is True and "post_print=1" in detail
    assert _reasons(db) == {"quiet": "post_print_2h_quiet_reset", "chatty": None}


def test_quiet_timer_does_not_fire_early_or_when_unarmed(tmp_path, monkeypatch):
    now = 100_000.0
    db = _session_db(tmp_path, [("s", 0, now - 3600)])
    _patch_idle(monkeypatch, tmp_path, now)
    assert watcher.check_and_reset_idle_discord_session(armed_at=now - 3600)[0] is False
    assert watcher.check_and_reset_idle_discord_session(armed_at=None)[0] is False
    assert _reasons(db) == {"s": None}


@pytest.mark.usefixtures("hermes_agent")
def test_daily_4am_backup_resets_archived_and_every_stale_session(tmp_path, monkeypatch):
    """Regression: an auto-archived live session escaped reset for 16 days. The 4 AM
    backup must end every unended row whose last activity predates the boundary."""
    now = 100_000.0
    db = _session_db(tmp_path, [("old_archived", 1, 1000.0), ("fresh_user2", 0, now - 60)])
    _patch_idle(monkeypatch, tmp_path, now)
    ok, detail, _ = watcher.check_and_reset_idle_discord_session(armed_at=None)
    assert ok is True and "daily=1" in detail
    assert _reasons(db) == {"old_archived": "daily_4am_backup_reset", "fresh_user2": None}


def test_open_multipart_plan_blocks_every_reset(tmp_path, monkeypatch):
    now = 100_000.0
    db = _session_db(tmp_path, [("s", 0, 1000.0)])
    _patch_idle(monkeypatch, tmp_path, now, plans=["desk-organizer"])
    ok, detail, disarm = watcher.check_and_reset_idle_discord_session(armed_at=1000.0)
    assert ok is False and disarm is False and "desk-organizer" in detail
    assert _reasons(db) == {"s": None}


def test_start_note_then_cancel_finalizes_same_dated_note(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "PRINTS_DIR", tmp_path / "Prints")
    monkeypatch.setattr(records, "PLANS_DIR", tmp_path / "Plans")
    ctx = {"job_key": "stand.gcode", "title": "Stand", "started_at": "2026-09-24T03:30:00Z",
           "hardware": "0.6 mm ruby", "estimated_time": "17h 56m", "filament_diameter_mm": 1.75, "filament_density": 1.24}
    path = records.write_start_record(ctx)
    text = open(path).read()
    assert 'status: "printing"' in text and "2026-09-23 11:30 PM EDT" in text and "in progress" in text
    assert not (tmp_path / "Plans").exists()
    data = records.build_record_data("stand.gcode", stats={"state": "cancelled", "print_duration": 3600, "filament_used": 1000},
                                     context={**ctx, "record_path": path}, completed_at="2026-09-24T04:30:00Z")
    result = records.write_completed_record(data)
    assert result["record_path"] == path and len(list((tmp_path / "Prints").glob("*.md"))) == 1
    final = open(path).read()
    assert 'status: "cancelled"' in final and "success: false" in final and "1h 0m" in final and "Used filament (g):** 3.0" in final
    records.write_completed_record(records.build_record_data("stand.gcode", stats={"state": "complete"}, context={**ctx, "record_path": path}))
    assert open(path).read() == final  # finalized notes are immutable


def test_cancel_to_standby_finalizes_note_from_history(tmp_path, monkeypatch):
    """Klipper drops to standby with an empty filename on cancel; the note must still close."""
    monkeypatch.setattr(records, "PRINTS_DIR", tmp_path / "Prints")
    monkeypatch.setattr(watcher, "STATE_PATH", tmp_path / "state.json")
    ctx = {"job_key": "stand.gcode", "title": "Stand", "started_at": "2026-09-24T03:31:54Z",
           "filament_diameter_mm": 1.75, "filament_density": 1.24}
    ctx["record_path"] = records.write_start_record(ctx)
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps({"jobs": {"stand.gcode": ctx}}))
    monkeypatch.setenv("PRINT_BITCH_CONTEXT_PATH", str(context_path))
    responses = iter((
        {"job": {"file": {"path": "stand.gcode", "display": "stand.gcode"}}, "progress": {"completion": 0.4}, "state": "Printing", "stats": {"state": "printing"}},
        {"job": {"file": {"path": "stand.gcode", "display": "stand.gcode"}}, "progress": {"completion": 0.4}, "state": "Printing", "stats": {"state": "printing"}},
        {"job": {"file": {"name": None}}, "progress": {"completion": None}, "state": "Operational", "stats": {"state": "standby"}},
    ))
    monkeypatch.setattr(watcher, "get_job", lambda: next(responses))
    history = {"result": {"jobs": [{"filename": "stand.gcode", "status": "cancelled", "print_duration": 790,
                                    "filament_used": 478.5, "end_time": 1790221997}]}}
    monkeypatch.setattr(watcher, "get_json", lambda path: history if path.startswith("/server/history") else {})
    monkeypatch.setattr(watcher, "get_active_spool", lambda: {})
    monkeypatch.setattr(watcher, "get_file_metadata", lambda filename: {})
    monkeypatch.setattr(watcher, "process_pending_cleanups", lambda state, now=None: state)
    monkeypatch.setattr(watcher, "check_and_reset_idle_discord_session", lambda *a, **k: (False, ""))
    for _ in range(3):
        assert watcher.main() == 0
    final = open(ctx["record_path"]).read()
    assert 'status: "cancelled"' in final and "success: false" in final and "0h 13m" in final
    assert "2026-09-23 11:53 PM EDT" in final and len(list((tmp_path / "Prints").glob("*.md"))) == 1
