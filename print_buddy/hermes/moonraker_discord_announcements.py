#!/usr/bin/env python3
"""Emit one Discord announcement on print completion."""

from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import _config
from . import discord_print_summary as print_summary

OPENVIKING_URL = _config.service_url("openviking_url")


def _profile_env_value(name):
    """Read ONE key from the profile .env (the systemd unit loads no EnvironmentFile)."""
    env_path = _config.hermes_home() / ".env"
    try:
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


OPENVIKING_API_KEY = os.environ.get("OPENVIKING_API_KEY") or _profile_env_value("OPENVIKING_API_KEY")
OPENVIKING_VERIFY_TIMEOUT = float(os.environ.get("OPENVIKING_VERIFY_TIMEOUT", "15"))
DISCORD_CHAT_ID = _config.discord_chat_id()

from .print_records import (
    CLEANUP_DELAY_SECONDS,
    archive_discord_session,
    build_record_data,
    discover_discord_session,
    load_context,
    plan_is_complete,
    update_cleanup_record,
    utc_now,
    write_completed_record,
    format_multipart_summary,
    remaining_plate_choices,
    PLANS_DIR,
    _safe_slug,
)

# Stdout line telling the listener to post the interactive plate picker for this plan after the completion post.
PLATE_PICKER_MARKER = "PLATE_PICKER:"

BASE = _config.moonraker_url()
SPOOLMAN_BASE = _config.service_url("spoolman_url")
API_KEY = os.environ.get("MOONRAKER_API_KEY", "")
STATE_PATH = _config.state_file("MOONRAKER_ANNOUNCEMENT_STATE", "moonraker_discord_announcements.json")
MEDIA_DIR = _config.cache_dir() / "moonraker-announcements"
# Remote timelapse archive over ssh. An empty host turns the archive (and the posted video) off.
# The ssh login comes from ~/.ssh/config for that host. Some NAS hosts drop scp, so transfers stream over ssh.
_TIMELAPSE = _config.cfg()["timelapse"]
TIMELAPSE_ARCHIVE_HOST = str(_TIMELAPSE["archive_host"])
TIMELAPSE_ARCHIVE_DIR = str(_TIMELAPSE["archive_dir"])
TIMELAPSE_SSH_KEY = str(_TIMELAPSE["ssh_key"])
TIMELAPSE_RENDER_WAIT_SECONDS = float(_TIMELAPSE["render_wait_s"])
TIMELAPSE_RENDER_POLL_SECONDS = float(_TIMELAPSE["render_poll_s"])
TIMELAPSE_MAX_BYTES = int(_TIMELAPSE["max_bytes"])
TIMELAPSE_LOCAL_RETENTION_DAYS = float(_TIMELAPSE["local_retention_days"])
ACTIVE_STATES = {"Printing", "Paused", "Pausing", "Resuming"}
# Pinned to the print profile from config. The multiplex gateway exports the launching profile's
# HERMES_HOME to cron scripts, which silently pointed every session reset at the wrong state.db.
PROFILE_HOME = _config.pinned_hermes_home()


def _context_value(context, *keys):
    """Read batch metadata from flat or nested print context."""
    sources = [context] if isinstance(context, dict) else []
    if isinstance(context, dict):
        sources.extend(value for key in ("batch", "job", "print", "copies")
                       if isinstance(value := context.get(key), dict))
    for source in sources:
        for key in keys:
            if source.get(key) is not None:
                return source[key]
    return None


def _queued_jobs():
    """Return Moonraker's queue; unavailable status fails closed."""
    try:
        result = get_json("/server/job_queue/status").get("result") or {}
        return result.get("queued_jobs") or result.get("queue") or []
    except Exception as exc:
        print(f"Print queue status unavailable: {exc}", file=sys.stderr)
        return None


def _batch_fully_complete(context):
    """Only reset after all copies and multipart steps are complete."""
    total = _context_value(context, "total_copies", "copies", "copy_count", "batch_size")
    index = _context_value(context, "copy_index", "copy_number", "batch_index")
    try:
        if total is not None and int(total) > 0 and index is not None and int(index) < int(total):
            return False
    except (TypeError, ValueError):
        return False
    plan_id = _context_value(context, "multipart_plan_id", "plan_id")
    if plan_id and not plan_is_complete(str(plan_id)):
        return False
    return _queued_jobs() == []


def _openviking_request(method, path, payload=None, timeout=10):
    headers = {"Accept": "application/json"}
    if OPENVIKING_API_KEY:
        # OpenViking's authenticated client sends both forms on every request.
        headers["X-API-Key"] = OPENVIKING_API_KEY
        headers["Authorization"] = f"Bearer {OPENVIKING_API_KEY}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{_config.require(OPENVIKING_URL, 'services.openviking_url')}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def write_and_verify_print_memory(filename, stats, context):
    """Write the durable print line and require verified memory_diff output."""
    spool = context.get("active_spool") if isinstance(context, dict) else {}
    spool = spool if isinstance(spool, dict) else {}
    filament_data = spool.get("filament") if isinstance(spool.get("filament"), dict) else {}
    filament = " ".join(str(value).strip() for value in (
        spool.get("vendor") or filament_data.get("vendor"),
        spool.get("material") or filament_data.get("material"),
        spool.get("color") or filament_data.get("color"),
    ) if value).strip()
    filament = filament or str(spool.get("name") or "filament not recorded")
    used = stats.get("filament_used") if isinstance(stats, dict) else None
    line = f"Print {Path(str(filename)).stem}: success; filament {filament}; used {used if used is not None else 'not recorded'} mm; date {utc_now().split('T', 1)[0]}."
    sid = f"hermes-remember-print-{hashlib.sha256(line.encode()).hexdigest()[:16]}"
    try:
        _openviking_request("POST", f"/api/v1/sessions/{sid}/messages", {"role": "user", "parts": [{"type": "text", "text": line}]})
        _openviking_request("POST", f"/api/v1/sessions/{sid}/commit", {"keep_recent_count": 0})
        deadline = time.time() + OPENVIKING_VERIFY_TIMEOUT
        while time.time() < deadline:
            listing = _openviking_request("GET", f"/api/v1/fs/ls?uri=viking://user/hermes/sessions/{sid}", timeout=5)
            if "memory_diff.json" in json.dumps(listing):
                diff_text = json.dumps(listing)
                if '"adds": 0' not in diff_text or '"updates": 0' not in diff_text:
                    return True, line
                raise RuntimeError("memory_diff.json reported zero adds/updates")
            time.sleep(0.5)
        raise RuntimeError("memory_diff.json was not found")
    except Exception as exc:
        print(f"Print memory write/verification failed: {exc}", file=sys.stderr)
        return False, line


# Reset policy (the operator, 2026-09-29): never reset on completion itself. A finished
# print/batch arms a timer; the session resets only after DISCORD_POST_PRINT_QUIET_SECONDS
# of no chat and no new print. A daily backup (discord.daily_reset_hour) resets sessions quiet since before the
# boundary. Nothing resets while printing, with jobs queued, or with a multipart plan open.
DISCORD_POST_PRINT_QUIET_SECONDS = float(_config.cfg()["discord"]["post_print_quiet_s"])


def _live_channel_sessions(chat_id):
    """Every unended Discord session routed to the channel, one per user (group_sessions_per_user).

    ``archived`` is deliberately NOT filtered: sessions.auto_archive hides rows from the UI
    after a few days while the gateway keeps routing to them, so an archived row can still
    be the live conversation (a Sep 7 session survived to Sep 23 exactly this way).
    """
    import sqlite3
    with sqlite3.connect(PROFILE_HOME / "state.db") as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT id, started_at, last_activity_at FROM sessions "
            "WHERE source = 'discord' AND chat_id = ? AND ended_at IS NULL "
            "ORDER BY COALESCE(last_activity_at, started_at) DESC",
            (str(chat_id),),
        ).fetchall()


def _promote_reset(session_ids, reason):
    _config.add_hermes_agent_to_path()
    from hermes_state import SessionDB
    db = SessionDB(PROFILE_HOME / "state.db")
    try:
        return [sid for sid in session_ids if db.promote_to_session_reset(str(sid), reason)]
    finally:
        close = getattr(db, "close", None)
        if callable(close):
            close()


def silently_reset_discord_session(chat_id, session_id=None, reason="print_complete_auto_reset"):
    """End the route(s) without dispatching visible /stop or /new replies.

    With no explicit session_id, every live per-user session in the channel is reset;
    the old single-match discovery refused whenever two users had sessions, so the
    completion reset never fired.
    """
    try:
        ids = [session_id] if session_id else [r["id"] for r in _live_channel_sessions(chat_id)]
        if not ids:
            return False, "no live Discord session in channel"
        changed = _promote_reset(ids, reason)
        return bool(changed), f"session reset boundary recorded silently for {len(changed)}/{len(ids)}"
    except Exception as exc:
        return False, f"silent reset failed: {exc}"


def _open_multipart_plans():
    """Plan ids with at least one part not completed; unreadable plan files count as open."""
    from .print_records import PLANS_DIR
    open_ids = []
    if not PLANS_DIR.is_dir():
        return open_ids
    for path in PLANS_DIR.glob("*.json"):
        try:
            parts = (json.loads(path.read_text(encoding="utf-8")) or {}).get("parts") or []
        except (OSError, json.JSONDecodeError, AttributeError):
            open_ids.append(path.stem)
            continue
        if parts and any(part.get("status") != "completed" for part in parts):
            open_ids.append(path.stem)
    return open_ids


def check_and_reset_idle_discord_session(armed_at=None, chat_id=DISCORD_CHAT_ID,
                                        quiet_seconds=DISCORD_POST_PRINT_QUIET_SECONDS):
    """Post-print quiet reset plus 4 AM backup. Returns (changed, detail, disarm)."""
    queued = _queued_jobs()
    if queued is None:
        return False, "queue check failed", False
    if len(queued) > 0:
        return False, "jobs currently queued", False
    try:
        open_plans = _open_multipart_plans()
    except Exception as exc:
        return False, f"multipart plan check failed: {exc}", False
    if open_plans:
        return False, f"multipart project open: {', '.join(sorted(open_plans))}", False

    now = time.time()
    try:
        rows = _live_channel_sessions(chat_id)
    except Exception as exc:
        return False, f"database query failed: {exc}", False
    if not rows:
        return False, "no active unended Discord session", bool(armed_at)

    boundary = _daily_boundary_epoch(now)
    quiet, overnight = [], []
    for r in rows:
        last = float(r["last_activity_at"] or r["started_at"] or 0)
        if not last:
            continue
        if armed_at and now - max(last, float(armed_at)) >= quiet_seconds:
            quiet.append(r["id"])
        elif last < boundary:
            overnight.append(r["id"])
    if not quiet and not overnight:
        return False, "no session past a reset boundary", False
    try:
        changed = _promote_reset(quiet, "post_print_2h_quiet_reset") if quiet else []
        changed += _promote_reset(overnight, "daily_4am_backup_reset") if overnight else []
    except Exception as exc:
        return False, f"silent reset failed: {exc}", False
    return bool(changed), (f"reset {len(changed)}/{len(quiet) + len(overnight)} "
                           f"(post_print={len(quiet)}, daily={len(overnight)})"), bool(quiet)


DISCORD_DAILY_RESET_HOUR = int(_config.cfg()["discord"]["daily_reset_hour"])


def _daily_boundary_epoch(now=None):
    """Most recent DISCORD_DAILY_RESET_HOUR:00 in the configured timezone, as epoch seconds."""
    from datetime import timedelta
    local = datetime.fromtimestamp(now or time.time(), _config.tz())
    b = local.replace(hour=DISCORD_DAILY_RESET_HOUR, minute=0, second=0, microsecond=0)
    if b > local:
        b -= timedelta(days=1)
    return b.timestamp()


def get_job():
    """Read a stable Moonraker-native job from Moonraker native state."""
    payload = get_json("/printer/objects/query?print_stats&virtual_sdcard")
    status = (payload.get("result") or {}).get("status") or {}
    stats = status.get("print_stats") or {}
    virtual_sdcard = status.get("virtual_sdcard") or {}

    native_state = str(stats.get("state") or "standby").lower()
    state_map = {
        "printing": "Printing",
        "paused": "Paused",
        "complete": "Completed",
        "error": "Error",
        "cancelled": "Operational",
        "standby": "Operational",
    }
    state = state_map.get(native_state, "Operational")
    filename = str(stats.get("filename") or "")

    if native_state == "complete":
        completion = 100.0
    elif virtual_sdcard.get("is_active") and virtual_sdcard.get("file_size"):
        completion = float(virtual_sdcard.get("progress") or 0.0) * 100.0
    else:
        completion = None

    if filename:
        file_info = {
            "name": filename,
            "display": filename,
            "path": filename,
            "origin": "local",
        }
    else:
        file_info = {"name": None}

    return {
        "job": {"file": file_info},
        "progress": {
            "completion": completion,
            "printTime": stats.get("print_duration"),
        },
        "state": state,
        "stats": stats,
    }


def get_json(path, timeout=10):
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["X-Api-Key"] = API_KEY
    request = urllib.request.Request(f"{_config.require(BASE, 'services.moonraker_url')}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def get_file_metadata(filename):
    """Read Moonraker's confirmed metadata without changing printer state."""
    encoded = urllib.parse.quote(str(filename), safe="/")
    payload = get_json(f"/server/files/metadata?filename={encoded}")
    return payload.get("result") or {}


def _job_gcode_name(job_key):
    """Moonraker print filename, the token the timelapse plugin embeds in the MP4 name."""
    return Path(str(job_key or "")).name


def _timelapse_matches_job(video_name, job_key):
    """True only for timelapse_<full gcode name>_<stamp>.mp4 from this exact job.

    mainsail-crew moonraker-timelapse render() keeps the whole remote name,
    including .gcode, then appends time_format_code (%Y%m%d_%H%M here):
    timelapse_{print_stats.filename}_{date_time}.mp4. Stripping the suffix
    matched nothing the plugin actually writes.
    """
    gcode = _job_gcode_name(job_key)
    name = Path(str(video_name or "")).name
    if not gcode or Path(name).suffix.lower() != ".mp4":
        return False
    if ".." in Path(name).parts or "/" in str(video_name) or name != str(video_name):
        return False
    prefix = f"timelapse_{gcode}_"
    if not name.startswith(prefix) or len(name) != len(prefix) + len("YYYYMMDD_HHMM") + 4:
        return False
    stamp = name[len(prefix):-4]
    return bool(re.fullmatch(r"[0-9]{8}_[0-9]{4}", stamp))


def _timelapse_candidates(job_key):
    """List matching MP4s from Moonraker's registered timelapse root, newest first."""
    # The recursive root listing walks hundreds of frame JPEGs and took ~10 s, which
    # tripped the 10 s timeout on every print. The top-level directory call is ~0.3 s.
    payload = get_json("/server/files/directory?path=timelapse&extended=false", timeout=30)
    result = payload.get("result") or {}
    rows = result.get("files") if isinstance(result, dict) else result
    rows = rows or []
    matches = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or row.get("filename") or row.get("name") or "")
        if _timelapse_matches_job(path, job_key):
            matches.append((float(row.get("modified") or row.get("modified_time") or 0), Path(path).name))
    return [path for _, path in sorted(matches, reverse=True)]


def timelapse_archive_name(job_key, video_path, completed_at=None):
    """Stable collision-resistant filename tied to the exact completed job and source video."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    value = completed_at or utc_now()
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    local = parsed.astimezone(ZoneInfo("America/New_York"))
    stamp = local.strftime("%Y%m%d-%H%M%S%z")
    job = _safe_slug(Path(_job_gcode_name(job_key)).stem)[:48] or "print"
    digest = hashlib.sha256(f"{job_key}|{video_path}".encode()).hexdigest()[:12]
    return f"{stamp}-{job}-{digest}.mp4"


def download_timelapse(video_name, job_key):
    """GET the rendered MP4 through Moonraker's timelapse file root. Never SCP the printer."""
    name = Path(str(video_name)).name
    if not _timelapse_matches_job(name, job_key):
        raise ValueError("timelapse filename does not match the completed job")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    destination = MEDIA_DIR / f"source-{hashlib.sha256(name.encode()).hexdigest()[:16]}-{name}"
    if destination.is_file() and destination.stat().st_size:
        return destination
    temporary = destination.with_name(f".{destination.name}.partial")
    encoded = urllib.parse.quote(name)
    request = urllib.request.Request(f"{_config.require(BASE, 'services.moonraker_url')}/server/files/timelapse/{encoded}")
    if API_KEY:
        request.add_header("X-Api-Key", API_KEY)
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as handle:
            copied = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > TIMELAPSE_MAX_BYTES:
                    raise RuntimeError("timelapse download exceeded size cap")
                handle.write(chunk)
        if copied == 0 or not temporary.is_file():
            raise RuntimeError("downloaded timelapse is empty")
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary.exists():
            temporary.unlink()


def _archive_ssh(*remote_args):
    _config.require(TIMELAPSE_ARCHIVE_HOST, "timelapse.archive_host")
    ssh = shutil.which("ssh") or "ssh"
    command = [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "LogLevel=ERROR"]
    if TIMELAPSE_SSH_KEY:
        command += ["-i", TIMELAPSE_SSH_KEY]
    return command + [TIMELAPSE_ARCHIVE_HOST, *remote_args]


def archive_timelapse(job_key, video_path, completed_at=None):
    """Download a matching MP4 over HTTP, then copy that local file to the archive host.

    The printer original stays on the printer. The archive SSH key cannot log
    into the printer, so the source is never root@printer SCP.
    """
    _config.require(TIMELAPSE_ARCHIVE_HOST, "timelapse.archive_host")
    _config.require(TIMELAPSE_ARCHIVE_DIR, "timelapse.archive_dir")
    local = download_timelapse(video_path, job_key)
    remote_name = timelapse_archive_name(job_key, video_path, completed_at)
    remote_tmp = f"{TIMELAPSE_ARCHIVE_DIR}/.{remote_name}.partial"
    remote_final = f"{TIMELAPSE_ARCHIVE_DIR}/{remote_name}"
    with open(local, "rb") as source:
        subprocess.run(
            _archive_ssh(f"mkdir -p {shlex.quote(TIMELAPSE_ARCHIVE_DIR)} && cat > {shlex.quote(remote_tmp)}"),
            stdin=source, check=True, capture_output=True, timeout=180,
        )
    subprocess.run(
        _archive_ssh(f"test -s {shlex.quote(remote_tmp)} && mv {shlex.quote(remote_tmp)} {shlex.quote(remote_final)}"),
        check=True, capture_output=True, timeout=30,
    )
    # The archive host now holds the durable copy; the HTTP staging copy is redundant.
    Path(local).unlink(missing_ok=True)
    return remote_final


def prune_local_timelapses(now=None):
    """Retention for the local Discord cache only: drop MP4s older than the window.

    The remote archive is the durable copy and is kept indefinitely. The
    printer original is never deleted by Hermes.
    """
    if TIMELAPSE_LOCAL_RETENTION_DAYS <= 0 or not MEDIA_DIR.is_dir():
        return []
    cutoff = (now if now is not None else time.time()) - TIMELAPSE_LOCAL_RETENTION_DAYS * 86400
    removed = []
    for path in MEDIA_DIR.glob("*.mp4"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(path)
        except OSError:
            continue
    return removed


def materialize_archived_timelapse(remote_path):
    """Download a successfully archived MP4 into the local media cache for Discord.

    A remote archive path is not a local file. hermes send only sees this copy.
    """
    remote = Path(str(remote_path))
    archive_root = Path(TIMELAPSE_ARCHIVE_DIR)
    if remote.parent != archive_root or remote.suffix.lower() != ".mp4" or remote.name.startswith("."):
        raise ValueError("timelapse archive path is outside the configured archive directory")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    prune_local_timelapses()
    destination = MEDIA_DIR / remote.name
    if destination.is_file() and destination.stat().st_size:
        return destination
    temporary = destination.with_name(f".{destination.name}.partial")
    try:
        with temporary.open("wb") as handle:
            subprocess.run(
                _archive_ssh(f"cat {shlex.quote(str(remote))}"),
                stdout=handle, stderr=subprocess.PIPE, check=True, timeout=180,
            )
        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError("downloaded timelapse is empty")
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary.exists():
            temporary.unlink()


def archive_completed_timelapse(job_key, completed_at=None):
    """Wait a bounded interval for the completed job's MP4, then archive if available.

    With no timelapse.archive_host configured the archive, and the posted video, are off.
    """
    if not TIMELAPSE_ARCHIVE_HOST or not TIMELAPSE_ARCHIVE_DIR:
        print("Timelapse archive is off (timelapse.archive_host / archive_dir not configured)", file=sys.stderr)
        return None
    deadline = time.monotonic() + max(0, TIMELAPSE_RENDER_WAIT_SECONDS)
    while True:
        try:
            candidates = _timelapse_candidates(job_key)
        except Exception as exc:  # transient Moonraker hiccup: keep waiting until the deadline
            print(f"Timelapse lookup unavailable (will retry): {exc}", file=sys.stderr)
            candidates = []
        if candidates:
            try:
                return archive_timelapse(job_key, candidates[0], completed_at)
            except Exception as exc:
                print(f"Timelapse archive failed: {exc}", file=sys.stderr)
                return None
        if time.monotonic() >= deadline:
            return None
        time.sleep(max(0.1, TIMELAPSE_RENDER_POLL_SECONDS))


def _timelapse_marker(job_key):
    """Completion handoff carrying the exact Moonraker filename.

    stdout is captured by the listener and this line is stripped before the
    Discord post. Slugging the human title cannot round trip: safe_label turns
    underscores into spaces and _safe_slug does not reverse that.
    """
    name = _job_gcode_name(job_key)
    if not name or "/" in name or name in {".", ".."}:
        return ""
    return name


def _timelapse_job_key(marker):
    """Accept the marker only when it is the exact current job filename."""
    state = load_state()
    key = str(state.get("job_key") or "") if isinstance(state, dict) else ""
    return key if marker and marker == _timelapse_marker(key) else ""


def get_active_spool():
    """Read the active Spoolman spool when Moonraker exposes it."""
    payload = get_json("/server/spoolman/spool_id")
    result = payload.get("result")
    if isinstance(result, dict):
        spool = dict(result)
        spool_id = result.get("spool_id") or result.get("id")
    else:
        if result in (None, ""):
            return {}
        spool = {"spool_id": result}
        spool_id = result
    if spool_id in (None, ""):
        return spool
    try:
        request = urllib.request.Request(
            f"{_config.require(SPOOLMAN_BASE, 'services.spoolman_url')}/api/v1/spool/{urllib.parse.quote(str(spool_id), safe='')}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            details = json.load(response)
        if isinstance(details, dict):
            spool.update(details)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return spool


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".moonraker-announcements-", dir=STATE_PATH.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, STATE_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


HISTORY_STATE = {"completed": "complete", "cancelled": "cancelled"}


def finalize_from_history(job_key):
    """Finalize a stopped job's note after Klipper cleared the filename.

    On cancel Klipper often drops straight to standby with an empty filename,
    so the live key changes before the stop branch can see it. Moonraker job
    history still names the job and has its duration, filament, and end time.
    """
    jobs = (get_json("/server/history/list?limit=1&order=desc").get("result") or {}).get("jobs") or []
    if not jobs or jobs[0].get("filename") != job_key or jobs[0].get("status") in (None, "in_progress"):
        return None
    job = jobs[0]
    stats = {"state": HISTORY_STATE.get(job["status"], "error"), "print_duration": job.get("print_duration"),
             "filament_used": job.get("filament_used")}
    ended = job.get("end_time")
    completed_at = datetime.fromtimestamp(ended, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ended else None
    return record_completion(job_key, job_key, stats, completed_at=completed_at)


def record_completion(job_key, filename, stats, completed_at=None):
    """Persist confirmed completion data; unavailable optional reads stay absent."""
    context = load_context(job_key)
    context["job_key"] = job_key
    try:
        metadata = get_file_metadata(filename)
    except Exception as exc:
        print(f"Completion metadata unavailable: {exc}", file=sys.stderr)
        metadata = {}
    try:
        active_spool = get_active_spool()
    except Exception as exc:
        print(f"Active Spoolman spool unavailable: {exc}", file=sys.stderr)
        active_spool = {}
    data = build_record_data(
        filename,
        stats=stats,
        metadata=metadata,
        context=context,
        active_spool=active_spool,
        completed_at=completed_at or utc_now(),
    )
    result = write_completed_record(data)
    result.update({"context": context, "completed_at": data["completed_at"]})
    return result


def queue_completion_record(previous, job_key, filename, stats):
    record = record_completion(job_key, filename, stats)
    previous["record_written"] = True
    previous.setdefault("pending_cleanups", []).append({
        "record_path": record["record_path"],
        "plan_id": record.get("plan_id"),
        "cleanup_eligible": record.get("cleanup_eligible", False),
        "discord_session_id": record.get("discord_session_id"),
        "discord_chat_id": record.get("discord_chat_id"),
        "print_started_at": previous.get("print_started_at"),
        "cleanup_due_at": time.time() + CLEANUP_DELAY_SECONDS,
    })


def process_pending_cleanups(state, now=None):
    """Archive only verified channel sessions after the five-minute delay."""
    now = time.time() if now is None else now
    pending = state.get("pending_cleanups")
    if not isinstance(pending, list):
        pending = []
    remaining = []
    dry_run = os.environ.get("PRINT_BITCH_CLEANUP_DRY_RUN") == "1"
    for item in pending:
        if not isinstance(item, dict):
            continue
        plan_id = item.get("plan_id")
        if plan_id and not plan_is_complete(plan_id):
            remaining.append(item)
            continue
        try:
            due_at = float(item.get("cleanup_due_at", 0))
        except (TypeError, ValueError):
            due_at = now + CLEANUP_DELAY_SECONDS
        if due_at > now:
            remaining.append(item)
            continue

        session_id = item.get("discord_session_id")
        detail = ""
        chat_id = str(item.get("discord_chat_id") or DISCORD_CHAT_ID)
        if not chat_id:
            item["last_cleanup_error"] = "discord.chat_id is not configured"
            remaining.append(item)
            continue
        if not session_id:
            session_id, detail = discover_discord_session(
                chat_id,
                not_before=float(item.get("print_started_at") or 0) - 3600,
                db_path=PROFILE_HOME / "state.db",
            )
        if not session_id:
            item["last_cleanup_error"] = detail
            remaining.append(item)
            continue
        archived, detail = archive_discord_session(
            str(session_id),
            chat_id,
            dry_run=dry_run,
            db_path=PROFILE_HOME / "state.db",
        )
        if not archived:
            item["last_cleanup_error"] = detail
            remaining.append(item)
            continue
        if dry_run:
            item["last_cleanup_dry_run"] = detail
            remaining.append(item)
            continue
        update_cleanup_record(item.get("record_path", ""), "archived", str(session_id), detail)
    state["pending_cleanups"] = remaining
    return state


def main():
    try:
        payload = get_job()
    except Exception as exc:
        print(f"Moonraker announcement check failed: {exc}", file=sys.stderr)
        return 0

    job = payload.get("job") or {}
    progress = payload.get("progress") or {}
    state = str(payload.get("state") or "")
    filename = str((job.get("file") or {}).get("display") or (job.get("file") or {}).get("name") or "current print")
    completion = progress.get("completion")
    try:
        completion = float(completion) if completion is not None else None
    except (TypeError, ValueError):
        completion = None

    previous = load_state()
    if state not in ACTIVE_STATES:
        previous = process_pending_cleanups(previous)
        try:
            idle_reset, idle_detail, disarm = check_and_reset_idle_discord_session(
                previous.get("reset_armed_at"))
            if disarm:
                previous.pop("reset_armed_at", None)
            try:  # audit trail; stdout would be posted to Discord
                log = PROFILE_HOME / "logs" / "discord_session_reset.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a") as fh:
                    fh.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} "
                             f"home={_config.hermes_home()} reset={idle_reset} {idle_detail}\n")
            except OSError:
                pass
            if idle_reset:
                previous["last_idle_reset"] = time.time()
                previous["last_idle_reset_detail"] = idle_detail
        except Exception as exc:
            print(f"Idle session reset check failed: {exc}", file=sys.stderr)
    job_key = str((job.get("file") or {}).get("path") or filename)
    previous_key = previous.get("job_key")

    if job_key != previous_key and previous.get("printing") and previous_key and not previous.get("record_written"):
        try:
            finalize_from_history(previous_key)
        except Exception as exc:
            print(f"Stopped print record unavailable: {exc}", file=sys.stderr)

    # A new job gets a fresh one-shot announcement state.
    if job_key != previous_key:
        previous = {
            "job_key": job_key,
            "completion": completion,
            "printing": state in ACTIVE_STATES,
            "announced_completion": False,
            "record_written": False,
            "print_started_at": time.time() if state in ACTIVE_STATES else None,
            "pending_cleanups": previous.get("pending_cleanups", []),
            # A new print is activity: drop any armed post-print timer.
            "reset_armed_at": None if state in ACTIVE_STATES else previous.get("reset_armed_at"),
        }
        save_state(previous)
        return 0

    printing = state in ACTIVE_STATES
    message = None

    # Completion is a transition out of an active print at 100 percent.
    was_printing = bool(previous.get("printing", False))
    if message is None and not printing and was_printing and completion is not None and completion >= 100.0 and not previous.get("announced_completion", False):
        # The event listener consumes this handoff only on the successful transition.
        # Do not render synchronously in the printer status path. The listener sees
        # this marker and performs bounded post-completion retrieval before delivery.
        marker = _timelapse_marker(job_key)
        if marker:
            print(f"TIMELAPSE_POSTPROCESS:{marker}")
        message = print_summary.format_event("complete", filename)
        try:
            from .moonraker_event_listener import generate_roast
            job_info, _ = print_summary.find_job(filename)
            title = (job_info or {}).get("title")
            summary = (job_info or {}).get("summary")
            roast = generate_roast(title, summary)
            if roast:
                message += f"\n\n{roast}"
        except Exception:
            pass
        try:
            queue_completion_record(previous, job_key, filename, payload.get("stats") or {})
        except Exception as exc:
            print(f"Completed print record unavailable: {exc}", file=sys.stderr)
            previous["record_error"] = str(exc)
        context = load_context(job_key)
        multipart_id = context.get("multipart_plan_id") if isinstance(context, dict) else None
        if multipart_id:
            try:
                plan_path = PLANS_DIR / f"{_safe_slug(str(multipart_id))}.json"
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                summary = format_multipart_summary(plan, context.get("part_id"), picker=True)
                if summary:
                    message += "\n" + summary
                    if remaining_plate_choices(plan):
                        # The listener posts the interactive picker after this completion message.
                        print(f"{PLATE_PICKER_MARKER}{plan.get('plan_id') or _safe_slug(str(multipart_id))}")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"Multipart continuation summary unavailable: {exc}", file=sys.stderr)
        batch_complete = _batch_fully_complete(context)
        previous["batch_complete"] = batch_complete
        if batch_complete:
            memory_ok, memory_line = write_and_verify_print_memory(filename, payload.get("stats") or {}, context)
            previous["memory_verified"] = memory_ok
            previous["memory_line"] = memory_line
        else:
            memory_ok = False
            previous["memory_verified"] = False
            previous["memory_line"] = "deferred until the complete batch/job finishes"
        if batch_complete:
            # No immediate reset: arm the 2h quiet timer instead.
            previous["reset_armed_at"] = time.time()
        previous["announced_completion"] = True

    # A cancel or error also finalizes the Obsidian note, without an announcement
    # or session cleanup, so every started print ends with a dated outcome.
    native = str((payload.get("stats") or {}).get("state") or "").lower()
    if was_printing and not printing and native in ("cancelled", "error") and not previous.get("record_written", False):
        try:
            record = record_completion(job_key, filename, payload.get("stats") or {})
            previous["record_written"] = True
            previous["record_path"] = record.get("record_path")
            previous.pop("record_error", None)
        except Exception as exc:
            print(f"Stopped print record unavailable: {exc}", file=sys.stderr)
            previous["record_error"] = str(exc)

    # A transient metadata or vault failure must not permanently lose the
    # record merely because the Discord announcement already succeeded.
    if message is None and not printing and completion is not None and completion >= 100.0 and not previous.get("record_written", False):
        try:
            queue_completion_record(previous, job_key, filename, payload.get("stats") or {})
            previous.pop("record_error", None)
        except Exception as exc:
            previous["record_error"] = str(exc)

    previous.update({"job_key": job_key, "completion": completion, "printing": printing})
    save_state(previous)
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
