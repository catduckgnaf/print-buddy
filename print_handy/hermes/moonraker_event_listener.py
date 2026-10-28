#!/usr/bin/env python3
"""Event driven replacement for the old 5 minute Moonraker cron job. No AI agent involved.

Holds a websocket subscription to Moonraker print_stats. On every print state change
(and on every (re)connect) it runs the existing announcer logic in
moonraker_discord_announcements.main(), captures what it would have printed, and
posts that to #3d-printer through `hermes send` (bot token only, no LLM).

A light local tick (default 10 min) re-runs the same logic so the 2 hour post print
quiet reset and the 4 AM ET backup reset fire without any external scheduler. The
tick makes no model calls and posts nothing unless a transition occurred.
"""

import asyncio
import contextlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import websockets

from .. import go2rtc, healthcheck, logs, printers
from ..core import delivery, spoolman_client
from . import _config
from . import moonraker_discord_announcements as announcer
from . import discord_print_summary as print_summary
from . import plan_timelapse
from . import timelapse_capture
from . import timelapse_encode
from . import print_control
from . import visual_watch as _visual_watch
from . import print_markers
from . import print_records
from . import vertical_short
INTERRUPTED_HINT = print_control.INTERRUPTED_HINT
try:
    from . import maintenance as maintenance_state
except ImportError:
    maintenance_state = None

_LISTENER = _config.cfg()["listener"]
WS_URL = str(_config.cfg()["services"]["moonraker_ws_url"])
DISCORD_TARGET = f"discord:{announcer.DISCORD_CHAT_ID}"
TICK_SECONDS = float(_LISTENER["tick_s"])
HERMES_BIN = _config.hermes_bin()
LOG = announcer.PROFILE_HOME / "logs" / "moonraker_event_listener.log"
TERMINAL = {"cancelled": "Print cancelled", "error": "Print stopped with an error"}


logger = logging.getLogger(__name__)
_PROBLEM = re.compile(r"\b(failed|failure|error|lost|refused|could not|cannot|unreachable|timed out)\b", re.I)


def log(line):
    """Record one listener event: the legacy log file, and the shared logger (stderr, journald, docker logs).

    A line that reports a failure is logged as a warning, and the traceback of the exception being handled
    when it is called, if any, is kept. Credentials are redacted in both places.
    """
    line = logs.redact(str(line))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {line}\n")
    logger.log(logging.WARNING if _PROBLEM.search(line) else logging.INFO, "%s", line,
               exc_info=sys.exc_info() if sys.exc_info()[0] else None)


def _platform_name():
    """The standalone bot's chat platform ([bot] platform, #164); 'discord' unless configured."""
    return str(_config.cfg()["bot"].get("platform") or "discord")


def _telegram_standalone():
    return _config.standalone() and _platform_name() == "telegram"


def _telegram_token():
    """The Telegram bot token, from the variable [telegram] token_env names."""
    return _profile_env_value(str(_config.cfg()["telegram"].get("token_env") or "TELEGRAM_BOT_TOKEN"))


def _telegram_chat_id():
    return str(_config.cfg()["telegram"].get("chat_id") or "")


def _matrix_standalone():
    return _config.standalone() and _platform_name() == "matrix"


def _buttonless_standalone():
    """The platform name when standalone posts have no Discord buttons, else None.

    Telegram (#164 stage 2) and Matrix (stage 3) have no Discord-shaped
    button posts: alerts go out as plain text and the operator answers
    with the typed commands the text names.
    """
    if _telegram_standalone():
        return "telegram"
    if _matrix_standalone():
        return "matrix"
    return None


def _matrix_token():
    """The Matrix access token, from the variable [matrix] access_token_env names."""
    return _profile_env_value(str(_config.cfg()["matrix"].get("access_token_env") or "MATRIX_ACCESS_TOKEN"))


def _matrix_homeserver():
    return str(_config.cfg()["matrix"].get("homeserver_url") or "")


def _matrix_room_id():
    return str(_config.cfg()["matrix"].get("room_id") or "")


def post(message):
    """Deliver physical print lifecycle text to the print chat only, with no agent."""
    if _config.standalone():
        return _post_rest(message)
    target = DISCORD_TARGET
    if target == "discord:":
        log("post skipped: discord.chat_id is not configured")
        return False
    try:
        result = subprocess.run(
            [HERMES_BIN, "-p", "3dprinting", "send", "--quiet", "--to", target, message],
            capture_output=True, text=True, timeout=120,
        )
        log(f"post profile=3dprinting target={target} rc={result.returncode} {message.splitlines()[0][:120]!r} {result.stderr.strip()[:200]}")
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"post failed profile=3dprinting target={target}: {exc!r}")
        return False


def _post_rest(message):
    """Standalone mode: the configured platform's REST sender with its bot token.

    Works with no gateway connected. Discord is the original path; Telegram
    (#164 stage 2) posts text and MEDIA files through telegram_rest, Matrix
    (stage 3) through matrix_rest.
    """
    if _platform_name() == "telegram":
        from print_handy.bot import telegram_rest
        chat = _telegram_chat_id()
        if not chat:
            log("post skipped: telegram.chat_id is not configured")
            return False
        ok, detail = telegram_rest.send(_telegram_token(), chat, message)
        log(f"post rest target=telegram:{chat} ok={ok} {message.splitlines()[0][:120] if message else ''!r}"
            f"{'' if ok else ' ' + str(detail)[:200]}")
        return ok
    if _platform_name() == "matrix":
        from print_handy.bot import matrix_rest
        room = _matrix_room_id()
        if not room:
            log("post skipped: matrix.room_id is not configured")
            return False
        ok, detail = matrix_rest.send(_matrix_homeserver(), _matrix_token(), room, message)
        log(f"post rest target=matrix:{room} ok={ok} {message.splitlines()[0][:120] if message else ''!r}"
            f"{'' if ok else ' ' + str(detail)[:200]}")
        return ok
    from print_handy.bot import rest
    ok, detail = rest.send(_bot_token(), announcer.DISCORD_CHAT_ID, message)
    log(f"post rest target={DISCORD_TARGET} ok={ok} {message.splitlines()[0][:120] if message else ''!r}"
        f"{'' if ok else ' ' + str(detail)[:200]}")
    return ok


def post_alert(message, kind, filename):
    """Post with Resume/Cancel buttons; fall back to plain text if Discord refuses.

    On Telegram and Matrix (#164 stages 2-3) the Discord-shaped button
    posts do not apply: the alert goes out as plain text and the operator
    answers with the typed commands the text names.
    """
    if _buttonless_standalone():
        return post(message)
    try:
        from . import print_alert_buttons as pab
        if pab.post_with_buttons(_bot_token(), announcer.DISCORD_CHAT_ID,
                                 message, kind, filename):
            log(f"post buttons kind={kind} {message.splitlines()[0][:120]!r}")
            return True
        log("button post failed; falling back to plain text")
    except Exception as exc:
        log(f"button post error: {exc!r}")
    return post(message)


def post_plate_picker(plan_id):
    """Post the interactive remaining-plate picker; name the command only when it cannot be delivered."""
    if _buttonless_standalone():
        return post(f"To start the next plate, type `/print-next {plan_id}`.")
    try:
        from . import print_alert_buttons as pab
        from . import print_next
        from .print_records import remaining_plate_choices
        plan = print_next.load_plan(plan_id)
        parts = remaining_plate_choices(plan)
        if not parts:
            return False
        options = [{"label": print_next.plate_choice_label(part), "value": str(part["id"])} for part in parts]
        if pab.post_plate_picker(_bot_token(), announcer.DISCORD_CHAT_ID,
                                 "Which plate is next? Clear the bed, then choose a plate.", plan_id, options):
            log(f"post plate picker plan={plan_id} plates={len(options)}")
            return True
        log(f"plate picker post failed plan={plan_id}; falling back to text")
    except Exception as exc:
        log(f"plate picker post error plan={plan_id}: {exc!r}")
    return post(f"To start the next plate, type `/print-next {plan_id}`.")


def post_insertion_confirmation(slot):
    """Offer an answer-only IFS insertion UI, then retain the command-text fallback."""
    if _buttonless_standalone():
        return post(insertion_prompt(slot))
    try:
        from . import print_alert_buttons as pab
        text = insertion_confirmation_text(slot)
        if pab.post_insertion_confirmation(_bot_token(), announcer.DISCORD_CHAT_ID,
                                           text, slot):
            log(f"post insertion confirmation slot={slot}")
            return True
        log(f"insertion confirmation button post failed slot={slot}; falling back to text")
    except Exception as exc:
        log(f"insertion confirmation button post error slot={slot}: {exc!r}")
    return post(insertion_prompt(slot))


def post_spool_question(record, nag=False):
    """Post once or refresh a paused-spool question without stacking nag messages."""
    if _buttonless_standalone():
        if nag:  # no Discord message to refresh; never stack a second question
            log(f"spool question nag skipped on {_buttonless_standalone()}: no message refresh")
            return False
        return post(spool_question_text(record))
    try:
        from . import print_alert_buttons as pab
        previous = str(record.get("discord_message_id") or "") if nag else ""
        if nag and not previous:
            log("spool question nag skipped: no Discord message id to refresh")
            return False
        message_id = pab.post_spool_question(_bot_token(), announcer.DISCORD_CHAT_ID,
                                             spool_question_text(record, nag=nag), record, previous or None)
        if message_id:
            record["discord_message_id"] = message_id
            atomic_write_json(RUNOUT_PAUSE_STATE, record)
            log(f"spool question {'refreshed' if previous else 'posted'} message={message_id}")
            return True
        log("spool question component post failed")
    except Exception as exc:
        log(f"spool question component post error: {exc!r}")
    if nag:
        log("spool question nag left unchanged to avoid stacking messages")
        return False
    log("spool question component post failed; falling back to text")
    return post(spool_question_text(record))


def shutdown_alert_text(filename, state_message=None):
    from . import print_alert_buttons as pab
    if state_message is None:
        state_message = pab.shutdown_message()
    return ("**Printer firmware stopped.**\n" + print_summary.format_event("error", filename)
            + "\n**Why:** " + pab.explain(state_message)
            + "\nAn emergency stop can't be resumed. Clear the bed, then tap Cancel print "
              "(it clears the stop and ends the job, no motion), or start over with /print-again.")


def post_cancel_report(filename):
    """Full Klipper report on any cancel; falls back to the short summary if the report fails."""
    try:
        from . import klipper_report
        text = print_summary.format_event("cancelled", filename) + "\n" + klipper_report.report(filename)
    except Exception as exc:
        log(f"klipper report failed: {exc!r}")
        text = print_summary.format_event("cancelled", filename)
    return post(text)


SCREEN_CANCEL_NATIVE = {"cancel", "cancelled"}
SCREEN_CANCEL_BUSY = {"printing", "paused", "pausing", "error", "busy"}


def native_screen_cancel(prev, now):
    """Stock firmware left a job (printing/paused/error) for cancel or ready."""
    return prev in SCREEN_CANCEL_BUSY and now in SCREEN_CANCEL_NATIVE | {"ready"}


def screen_cancel_reboot(filename, *, status_reader=None, rebooter=None, clearer=None, poster=None):
    """House rule: a cancel from the printer screen force restarts Klipper. Never while printing."""
    from . import print_alert_buttons as pab
    read = status_reader or print_control.status
    say = poster or post
    st = read()
    if st.get("state") == "printing":
        log("screen cancel reboot skipped: printer is printing again")
        return False, "skipped"
    label = print_summary.safe_label(filename) if filename else "the print"
    if st.get("klippy") == "shutdown":
        # The cancel report was just posted; one result line after the restart is enough.
        ok, msg = (clearer or pab.clear_shutdown)()
    else:
        say(f"Screen cancel on {label}. Force restarting the printer now, about two minutes.")
        ok, msg = (rebooter or print_control.force_reboot)()
    log(f"screen cancel reboot ok={ok}: {msg}")
    if ok and clearer is None and rebooter is None and not _buttonless_standalone():  # real run only; tests inject fakes
        with contextlib.suppress(Exception):
            pab.retire_alerts(_bot_token(), filename, "Cleared after the screen cancel; nothing to do.")
    say(msg)
    return ok, msg


def post_shutdown_alert(filename):
    return post_alert(shutdown_alert_text(filename), "shutdown", filename)


def _profile_env_value(name):
    """Read one profile env value. The listener unit loads no EnvironmentFile."""
    return _config.profile_env_value(name)


def _bot_token():
    """The Discord bot token, from the variable [discord] token_env names (DISCORD_BOT_TOKEN by default)."""
    return _profile_env_value(str(_config.cfg()["discord"].get("token_env") or "DISCORD_BOT_TOKEN"))


def roast_enabled(cfg=None):
    """The roast switch: [vision] roast_enabled, on by default.

    Roasts run whenever the switch is on AND an LLM/vision endpoint is
    available (generate_roast's own checks below); the switch is the
    operator's way to turn them off without losing the camera watchdog.
    """
    vision = (cfg or _config.cfg()).get("vision") or {}
    return bool(vision.get("roast_enabled", True))


def generate_roast(title, summary=""):
    """Generate a quick 1-sentence roast via Luna LLM for the bot persona. Best-effort."""
    title = str(title or "").strip()
    if not title:
        return ""
    if not roast_enabled():
        log("roast skipped: vision.roast_enabled is false")
        return ""
    key = _profile_env_value("CLIPROXY_API_KEY")
    if not key:
        return ""
    chat_url = _config.service_url("vision_chat_url")
    if not chat_url:
        log("roast skipped: services.vision_chat_url is not configured")
        return ""
    prompt = f"Model: {title}"
    if summary:
        prompt += f" ({summary})"
    req = urllib.request.Request(
        chat_url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        data=json.dumps({
            "model": str(_config.cfg()["vision"]["roast_model"]),
            "messages": [
                {"role": "system", "content": f"You are {_config.bot_name()}, a witty 3D printer assistant who gently roasts 3D prints. Give ONE short funny sentence roasting this model. Keep it under 20 words. No quotes, no hashtags, no introductory filler."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 50,
            "temperature": 0.8
        }).encode()
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read())
            res = data["choices"][0]["message"]["content"].strip().strip("\"'")
            return res if res else ""
    except Exception:
        return ""


def start_message_with_roast(filename, archive=None, context_path=None):
    """Format the canonical start message and append a best-effort model roast."""
    message = print_summary.format_event("started", filename, archive=archive, context_path=context_path)
    job, _plate = print_summary.find_job(filename, archive=archive)
    title = (job or {}).get("title") or Path(str(filename or "")).stem
    roast = generate_roast(title)
    return f"{message}\n\n{roast}" if roast else message


def _live_auto_on_print_start():
    """Auto-start the live view on a print start (#311 stage 4), fail-soft.

    When [live_stream] auto_start_on_print is on and the feature is
    configured, the shared session record (print_handy.live_stream) is
    started and the Activity pointer is posted as its own line, like
    the no-mesh alert. This listener is the process that sees every
    Moonraker print start — claimed by the intake or started at the
    printer — so it is where the trigger lives; the bot and the
    Activity server read the same record. Anything wrong here (live
    view off, unconfigured, a torn record) is a silent no-op: a viewer
    feature never disturbs a print announcement (#235 posture).
    """
    try:
        from print_handy import live_stream

        cfg = _config.cfg()
        section = cfg.get("live_stream") or {}
        path = live_stream.session_file_path(cfg)
        session = live_stream.read_session_file(path)
        text = live_stream.auto_start(session, section, now=time.time())
        if text is None:
            return
        live_stream.write_session_file(session, path)
        post(text)
    except Exception:
        pass


def _live_auto_on_print_end():
    """End an auto-started live session when its print ends (#311 stage 4).

    Only a session the auto-start trigger itself opened is ended here;
    a session a user started with /print-live is theirs to stop (the
    empty timeout still applies to it). Fail-soft, like the start hook.
    """
    try:
        from print_handy import live_stream

        cfg = _config.cfg()
        path = live_stream.session_file_path(cfg)
        if not path.exists():
            return
        session = live_stream.read_session_file(path)
        if session.is_live and session.started_by == live_stream.AUTO_STARTED_BY:
            session.stop(now=time.time())
            live_stream.write_session_file(session, path)
    except Exception:
        pass


def paused_message(filename, runout=False, slot=None, spool_id=None):
    """One alert when a print pauses. Never pauses, resumes, or cancels anything itself."""
    where = ""
    try:
        from . import print_stop
        where = print_stop.where_text(print_stop.status())
    except Exception as exc:
        log(f"paused status read failed: {exc!r}")
    if runout:
        which = f"IFS slot {slot}" if slot in (1, 2, 3, 4) else "The active slot"
        into = f"IFS slot {slot}" if slot in (1, 2, 3, 4) else "the active slot"
        spool = f" (spool #{spool_id})" if spool_id else ""
        extra = (f"Filament runout: {which}{spool} ran out of filament.\n"
                 "To finish this print:\n"
                 f"1. Load the replacement filament into {into} at the printer.\n"
                 "2. Answer the spool question below (Existing spool or New spool) so the replacement "
                 "spool is the one registered for that slot — filament usage stays paused for every "
                 "spool until you answer.\n"
                 "3. Tap Resume print below (or type /print-resume) once the filament is loaded. "
                 "The print resumes only when you press it; nothing resumes on its own.")
    else:
        extra = (f"Paused at {where}. " if where else "") + "Fix it at the printer, then tap Resume or Cancel below (or type /print-resume or /print-stop)."
    return print_summary.format_event("paused", filename, extra=extra)


def recovery_slot(filename):
    """The slot and spool this job was using, from the hardware map. No printer call."""
    try:
        state = json.loads(HARDWARE_STATE.read_text())
    except (OSError, ValueError):
        return None, None
    slots = state.get("ifs_slots") or {}
    active = state.get("active_slot")
    slot = active if active in (1, 2, 3, 4) else None
    record = slots.get(str(slot)) if slot else None
    return slot, (record or {}).get("spoolman_id")


def list_spools():
    """Read Spoolman inventory. A failure returns nothing rather than inventing a spool."""
    base = _config.service_url("spoolman_url")
    if not base:
        log("spool inventory read skipped: services.spoolman_url is not configured")
        return []
    payload = spoolman_client.list_spools(base_url=base, timeout=8)
    if payload is None:
        log("spool inventory read failed: Spoolman did not answer")
        return []
    return payload


def spool_matches_recovery(existing_material, candidate_material, existing_color, candidate_color):
    """PLA and PLA+ can match, but color/finish must match exactly."""
    def normalized(value):
        return " ".join(str(value or "").casefold().split())

    materials = {normalized(existing_material), normalized(candidate_material)}
    materials_compatible = materials <= {"pla", "pla+"}
    if not materials_compatible and normalized(existing_material) != normalized(candidate_material):
        return False
    return bool(normalized(existing_color)) and normalized(existing_color) == normalized(candidate_color)


def classify_pause(message, where=""):
    """A pause is a filament runout only when the alert text says so.

    Moonraker's print_stats payload has no pause cause. Ordinary pauses stay ordinary.
    """
    text = f"{message or ''} {where or ''}".casefold()
    return "runout" if "runout" in text or "filament sensor" in text else "other"


def persist_runout_pause(filename, slot, prior_spool_id, path=None):
    """Remember the depleted slot until the operator answers. No printer action."""
    record = {
        "filename": filename or "",
        "slot": slot if slot in (1, 2, 3, 4) else None,
        "prior_spool_id": prior_spool_id,
        "cause": "runout",
        "recorded_at": time.time(),
    }
    atomic_write_json(Path(path or RUNOUT_PAUSE_STATE), record)
    return record


def load_runout_pause(path=None, max_age_s=6 * 60 * 60):
    record = read_json_object(Path(path or RUNOUT_PAUSE_STATE))
    recorded = record.get("recorded_at")
    if record.get("cause") not in ("runout", "swap") or not isinstance(recorded, (int, float)):
        return None
    # Suspended usage never expires: nobody is being charged until a human answers.
    if not record.get("usage_suspended") and time.time() - recorded > max_age_s:
        return None
    return record


def pause_is_runout(message, slot, slot_presence, head_has_filament):
    """Runout = the alert says so, the paused job's slot reads empty, or the head sensor is empty."""
    if classify_pause(message) == "runout":
        return True
    if slot in (1, 2, 3, 4) and isinstance(slot_presence, dict) and slot_presence.get(slot) is False:
        return True
    return head_has_filament is False


FILAMENT_SENSOR_PREFIXES = ("filament_switch_sensor ", "filament_motion_sensor ")


def filament_sensor_names(objects):
    """Filament sensor object names from a Moonraker objects/list payload.

    Names come from the printer's own object list, never a hardcoded sensor
    name: any Klipper filament switch or motion sensor qualifies.
    """
    if not isinstance(objects, (list, tuple)):
        return []
    return [name for name in objects
            if isinstance(name, str) and name.startswith(FILAMENT_SENSOR_PREFIXES)]


def head_sensor_from_status(status):
    """True/False when an enabled filament sensor at the head answers, else None.

    Fail-safe (#442): a sensor that is absent, disabled, or reporting a
    non-boolean value yields None (unknown), never False — an unreadable
    sensor must not turn every pause into a runout. Any enabled sensor
    reporting no filament is decisive (False wins); otherwise one enabled
    sensor reporting filament means the head is loaded.
    """
    if not isinstance(status, dict):
        return None
    saw_loaded = False
    for name, sensor in status.items():
        if not (isinstance(name, str) and name.startswith(FILAMENT_SENSOR_PREFIXES)):
            continue
        if not isinstance(sensor, dict) or sensor.get("enabled") is not True:
            continue
        detected = sensor.get("filament_detected")
        if detected is False:
            return False
        if detected is True:
            saw_loaded = True
    return True if saw_loaded else None


def read_head_sensor():
    """Discover the printer's filament sensors and read them via Moonraker. None when unreadable.

    Read-only: two GETs (objects/list, then an objects/query for exactly the
    sensor objects the printer lists). Any failure returns None so the pause
    classification falls back to the message and slot evidence alone.
    """
    try:
        listing = print_control._call("/printer/objects/list")
        objects = ((listing.get("result") or {}).get("objects")
                   if isinstance(listing, dict) else None)
        names = filament_sensor_names(objects)
        if not names:
            return None
        query = "&".join(urllib.parse.quote(name, safe="") for name in names)
        data = print_control._call(f"/printer/objects/query?{query}")
        status = ((data.get("result") or {}).get("status")
                  if isinstance(data, dict) else None)
        return head_sensor_from_status(status)
    except Exception as exc:
        log(f"head filament sensor read failed: {exc!r}")
        return None


def open_spool_question(filename, slot, prior_spool_id, cause, suspended_spool, path=None):
    """Persist an unanswered spool question. Usage is already suspended by the caller."""
    record = {
        "filename": filename or "",
        "slot": slot if slot in (1, 2, 3, 4) else None,
        "prior_spool_id": prior_spool_id,
        "cause": cause,
        "usage_suspended": True,
        "suspended_spool_id": suspended_spool,
        "recorded_at": time.time(),
        "last_nag_at": time.time(),
        "nags": 0,
    }
    atomic_write_json(Path(path or RUNOUT_PAUSE_STATE), record)
    return record


def spool_question_text(record, nag=False):
    slot = record.get("slot")
    where = f"IFS slot {slot}" if slot in (1, 2, 3, 4) else "the active IFS slot"
    prior = record.get("prior_spool_id")
    why = ("ran out" if record.get("cause") == "runout"
           else "was unloaded and reloaded mid-print")
    head = (f"**Still waiting (reminder {record.get('nags', 0)})**: which spool is in {where}?" if nag
            else f"**Spool check:** the filament in {where} {why}.")
    same = ("\n• `same` if you put spool #%s back" % prior) if record.get("cause") == "swap" and prior else ""
    return (f"{head}\nFilament usage is **paused for every spool** until you answer, "
            f"so neither the old nor the new spool is charged.\nReply with:\n"
            f"• a spool number from Spoolman, e.g. `12`{same}\n"
            f"• or a new spool: `brand, material, color, grams` e.g. `Sunlu, PLA+, White, 1000`\n"
            f"• or `cancel the print` (or the **Cancel print** button) to end the print and close this question\n"
            "`/spool list` shows what is on the shelf. Answering never touches the printer; "
            "cancelling is the one reply that does.")


def clear_runout_pause(path=None):
    target = Path(path or RUNOUT_PAUSE_STATE)
    if target.exists():
        target.unlink()


def compatible_offers(spools, material, color):
    """Offer same color/finish PLA or PLA+ spools. Never pick one."""
    offers = []
    for item in spools or []:
        filament = item.get("filament") or {}
        if item.get("archived") is True:
            continue
        if spool_matches_recovery(material, filament.get("material") or item.get("material"),
                                  color, filament.get("name") or item.get("color") or item.get("name")):
            offers.append({"id": item.get("id"), "remaining_weight": item.get("remaining_weight")})
    return offers


EXISTING_CHOICE = "existing spool"
NEW_CHOICE = "new spool"


def _grams(value):
    text = str(value or "").strip()
    # Discord replies commonly end in punctuation; accept a grams suffix but not stray prose.
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:g)?\s*[.!?]*", text, re.I)
    if not match:
        return None
    try:
        grams = float(match.group(1))
    except (TypeError, ValueError):
        return None
    if grams <= 0:
        return None
    return round(grams, 2)


CANCEL_PRINT_REPLIES = frozenset({
    "cancel", "cancel print", "cancel the print", "cancel it",
    "stop", "stop print", "stop the print",
})


def parse_cancel_print_reply(text):
    """True only for an unambiguous typed instruction to cancel the paused print.

    Consulted while a spool question is pending, before the spool-answer
    parser rejects the reply. Anything softer — a question about cancelling,
    a sentence that merely mentions cancel, extra words — is not an
    instruction and keeps falling through to that rejection, exactly as
    before. The reply gate is the same one every answer passes through
    (an authorized operator in the print channel), so a typed cancel carries
    the same authority as the Cancel print button.
    """
    folded = " ".join(str(text or "").split()).casefold().strip(" .!")
    return folded in CANCEL_PRINT_REPLIES


def parse_runout_reply(text):
    """Turn one Discord reply into an existing-spool or new-spool choice. No writes."""
    raw = " ".join(str(text or "").split())
    folded = raw.casefold()
    if not raw:
        return {"status": "need_choice"}
    if folded in {"a", "existing", EXISTING_CHOICE}:
        return {"status": "need_spool_number"}
    if folded in {"b", "new", NEW_CHOICE}:
        return {"status": "need_new_fields"}
    spool_number = None
    if folded.startswith("#") and folded[1:].isdigit():
        spool_number = int(folded[1:])
    elif folded.isdigit():
        spool_number = int(folded)
    if spool_number:
        return {"status": "existing", "spool_id": spool_number}
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) < 3:
        return {"status": "unparsed", "text": raw}
    brand = parts[0] or None
    material, color = parts[1], parts[2]
    grams = _grams(parts[3]) if len(parts) > 3 else None
    lot = parts[4] if len(parts) > 4 else None
    if not material or not color or grams is None:
        return {"status": "unparsed", "text": raw}
    return {"status": "new", "brand": brand, "material": material, "color": color,
            "grams": grams, "lot": lot}


def apply_runout_choice(state, context, choice, *, client, filaments=None):
    """Bind the paused slot. Inventory writes only. Never calls the printer.

    client(method, path, body) stands in for Spoolman. filaments is a list of
    existing filament records used to avoid a duplicate type.
    """
    slot = context.get("slot")
    if slot not in (1, 2, 3, 4):
        raise ValueError("runout pause has no IFS slot")
    prior_id = context.get("prior_spool_id")
    if choice.get("status") == "existing":
        spool_id = int(choice["spool_id"])
        if prior_id is not None and spool_id == int(prior_id):
            raise ValueError(f"spool #{spool_id} is the depleted spool; pick another or say new")
        record = client("GET", f"/api/v1/spool/{spool_id}", None)
        if record.get("archived") is True:
            raise ValueError(f"spool #{spool_id} is archived")
        filament = record.get("filament") or {}
        client("PATCH", f"/api/v1/spool/{spool_id}", {"location": f"IFS Slot {slot}"})
        if prior_id and int(prior_id) != spool_id:
            client("PATCH", f"/api/v1/spool/{int(prior_id)}",
                   {"archived": True, "remaining_weight": 0, "location": "depleted"})
        return {"action": "existing", "slot": slot, "spool_id": spool_id,
                "material": filament.get("material"), "color": filament.get("name"),
                "prior_spool_id": prior_id, "printer_commands": []}
    if choice.get("status") != "new":
        raise ValueError("choice is not an existing or new spool")
    grams = _grams(choice.get("grams"))
    material = str(choice.get("material") or "").strip()
    color = str(choice.get("color") or "").strip()
    if grams is None or not material or not color:
        raise ValueError("new spool needs material, color/finish, and full starting grams")
    match = None
    for filament in filaments or []:
        if (str(filament.get("material") or "").casefold() == material.casefold()
                and str(filament.get("name") or "").casefold() == color.casefold()
                and str((filament.get("vendor") or {}).get("name") or "").casefold()
                == str(choice.get("brand") or "").casefold()):
            match = filament
            break
    if match is None:
        match = client("POST", "/api/v1/filament", {
            "name": color, "material": material, "vendor_name": choice.get("brand") or None,
            "diameter": 1.75, "density": 1.24, "weight": grams,
        })
    created = client("POST", "/api/v1/spool", {
        "filament_id": match["id"], "initial_weight": grams, "remaining_weight": grams,
        "used_weight": 0, "location": f"IFS Slot {slot}", "lot_nr": choice.get("lot"),
        "comment": "runout replacement; starting weight supplied by operator",
    })
    if prior_id:
        client("PATCH", f"/api/v1/spool/{int(prior_id)}",
               {"archived": True, "remaining_weight": 0, "location": "depleted"})
    return {"action": "new", "slot": slot, "spool_id": created.get("id"),
            "filament_id": match.get("id"), "material": material, "color": color,
            "starting_grams": grams, "prior_spool_id": prior_id, "printer_commands": []}


def manual_resume_tracking_message(filename, slot=None, compatible_spools=None):
    """Prompt inventory reconciliation after a manual resume; never control the printer."""
    slot_text = f"IFS slot {slot}" if slot in (1, 2, 3, 4) else "the affected IFS slot"
    choices = []
    for item in compatible_spools or []:
        if isinstance(item, dict) and item.get("id") is not None:
            choices.append(f"#{item['id']} ({item.get('remaining_weight', 'unknown')} g remaining)")
    offer = (" Compatible same-color PLA/PLA+ spool found: " + ", ".join(choices) + ". You may choose its number; I will not select it automatically." if choices else "")
    return (
        f"Filament runout recovery for {print_summary.safe_label(filename)}, {slot_text}. "
        "Choose how to continue tracking: A) existing Spoolman spool, or B) new spool."
        + offer +
        " If existing, reply with its spool number or confirm the offered number. I will update assignment/tracking only. "
        "If new, load it and resume manually at the printer first. Once the live printer state shows the job resumed, "
        "send a clear label photo (preferred), or give optional brand, material, color/finish, and full starting weight in grams. "
        "I will then create a distinct spool at that full starting weight, mark the replaced exhausted spool depleted when confirmed, "
        "map this IFS slot to the new spool, and reconcile tracking sources. Similar-color records remain untouched. "
        "Inventory only: I will never start, resume, pause, heat, or move the printer."
    )


def _post_completion(message, completion_message):
    """Acknowledge only a matching pending notice after transport success."""
    delivered = post(message)
    if delivered:
        state = announcer.load_state()
        if state.get("pending_completion_message") == completion_message:
            state.pop("pending_completion_message", None)
            state.pop("pending_timelapse_job_key", None)
            state["announced_completion"] = True
            announcer.save_state(state)
    return delivered


def run_announcer(reason):
    """Run announcer once; wait to make completion and its video one Discord message."""
    out = io.StringIO()
    pending = announcer.load_state().get("pending_completion_message")
    if pending:
        tl_key = announcer.load_state().get("pending_timelapse_job_key")
        if tl_key:
            # The completion's video leg was armed but never delivered — the
            # listener restarted (or the postprocess died) during the render
            # wait. Re-drive the retrieval for the persisted job instead of
            # posting the pending text bare and silently losing the video
            # (#373). Claim the key first so a later pass cannot re-drive it
            # twice; the postprocess's own fallbacks post text (with the
            # reason) if the video still cannot be attached.
            state = announcer.load_state()
            state.pop("pending_timelapse_job_key", None)
            announcer.save_state(state)
            threading.Thread(target=_timelapse_postprocess, args=(tl_key, pending, None, None),
                             daemon=True, name="timelapse-postprocess-retry").start()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    announcer.main()
            except Exception as exc:  # never let one bad pass kill the listener
                log(f"announcer error ({reason}): {exc!r}")
            return
        delivered = _post_completion(pending, pending)
        if not delivered or announcer.load_state().get("pending_completion_message"):
            # Avoid a second identical delivery attempt from main() in this pass.
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    announcer.main()
            except Exception as exc:  # never let one bad pass kill the listener
                log(f"announcer error ({reason}): {exc!r}")
            return
    try:
        with contextlib.redirect_stdout(out):
            announcer.main()
    except Exception as exc:  # never let one bad pass kill the listener
        log(f"announcer error ({reason}): {exc!r}")
        return
    lines = out.getvalue().splitlines()
    marker = next((line for line in lines if line.startswith("TIMELAPSE_POSTPROCESS:")), None)
    picker = next((line for line in lines if line.startswith(announcer.PLATE_PICKER_MARKER)), None)
    plan_id = picker.split(":", 1)[1].strip() if picker else None
    tl_line = next((line for line in lines if line.startswith(plan_timelapse.PLAN_MARKER)), None)
    message = "\n".join(line for line in lines
                        if not line.startswith(("TIMELAPSE_POSTPROCESS:", announcer.PLATE_PICKER_MARKER,
                                                plan_timelapse.PLAN_MARKER))).strip()
    if not message:
        return
    tl_plan = None
    if tl_line:
        try:
            tl_id, tl_stage, tl_order = tl_line[len(plan_timelapse.PLAN_MARKER):].strip().split(":")
            tl_plan = (tl_id, tl_stage, int(tl_order))
        except ValueError:
            log(f"ignoring malformed timelapse plan marker {tl_line!r}")
    if tl_plan and tl_plan[1] == "partial":
        # Plan stopped midway: post what exists so far, labeled partial. No picker.
        threading.Thread(target=_plan_timelapse_post, args=(None, message, tl_plan), daemon=True,
                         name="timelapse-partial").start()
        return
    if not marker:
        if tl_plan and tl_plan[1] == "final":
            _plan_timelapse_post(None, message, tl_plan)
        else:
            _post_completion(message, message)
        if plan_id:
            post_plate_picker(plan_id)
        return
    job_key = announcer._timelapse_job_key(marker.split(":", 1)[1].strip())
    if not job_key:
        log(f"timelapse postprocess has no matching active job for {marker!r}")
        if tl_plan and tl_plan[1] == "final":
            _plan_timelapse_post(None, message, tl_plan)
        else:
            # The marker fired, so a video was expected: say in the post why
            # there isn't one instead of letting it vanish silently (#373).
            _post_completion(f"{message}\nTimelapse not attached: the video marker "
                             "didn't match the active job (see the listener log).", message)
        if plan_id:
            post_plate_picker(plan_id)
        return
    # Rendering can take minutes; leave the websocket loop alone and post once when done.
    threading.Thread(target=_timelapse_postprocess, args=(job_key, message, plan_id, tl_plan), daemon=True,
                     name="timelapse-postprocess").start()


def _short_meta(job_key):
    """Overlay metadata for a vertical short, from what the listener already knows (#317)."""
    context = {}
    try:
        context = print_records.load_context(job_key) if job_key else {}
    except Exception:
        context = {}
    printer_name = ""
    try:
        printer_name = printers.current().display_name
    except Exception:
        printer_name = ""
    return {
        "title": context.get("title") or clean(job_key or "print"),
        "printer": printer_name,
        "material": context.get("filament_material") or context.get("material"),
        "elapsed_s": context.get("print_duration") or context.get("elapsed_s"),
        "outcome": "Done",
    }


def _vertical_short_attachment(video, job_key):
    """Build the #317 vertical short for a sized timelapse; None when off, failed, or oversize.

    Warn-only by contract: any failure logs and returns None, so the
    completion post always carries the timelapse itself. The short is
    clamped to the configured platform's effective upload limit
    (_media_upload_limit, #314 — the same cap the timelapse shrink
    uses); a short that cannot fit is dropped, never the timelapse.
    """
    try:
        cfg = _config.cfg()
        timelapse_cfg = cfg.get("timelapse") or {}
        if not timelapse_cfg.get("vertical_short"):
            return None
        short = vertical_short.build_short(
            video, meta=_short_meta(job_key),
            mode=str(timelapse_cfg.get("vertical_short_mode") or "pad"),
            overlay=bool(timelapse_cfg.get("vertical_short_overlay", True)),
            ffmpeg=FFMPEG_BIN)
        limit = _media_upload_limit()
        if Path(str(short)).stat().st_size > limit:
            short = platform_sized_video(short, max_bytes=limit)
        if Path(str(short)).stat().st_size > limit:
            log(f"vertical short for {job_key!r} is still over the {limit}-byte platform limit; dropping it")
            return None
        return Path(str(short))
    except Exception as exc:
        log(f"vertical short for {job_key!r} failed; posting timelapse only: {exc!r}")
        return None


def _captured_timelapse(job_key):
    """The in-container captured timelapse for a job, or None (#246 stage 3).

    Stage 3's half of the delivery fallback order: a finished capture
    that assembles under the platform cap wins; anything else — capture
    off, no capture for this job, every encoder failed — returns None
    and the caller uses the printer-rendered path exactly as before.
    Never raises.
    """
    try:
        return timelapse_encode.captured_video(
            job_key, data=_config.cfg(), max_bytes=_media_upload_limit(), log=log)
    except Exception as exc:
        log(f"captured timelapse lookup failed for {job_key!r}: {exc!r}")
        return None


def _dark_capture(job_key):
    """The #476 camera-dark capture outcome for a job (a manifest dict), or None.

    The manifest of a finished in-container capture that kept no frames
    because every frame was completely dark. Gated on capture_enabled
    exactly like _captured_timelapse's lookup: with capture off there is
    no dark outcome to name, and the delivery thread does no extra work.
    Never raises.
    """
    try:
        data = _config.cfg()
        if not go2rtc.capture_enabled(data):
            return None
        return timelapse_encode.dark_capture(job_key, data=data)
    except Exception as exc:
        log(f"dark capture lookup failed for {job_key!r}: {exc!r}")
        return None


def _timelapse_postprocess(job_key, completion_message, plan_id=None, tl_plan=None):
    try:
        if tl_plan:
            _plan_timelapse_post(job_key, completion_message, tl_plan)
        else:
            _timelapse_post(job_key, completion_message)
    finally:
        # The picker follows the completion/timelapse post, whatever happened to the video.
        if plan_id:
            post_plate_picker(plan_id)


def _plan_timelapse_post(job_key, completion_message, tl_plan):
    """A plate of a multi-plate plan: keep its clip, post video only once, after the last plate or on cancel.

    Non-final plates post the completion text alone (the caller adds the picker). The final plate,
    or a stopped plan ("partial"), posts one video of every stored clip in plate order.
    """
    plan, stage, order = tl_plan
    clip = None
    if job_key and stage in ("more", "final"):
        try:
            captured = _captured_timelapse(job_key)
            if captured is not None:
                clip = plan_timelapse.add_clip(plan, order, captured)
            else:
                archived = announcer.archive_completed_timelapse(job_key)
                if archived:
                    clip = Path(str(announcer.materialize_archived_timelapse(archived)))
                    plan_timelapse.add_clip(plan, order, clip)
                else:
                    dark = _dark_capture(job_key)
                    if dark:
                        log(f"timelapse capture for {job_key!r} kept no frames: all "
                            f"{dark.get('dark_frames')} frame(s) were completely dark (#476)")
                    else:
                        log(f"timelapse not rendered for {job_key!r} within the wait")
        except Exception as exc:
            log(f"plan timelapse clip for {job_key!r} unavailable: {exc!r}")
            clip = None
    if stage == "more":
        _post_completion(completion_message, completion_message)
        with contextlib.suppress(Exception):
            plan_timelapse.prune()  # abandoned plans never reach a final post
        return
    stored = plan_timelapse.clips(plan)
    expected = plan_timelapse.expected_clips(plan)
    # Partial when any plate's clip is missing, not only the final plate's.
    partial = stage == "partial" or clip is None or (expected is not None and len(stored) < expected)
    try:
        if not stored:
            _post_completion(completion_message, completion_message)
            return
        note = f"{completion_message}\nPartial timelapse: {len(stored)} plate(s) so far." if partial else completion_message
        try:
            combined = plan_timelapse.combine(plan)
        except Exception as exc:
            log(f"timelapse combine failed for plan {plan!r}: {exc!r}")
            _post_completion(completion_message, completion_message)
            return
        try:
            announcer.archive_local_timelapse(plan, combined)
        except Exception as exc:
            log(f"combined timelapse archive failed for plan {plan!r}: {exc!r}")
        video = combined
        try:
            video = platform_sized_video(combined)
        except Exception as exc:
            log(f"combined timelapse shrink failed for plan {plan!r}: {exc!r}")
        message = f"{note}\nMEDIA:{video}"
        short = _vertical_short_attachment(video, job_key or plan)
        if short is not None:
            message += f"\nMEDIA:{short}"
        if not _post_completion(message, completion_message):
            log(f"combined timelapse attach failed for plan {plan!r}; posting text only")
            _post_completion(f"{note}\n{_timelapse_too_big_text(combined=True)}", completion_message)
    finally:
        plan_timelapse.clear(plan)
        with contextlib.suppress(Exception):
            plan_timelapse.prune()


def _timelapse_post(job_key, completion_message):
    try:
        captured = _captured_timelapse(job_key)
        if captured is not None:
            # The captured video is already assembled under the platform
            # cap by timelapse_encode; it skips the archive + shrink the
            # printer-rendered path needs.
            message = f"{completion_message}\nMEDIA:{captured}"
            short = _vertical_short_attachment(captured, job_key)
            if short is not None:
                message += f"\nMEDIA:{short}"
            if not _post_completion(message, completion_message):
                log(f"captured timelapse attach failed for {job_key!r}; posting text only")
                _post_completion(f"{completion_message}\n{_timelapse_too_big_text(captured.name)}",
                                 completion_message)
            return
        archived = announcer.archive_completed_timelapse(job_key)
        if not archived:
            dark = _dark_capture(job_key)
            if dark:
                # #476: the in-container capture ran and every frame was
                # dark — name that outcome in the completion post (the
                # #383 principle) instead of the generic not-rendered line.
                _post_completion(
                    f"{completion_message}\n{timelapse_capture.dark_outcome_text(dark.get('dark_frames') or 0)}",
                    completion_message)
                return
            log(f"timelapse not rendered for {job_key!r} within the wait")
            if announcer.TIMELAPSE_ARCHIVE_HOST and announcer.TIMELAPSE_ARCHIVE_DIR:
                # Archiving is on, so a video was expected: the completion
                # post itself says it is missing and why, instead of the
                # video vanishing silently (#373). With archiving off the
                # bare text is the configured behaviour and stays quiet.
                _post_completion(f"{completion_message}\nTimelapse not attached: the printer's "
                                 "rendered video didn't arrive within the wait "
                                 "(see the listener log).", completion_message)
            else:
                _post_completion(completion_message, completion_message)
            return
        local_video = announcer.materialize_archived_timelapse(archived)
        try:
            local_video = platform_sized_video(local_video)
        except Exception as exc:  # oversize source still gets a try; the text fallback covers a refusal
            log(f"timelapse shrink failed for {job_key!r}: {exc!r}")
        message = f"{completion_message}\nMEDIA:{local_video}"
        short = _vertical_short_attachment(local_video, job_key)
        if short is not None:
            message += f"\nMEDIA:{short}"
        if not _post_completion(message, completion_message):
            # Never lose the completion notice because the platform refused the attachment.
            log(f"timelapse attach failed for {job_key!r}; posting text only")
            _post_completion(f"{completion_message}\n{_timelapse_too_big_text(Path(str(archived)).name)}", completion_message)
    except Exception as exc:
        log(f"timelapse postprocess failed for {job_key!r}: {exc!r}")
        _post_completion(completion_message, completion_message)


# paths.ffmpeg: a bare name is looked up on PATH, a path is used as is.
FFMPEG_BIN = (shutil.which(_config.ffmpeg_bin()) or _config.ffmpeg_bin()) if "/" not in _config.ffmpeg_bin() else _config.ffmpeg_bin()


def _media_upload_limit():
    """The timelapse size cap in bytes for the configured platform (#314).

    The one resolution every listener video goes through: bot-core
    delivery's rule (core.delivery.upload_limit — the configured
    platform's [platform] upload_max_bytes, that platform's settings
    default, [discord] as the fallback), tightened for a standalone
    Matrix install by the homeserver's own m.upload.size when the
    server reports one — the same runtime clamp the bot's Matrix
    adapter applies. Discord's resolution is exactly what it was, so
    Discord sizing is unchanged. A failed clamp lookup degrades to the
    configured limit; it never blocks a completion post.
    """
    limit = delivery.upload_limit(_config.cfg())
    if _matrix_standalone():
        try:
            from print_handy.bot import matrix_rest
            server_limit = matrix_rest.media_config(_matrix_homeserver(), _matrix_token())
        except Exception:
            server_limit = None
        if server_limit:
            limit = min(limit, int(server_limit))
    return limit


def _timelapse_too_big_text(archived_name=None, *, combined=False):
    """Why a timelapse is missing from a completion post, in the platform's terms (#314).

    Discord's lines are the ones it has always posted. On Matrix the
    sentence names the real cause — the server's upload limit — so a
    household whose server cannot take the video is told the timelapse
    was recorded but cannot be delivered, instead of it silently never
    arriving. A failed attachment is never reported as delivered.
    """
    platform = _platform_name() if _config.standalone() else "discord"
    if platform == "matrix":
        subject = "Combined timelapse" if combined else "Timelapse"
        return f"{subject} was recorded but is too large for this Matrix server's upload limit."
    if platform == "telegram":
        subject = "Combined timelapse" if combined else "Timelapse"
        return f"{subject} was recorded but is too large for Telegram's upload limit."
    if combined:
        return "Combined timelapse too big for Discord."
    return f"Timelapse archived but too big for Discord: {archived_name}"


def _video_duration(path):
    probe = str(Path(FFMPEG_BIN).with_name("ffprobe"))
    out = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=60, check=True).stdout.strip()
    return float(out)


def _timelapse_encoder():
    """The [timelapse] encoder choice for the sizing shrink (#314): "cpu" unless configured.

    One of vertical_short.ENCODERS; anything unexpected resolves to
    "cpu" here as well as in settings validation, so a bad value can
    cost hardware acceleration but never an encode.
    """
    try:
        encoder = str((_config.cfg().get("timelapse") or {}).get("encoder") or "cpu").strip().lower()
    except Exception:
        return "cpu"
    return encoder if encoder in vertical_short.ENCODERS else "cpu"


def _encode_sized(source, partial, kbps, encoder):
    """One ffmpeg encode of source toward partial at kbps, with the seam's codec for encoder.

    ffmpeg is the compressor — there is no other shrink mechanism. The
    codec choice comes from vertical_short's encoder seam (#246/#311
    names); the bitrate budget that makes the output fit is the sizing
    strategy and stays here.
    """
    subprocess.run([FFMPEG_BIN, "-y", "-v", "error", *vertical_short.encoder_input_args(encoder),
                    "-i", str(source), "-an",
                    "-vf", vertical_short.encoder_filter(encoder, "scale='min(1280,iw)':-2"),
                    *vertical_short.encoder_args(encoder),
                    "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
                    "-movflags", "+faststart", str(partial)],
                   capture_output=True, timeout=600, check=True)


def platform_sized_video(path, max_bytes=None):
    """Return a copy of path re-encoded under the platform upload cap, or path if it already fits.

    The cap defaults to _media_upload_limit() (#314): the configured
    platform's effective upload limit, not always Discord's. The
    two-attempt bitrate strategy is unchanged from the Discord-only
    sizing this generalises. The encode is ffmpeg's, with the
    [timelapse] encoder choice (CPU libx264 by default; VAAPI/QSV/NVENC
    when configured), and any hardware-encode failure retries the same
    attempt with the CPU encoder — it never fails the shrink, let alone
    the completion post.
    """
    max_bytes = max_bytes or _media_upload_limit()
    source = Path(str(path))
    if source.stat().st_size <= max_bytes:
        return source
    target = source.with_name(f"{source.stem}.sized.mp4")
    if target.is_file() and 0 < target.stat().st_size <= max_bytes:
        return target
    duration = max(1.0, _video_duration(source))
    # 90% of the budget for video; timelapses carry no audio.
    kbps = max(200, int(max_bytes * 8 * 0.90 / duration / 1000))
    encoder = _timelapse_encoder()
    for attempt_kbps in (kbps, int(kbps * 0.7)):
        partial = target.with_name(f".{target.name}.partial.mp4")
        used = encoder
        try:
            _encode_sized(source, partial, attempt_kbps, encoder)
        except Exception:
            if encoder == "cpu":
                raise
            log(f"timelapse {encoder} encode failed for {source.name}; retrying with the CPU encoder")
            used = "cpu"
            _encode_sized(source, partial, attempt_kbps, "cpu")
        if partial.stat().st_size <= max_bytes:
            os.replace(partial, target)
            log(f"timelapse shrunk {source.stat().st_size} -> {target.stat().st_size} bytes at {attempt_kbps}k ({used})")
            return target
        partial.unlink(missing_ok=True)
    raise RuntimeError(f"could not shrink {source.name} under {max_bytes} bytes")



NOTIFICATION_STATE = _config.state_file("PRINT_HANDY_NOTIFICATION_STATE", "lifecycle_notifications.json")


def _notification_identity(stats):
    """Stable per-job identity; prefer Moonraker history id, then filename plus start time."""
    job_id = stats.get("job_id") or stats.get("history_job_id")
    if job_id is not None:
        return f"job:{job_id}"
    filename = stats.get("filename")
    started = stats.get("print_start_time") or stats.get("start_time")
    if filename and started is not None:
        return f"file:{filename}|start:{started}"
    return None


def _claim_notification(identity, phase, path=None):
    """Persist an at-most-once lifecycle notification claim, atomically."""
    if not identity:
        return True
    target = Path(path or NOTIFICATION_STATE)
    state = read_json_object(target)
    key = f"{identity}|{phase}"
    if key in state.get("sent", []):
        return False
    sent = list(state.get("sent", []))
    sent.append(key)
    state["sent"] = sent[-500:]
    atomic_write_json(target, state)
    return True

def _record_transition_markers(old, new_state, filename, stats):
    """Record #317 event markers for one print state transition.

    print_markers.record() never raises for storage problems, so marker
    recording can never break the listener or a post. When the #299
    per-domain listener contract lands, its normalised events should call
    print_markers.record() the same way; for now the Moonraker transitions
    below are the only producer.
    """
    if not filename:
        return
    elapsed = stats.get("print_duration") if isinstance(stats, dict) else None
    try:
        elapsed = float(elapsed) if elapsed is not None else None
    except (TypeError, ValueError):
        elapsed = None
    active = old in ("printing", "paused")
    if new_state == "printing" and old == "paused":
        print_markers.record(filename, print_markers.RESUME, elapsed_s=elapsed)
    elif new_state == "printing" and not active:
        print_markers.record(filename, print_markers.START, elapsed_s=elapsed)
    elif new_state == "paused" and old == "printing":
        print_markers.record(filename, print_markers.PAUSE, elapsed_s=elapsed)
    elif active and new_state == "cancelled":
        print_markers.record(filename, print_markers.CANCEL, elapsed_s=elapsed)
        print_markers.record(filename, print_markers.COMPLETE, elapsed_s=elapsed, outcome="cancelled")
    elif active and new_state == "error":
        print_markers.record(filename, print_markers.ERROR, elapsed_s=elapsed)
        print_markers.record(filename, print_markers.COMPLETE, elapsed_s=elapsed, outcome="failed")
    elif active and new_state == "complete":
        print_markers.record(filename, print_markers.COMPLETE, elapsed_s=elapsed, outcome="success")


def clean(filename):
    return print_summary.safe_label(filename, "print")


START_CLAIMS = _config.state_file("PRINT_HANDY_START_CLAIMS", "print_handy_start_claims.json")
START_CLAIM_TTL_S = float(_LISTENER["start_claim_ttl_s"])
NATIVE_POLL_SECONDS = float(_LISTENER["ifs_presence_poll_s"])
IFS_EDGE_STATE = _config.state_file("IFS_EDGE_STATE", "ifs_presence_edges.json")
IFS_PENDING_STATE = _config.state_file("IFS_PENDING_STATE", "ifs_pending_prompts.json")
RUNOUT_PAUSE_STATE = _config.state_file("RUNOUT_PAUSE_STATE", "runout_pause.json")
HARDWARE_STATE = _config.state_file("PRINTER_HARDWARE_STATE", "printer_hardware.json")


def read_json_object(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    os.replace(temporary, path)


def insertion_prompt(slot):
    return (f"Filament loaded in IFS slot {slot}. If it is the same spool, ignore this. "
            f"If it is a different one: `/spool change {slot} <spool#>` for a spool already in Spoolman, "
            f"or `/spool new brand, material, color, grams` then `/spool change {slot} <new#>`. "
            "`/spool list` shows the shelf. Nothing has been changed yet.")


def insertion_confirmation_text(slot):
    """Short human confirmation prompt for a newly detected idle IFS insertion."""
    return (f"**IFS slot {slot} has filament.** Is this the same spool already mapped to that slot? "
            "Tap Same spool, Existing spool, or New spool. No inventory or printer change happens until you answer.")


class FilamentInsertionMonitor:
    """Stable native slot presence detector. Sends text only, never edits inventory."""
    def __init__(self, edge_path=IFS_EDGE_STATE, pending_path=IFS_PENDING_STATE):
        self.edge_path = Path(edge_path)
        self.pending_path = Path(pending_path)
        self.baselined = False
        self.last_sample = {}
        self.stable_counts = {}
        self.transition_from = {}

    def observe(self, slots, *, idle, connected=True):
        """Return newly confirmed slots; startup/reconnect samples only establish baseline."""
        if not connected or not idle or not isinstance(slots, dict):
            self.last_sample = {}
            self.stable_counts = {}
            self.transition_from = {}
            self.baselined = False
            return []
        current = {str(slot): value for slot, value in slots.items() if str(slot) in {"1", "2", "3", "4"} and isinstance(value, bool)}
        if not self.baselined:
            self.last_sample = current
            self.stable_counts = {slot: 1 for slot in current}
            edges = read_json_object(self.edge_path)
            updated = False
            for slot, present in current.items():
                if edges.get(slot) != present:
                    edges[slot] = present
                    updated = True
            if updated:
                atomic_write_json(self.edge_path, edges)
            self.baselined = True
            return []
        stable = []
        edges = read_json_object(self.edge_path)
        pending = read_json_object(self.pending_path)
        changed = False
        for slot, present in current.items():
            prior = self.last_sample.get(slot)
            self.stable_counts[slot] = self.stable_counts.get(slot, 0) + 1 if prior == present else 1
            if prior != present:
                self.transition_from[slot] = prior
            # A quick pull/reinsert can produce only one absent sample: edges remains True,
            # but the physical change is still worth an inventory-only confirmation prompt.
            if (self.transition_from.get(slot) is False and present is True and edges.get(slot) is True):
                stable.append(int(slot))
                pending[slot] = {"event": f"slot-{slot}-present", "status": "awaiting_user_dispatch"}
                self.transition_from[slot] = None
            elif self.stable_counts[slot] >= 2 and edges.get(slot) != present:
                edges[slot] = present
                changed = True
                if self.transition_from.get(slot) is False and present is True:
                    stable.append(int(slot))
                    pending[slot] = {"event": f"slot-{slot}-present", "status": "awaiting_user_dispatch"}
                    self.transition_from[slot] = None
        self.last_sample = current
        if changed:
            atomic_write_json(self.edge_path, edges)
        if stable:
            atomic_write_json(self.pending_path, pending)
        return stable


def start_claim_time(filename, now=None):
    """When print-now claimed this job's start announcement, or None when unclaimed/expired."""
    now = time.time() if now is None else now
    try:
        claims = json.loads(START_CLAIMS.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(claims, dict):
        return None
    ts = claims.get(Path(str(filename or "")).name)
    return ts if isinstance(ts, (int, float)) and 0 <= now - ts < START_CLAIM_TTL_S else None


def start_claimed(filename, now=None):
    """True when model_job.py print-now already owns this job's start announcement."""
    return start_claim_time(filename, now) is not None


def announce_warmup_done(filename):
    """A claimed start already has its one "Print started" post: edit it, never post another.

    This is the single roast point for a warming start (#374): the intake
    posted its start message without a roast and recorded its id, and this
    edit adds the warmup-complete line plus exactly one roast, keeping the
    canonical start details. The recorded id is consumed, so a replayed
    transition cannot add a second roast. With no recorded id, or when
    Discord refuses the edit, the start post is left as is — no second
    post and no roast is posted elsewhere.
    """
    text = print_summary.format_event("started", filename)
    text += "\nWarmup complete, now printing."
    message_id = None
    roast = ""
    try:
        from . import print_next
        message_id = print_next.take_start_message(filename)
    except Exception as exc:
        log(f"start message lookup failed file={filename!r}: {exc!r}")
    if not message_id:
        # The intake already posted the one "Print started" message; a second line after it is noise.
        log(f"no recorded start message; warmup done silently file={filename!r}")
        return False
    try:
        job, _plate = print_summary.find_job(filename)
        roast = generate_roast((job or {}).get("title") or Path(str(filename or "")).stem,
                               (job or {}).get("summary") or "")
    except Exception:
        roast = ""
    if roast:
        text += f"\n\n{roast}"
    if message_id:
        try:
            from . import print_alert_buttons as pab
            if pab.edit_message(_bot_token(), announcer.DISCORD_CHAT_ID,
                                message_id, text):
                log(f"start message edited id={message_id} file={filename!r}")
                return True
        except Exception as exc:
            log(f"start message edit error id={message_id}: {exc!r}")
        log(f"start message edit failed id={message_id}; leaving the start post as is")
    return False


SUBSCRIBE = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "printer.objects.subscribe",
    "params": {"objects": {"print_stats": ["state", "filename", "message", "info"],
                             "gcode_move": ["gcode_position"], "toolhead": ["position"]}},
})

# ZMod START_PRINT logs `Printing with bed mesh: <profile>`. A blank profile means no mesh is
# applied; that is what made the 2026-10-03 first layers print too high.
NO_MESH_ALERT = ("**Heads up: this print started with NO bed mesh.** The first layer will likely be too high or "
                 "uneven, like the cancelled one on Oct 3. Watch it, and cancel if it is not sticking. Fix: run "
                 "full bed leveling on the printer screen before the next print.")


def no_mesh_line(line):
    """True when a gcode response line reports a print starting with no bed mesh profile."""
    marker = "Printing with bed mesh:"
    if not isinstance(line, str) or marker not in line:
        return False
    return line.split(marker, 1)[1].strip() == ""


SPOOL_NAG_SECONDS = float(_LISTENER["spool_nag_s"])


def _camera_url():
    return _config.require(_config.service_url("camera_snapshot_url"), "services.camera_snapshot_url")


def _vision_chat_url():
    return _config.require(_config.service_url("vision_chat_url"), "services.vision_chat_url")


# The visual-watch implementation is shared with the Bambu camera watch (#294):
# these names are the shared module's, re-exported so existing references work.
VISUAL_VERDICTS = _visual_watch.VISUAL_VERDICTS
VISUAL_ALERT_VERDICTS = _visual_watch.VISUAL_ALERT_VERDICTS
VISUAL_HEALTHY_VERDICTS = _visual_watch.VISUAL_HEALTHY_VERDICTS
VISUAL_SENSITIVITY = _visual_watch.VISUAL_SENSITIVITY
_visual_level = _visual_watch._visual_level
_visual_profile = _visual_watch._visual_profile
_frame_changed = _visual_watch._frame_changed
_strip_json_fence = _visual_watch._strip_json_fence
VisualPrintWatch = _visual_watch.VisualPrintWatch
_VISION_BASE = _config.service_url("vision_chat_url")
_VISION_MODEL = str(_config.cfg()["vision"]["model"])
_VISION_CONTEXT = (
    "Printer: Flashforge AD5X, enclosed, smooth PEI plate. "
    "Reply with JSON only, no markdown: {\"verdict\":\"ok|air|spaghetti|detached|empty_idle|uncertain\",\"reason\":\"short\"}. "
    "ok means plastic is on the bed and printing normally. "
    "air means the bed is empty while a print should be there. "
    "spaghetti means a tangled failed extrusion. "
    "detached means a printed part has come off the plate. "
    "empty_idle means the printer is idle and the bed is empty. "
    "uncertain means the frame is not clear enough to judge."
)


_VISION_CONTEXT = "Printer: Flashforge AD5X, enclosed, smooth PEI plate. Reply JSON verdict ok|air|spaghetti|detached|empty_idle|uncertain. "


def _fetch_snapshot(url):
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=8) as response:
        image = response.read(8 * 1024 * 1024 + 1)
    if len(image) > 8 * 1024 * 1024 or not image.startswith(bytes((0xff, 0xd8))):
        raise ValueError("camera response is not a bounded JPEG snapshot")
    return image


def _camera_snapshot_bytes():
    """One watchdog still, from the go2rtc fan-out whenever it is running.

    The #311 one-upstream rule: while timelapse capture or live viewing
    has go2rtc running, it holds the single camera pull, so the watchdog
    reads its still from go2rtc's loopback frame endpoint and never
    opens a second direct connection. When no fan-out feature is on,
    go2rtc is not running and the direct snapshot URL is the sole pull,
    exactly as before. A failed fan-out fetch falls back to the direct
    URL once — sequentially, never in parallel — so a broken stream can
    never degrade the watchdog (#311's fail-soft rule).
    """
    direct = _camera_url()
    try:
        fanout = go2rtc.fanout_frame_url(_config.cfg())
    except Exception:
        fanout = None
    if fanout:
        try:
            frame = _fetch_snapshot(fanout)
            if not _visual_watch.frame_dark(frame):
                return frame
            # #476: a black JPEG is a *successful* fetch, so the #424
            # failure fallback never fired on it — go2rtc serves black
            # frames before the stream produces real ones. A completely
            # dark fan-out frame falls back exactly like a failed fetch.
            log("visual watch: go2rtc fan-out snapshot is completely dark; "
                "falling back to the direct camera snapshot")
        except Exception:
            log("visual watch: go2rtc fan-out snapshot failed; "
                "falling back to the direct camera snapshot")
    return _fetch_snapshot(direct)




_VISION_CONTEXT = "Printer: Flashforge AD5X, enclosed, smooth PEI plate. Reply JSON verdict ok|air|spaghetti|detached|empty_idle|uncertain. "


def _visual_verdict(image, prompt):
    """The shared verdict call (visual_watch.visual_verdict) with this listener's values."""
    return _visual_watch.visual_verdict(
        image, prompt, chat_url=_vision_chat_url, model=_VISION_MODEL,
        api_key=lambda: _profile_env_value("CLIPROXY_API_KEY"), context=_VISION_CONTEXT)


def _visual_layer(stats):
    info = stats.get("info") if isinstance(stats, dict) else None
    if not isinstance(info, dict):
        return None
    value = info.get("current_layer") or info.get("layer")
    return value if isinstance(value, int) else None


def _visual_alert(filename, image, reason, identity=None):
    # #317: a watchdog alert is blooper material; record() never raises.
    print_markers.record(filename, print_markers.WATCHDOG_ALERT, detail=reason)
    target = Path(os.environ.get("PRINT_WATCH_FRAME_DIR") or _config.cache_dir() / "print-watch")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{int(time.time())}-{Path(filename or 'print').stem}.jpg"
    path.write_bytes(image)
    text = f"Print camera check: {clean(filename)}\n{reason}"
    if _buttonless_standalone():
        post(text + f"\n{path}\nMEDIA:{path}")
        return path
    try:
        from . import print_alert_buttons as pab
        if pab.post_visual_alert(_bot_token(), announcer.DISCORD_CHAT_ID,
                                 text, filename, path, identity=identity):
            log(f"post visual alert {clean(filename)!r}")
            return path
        log("visual button post failed; falling back to text")
    except Exception as exc:
        log(f"visual button post error: {exc!r}")
    post(text + f"\n{path}\nMEDIA:{path}")
    return path


def _visual_dark_notice(filename, identity=None):
    """The once-per-print dark-camera notice (#476): a camera problem, not a print alert.

    Plain text on buttonless standalone platforms; on Discord the same text
    with only the "Stop asking for this print" button, via the alert-button
    transport. No image is attached — the frame is black.
    """
    text = (f"Camera check: {clean(filename)} — the camera image is completely dark, "
            "so I can't check the print. Check the camera or its light. "
            "Monitoring continues; nothing was sent to the printer.")
    if _buttonless_standalone():
        post(text)
        return
    try:
        from . import print_alert_buttons as pab
        if pab.post_visual_dark_notice(_bot_token(), announcer.DISCORD_CHAT_ID,
                                       text, filename, identity=identity):
            log(f"post visual dark notice {clean(filename)!r}")
            return
        log("visual dark button post failed; falling back to text")
    except Exception as exc:
        log(f"visual dark notice post error: {exc!r}")
    post(text)


def _slot_bools(slots):
    out = {}
    for key, value in (slots or {}).items():
        try:
            slot = int(key)
        except (TypeError, ValueError):
            continue
        if slot in (1, 2, 3, 4) and isinstance(value, bool):
            out[slot] = value
    return out


class MidPrintSlotTracker:
    """Debounced per-slot presence during a print. Reports emptied and refilled slots."""

    def __init__(self, stable_samples=2):
        self.stable_samples = stable_samples
        self.reset()

    def reset(self):
        self.confirmed = {}
        self.candidate = {}
        self.counts = {}
        self.emptied = set()

    def observe(self, slots):
        events = []
        for slot, present in _slot_bools(slots).items():
            if self.candidate.get(slot) == present:
                self.counts[slot] = self.counts.get(slot, 0) + 1
            else:
                self.candidate[slot], self.counts[slot] = present, 1
            if self.counts[slot] < self.stable_samples or self.confirmed.get(slot) == present:
                continue
            before = self.confirmed.get(slot)
            self.confirmed[slot] = present
            if before is True and present is False:
                self.emptied.add(slot)
                events.append(("emptied", slot))
            elif before is False and present is True and slot in self.emptied:
                self.emptied.discard(slot)
                events.append(("refilled", slot))
        return events

    def empty_slots(self, slots=None):
        live = {s for s, p in _slot_bools(slots).items() if p is False and self.confirmed.get(s) is not False}
        return sorted(self.emptied | live)


def _mapped_spool(slot):
    try:
        state = json.loads(HARDWARE_STATE.read_text())
    except (OSError, ValueError):
        return None
    return ((state.get("ifs_slots") or {}).get(str(slot)) or {}).get("spoolman_id")


def _maintenance_history_totals():
    payload = print_control._call('/server/history/totals')
    result = payload.get('result') or {}
    return float(result.get('total_time') or result.get('print_time') or 0.0)


async def maintenance_reminder_tick(listener):
    """Post due maintenance only when an explicit idle state is known."""
    from . import maintenance
    try:
        st = await asyncio.to_thread(print_control.status)
        if st.get('state') != 'standby':
            return
        hours = await asyncio.to_thread(_maintenance_history_totals)
        state = maintenance.load()
        message = maintenance.reminder_text(state, hours, idle=True)
        if message:
            signature = message.partition('(')[0]
            if state.get('last_reminder') != signature:
                if await asyncio.to_thread(post, message):
                    state['last_reminder'] = signature
                    maintenance.save(state)
    except Exception as exc:
        log(f"maintenance reminder check failed: {exc!r}")


async def maintenance_cancel_reminder():
    try:
        st = await asyncio.to_thread(print_control.status)
        if st.get('state') == 'standby':
            await asyncio.to_thread(post, 'A print was cancelled. When the printer is idle, check the filament path and consider a maintenance quick check.')
    except Exception as exc:
        log(f"cancel maintenance reminder failed: {exc!r}")


async def maintenance_airprint_reminder():
    # TODO: t_16bad84c signal contract is not available here.
    return None


NATIVE_ERROR_HINTS = {
    "E0102": "the filament changer could not feed that slot to the head (tangle, chewed or bent tip, or tube not seated)",
}


def native_error_key(detail):
    """(code, slot) when the stock screen reports an error, else None. The screen can halt a
    print while Klipper still says printing, so Moonraker alone never notices."""
    code = str((detail or {}).get("errorCode") or "").strip()
    if not code and (detail or {}).get("status") != "error":
        return None
    slot = ((detail or {}).get("matlStationInfo") or {}).get("currentLoadSlot")
    return (code or "unknown", slot)


def native_error_text(filename, key):
    code, slot = key
    where = f" (slot {slot})" if slot else ""
    hint = NATIVE_ERROR_HINTS.get(code, "see the printer screen for details")
    link = f"https://wiki.flashforge.com/en/ad5x/error_code_list_ad5x" if code.startswith("E") else ""
    return (f"**Print halted by the printer: {code}{where}.**\n" + print_summary.format_event("error", filename)
            + f"\n**Why:** {hint}.\nKlipper still shows printing, so nothing else will alert. Fix it, then press "
              "retry on the touchscreen." + (f"\n{link}" if link else ""))


class Listener:
    def __init__(self):
        self.state = None
        self.filename = ""
        self.pause_message = ""
        self.ifs_monitor = FilamentInsertionMonitor()
        self.slot_tracker = MidPrintSlotTracker()
        self.visual_watch = VisualPrintWatch()
        self.last_stats = {}
        self.last_visual_task = None
        self.visual_frames = {}
        self.last_slots = {}
        self.last_native_poll = 0.0
        self.native_poll_inflight = False
        self.prev_native = None
        self.screen_reboot_task = None
        self.background_tasks = set()  # strong refs: an unreferenced task can be collected mid-run
        self.maintenance_last_check = 0.0
        self.last_pause_was_runout = False
        self.pause_context = None
        self.native_error_alerted = None
        self.capture_session = None  # #246 stage 2: active timelapse_capture session, if any

    async def read_slots(self):
        from print_handy.core import printer_state
        from print_handy.core import model_job
        detail = await asyncio.to_thread(model_job.read_stock_detail, printer_state.load())
        return detail, model_job.read_stock_ifs_slots_from_detail(detail)

    async def open_question(self, slot, cause):
        """Stop charging every spool, remember the question, and ask once. Nag loop repeats it."""
        if load_runout_pause() is not None:
            return None
        from . import spool_sync
        try:
            suspended = await asyncio.to_thread(spool_sync.suspend_usage)
            note = ""
        except Exception as exc:
            suspended, note = None, f"\n⚠️ Could not pause filament usage ({exc}); the old spool may keep being charged."
            log(f"usage suspend failed: {exc!r}")
        record = open_spool_question(self.filename, slot, _mapped_spool(slot) if slot else None,
                                     cause, suspended)
        log(f"spool question opened: cause={cause} slot={slot} suspended_spool={suspended}")
        await asyncio.to_thread(post_spool_question, record)
        return record

    async def nag_if_due(self):
        record = load_runout_pause()
        if not record or not record.get("usage_suspended"):
            return
        if time.time() - float(record.get("last_nag_at") or 0) < SPOOL_NAG_SECONDS:
            return
        record["nags"] = int(record.get("nags") or 0) + 1
        record["last_nag_at"] = time.time()
        atomic_write_json(RUNOUT_PAUSE_STATE, record)
        await asyncio.to_thread(post_spool_question, record, True)

    async def poll_native_presence(self):
        """Read authenticated stock detail while idle and send only a one-way prompt."""
        if not printers.current().has_native_screen:
            return  # no vendor status API, no IFS presence to watch
        if self.native_poll_inflight:
            return
        self.native_poll_inflight = True
        try:
            detail, slots = await self.read_slots()
            self.last_slots = slots
            native = detail.get("status")
            if native_screen_cancel(self.prev_native, native):
                # Klipper shut down mid print, so Moonraker never sees the screen cancel. The stock firmware does.
                if (await asyncio.to_thread(print_control.status)).get("klippy") == "shutdown":
                    await asyncio.to_thread(post_cancel_report, self.filename)
                    self.start_screen_cancel_reboot(f"native {self.prev_native}->{native} during emergency stop")
            self.prev_native = native
            if self.state in ("printing", "paused"):
                key = native_error_key(detail)
                if key and key != self.native_error_alerted:
                    self.native_error_alerted = key
                    log(f"native screen error {key} file={self.filename!r}")
                    await asyncio.to_thread(post, native_error_text(self.filename, key))
                elif not key:
                    self.native_error_alerted = None
                for event, slot in self.slot_tracker.observe(slots):
                    log(f"mid-print slot {slot} {event}")
                    if event == "refilled":
                        # Unloaded and reloaded mid print: unknown spool. Runout already asked.
                        await self.open_question(slot, "swap")
                    elif (event == "emptied" and self.state == "paused"
                            and not self.last_pause_was_runout):
                        # The slot emptied while paused and the pause was not
                        # classified as a runout: upgrade it instead of
                        # dropping the event at a log line (#442).
                        await self.upgrade_paused_runout(slot)
            # Only exact idle state qualifies. Unknown/preparing/printing all suppress prompts.
            idle = detail.get("status") == "ready" and self.state == "standby"
            found = self.ifs_monitor.observe(slots, idle=idle, connected=True)
            for slot in found:
                await asyncio.to_thread(post_insertion_confirmation, slot)
                log(f"native filament presence transition prompted for slot {slot}")
        except Exception as exc:
            log(f"native filament presence poll failed: {exc!r}")
            self.ifs_monitor.observe({}, idle=False, connected=False)
        finally:
            self.native_poll_inflight = False

    async def classify_runout(self):
        """Pause cause from the alert text, the head sensor, and a fresh slot read.

        Returns (is_runout, slot). Klipper's macro-driven runout pause leaves
        print_stats.message empty (#442), so the message alone is not enough:
        the printer's own filament sensor (discovered from its Moonraker
        object list, any printer) and the IFS slot presence (native-screen
        printers) are read as well. A sensor or slot read that fails or is
        absent contributes no evidence — the pause stays generic.
        """
        empty = []
        present = {}
        slot = None
        if printers.current().has_native_screen:
            slots = self.last_slots
            try:
                _detail, slots = await self.read_slots()
                self.last_slots = slots
                self.slot_tracker.observe(slots)
            except Exception as exc:
                log(f"pause slot read failed: {exc!r}")
            empty = self.slot_tracker.empty_slots(slots)
            present = _slot_bools(slots)
            slot = empty[0] if len(empty) == 1 else recovery_slot(self.filename)[0]
        head_has_filament = await asyncio.to_thread(read_head_sensor)
        if slot is None and head_has_filament is False:
            # The head sensor names no slot; the job's own slot is the one that fed it.
            slot = recovery_slot(self.filename)[0]
        is_runout = pause_is_runout(self.pause_message, slot, present, head_has_filament) or bool(empty)
        return is_runout, slot

    async def upgrade_paused_runout(self, slot):
        """A paused print's slot emptied after the pause was posted as generic (#442).

        The pause alert already went out without a cause; do not leave the
        runout at a log line. Re-post as a runout alert (with the same
        Resume/Cancel buttons a paused alert carries) and open the spool
        question, exactly as if the pause had been classified runout at once.
        """
        self.last_pause_was_runout = True
        spool_id = _mapped_spool(slot) if slot else None
        await asyncio.to_thread(post_alert, paused_message(self.filename, runout=True,
                                                           slot=slot, spool_id=spool_id),
                                "paused", self.filename)
        self.pause_context = await self.open_question(slot, "runout")

    def _visual_identity(self):
        """This print's identity for watchdog mutes (#476): the notification identity.

        The same identity the lifecycle notifications claim on (Moonraker
        job id when known, else filename + start-claim time). It can be
        None early in a print; the mute store's fallback key covers that.
        """
        return _notification_identity({"start_time": start_claim_time(self.filename),
                                       **self.last_stats, "filename": self.filename})

    async def _dark_frame_check(self, reason, layer):
        """Handle one completely dark frame (#476). True when the frame was dark.

        A dark frame is a camera fact: it is logged, the vision endpoint is
        never consulted, the frame never becomes a stall baseline, and it
        never posts as a print alert. The operator gets at most one
        dark-camera notice per print — and none at all when this print's
        watchdog posts are muted.
        """
        log(f"visual check file={self.filename!r} reason={reason} layer={layer} verdict=dark detail='camera image completely dark'")
        if self.visual_watch.dark_noticed:
            return True
        self.visual_watch.dark_noticed = True
        from . import print_alert_buttons as pab
        if await asyncio.to_thread(pab.visual_muted, self.filename, self._visual_identity()):
            log(f"visual dark notice suppressed for muted print {self.filename!r}")
            return True
        await asyncio.to_thread(_visual_dark_notice, self.filename, self._visual_identity())
        return True

    async def visual_check(self, reason, layer):
        """Capture and classify a print frame; notify humans only, never actuate.

        A configured vision endpoint that returns uncertain, or any snapshot or
        vision failure, alerts. Missing plastic, spaghetti, and a detached part
        alert. Layers that advanced with an unchanged frame are promoted to a
        stall here, because the scheduler cannot see the camera before capture.
        At [visual_watch] sensitivity 1 or 2 a stall alerts only when the vision
        verdict is not ok/safe; at 3 to 5 every stall alerts.
        """
        image = None
        try:
            image = await asyncio.to_thread(_camera_snapshot_bytes)
            if await asyncio.to_thread(_visual_watch.frame_dark, image):
                await self._dark_frame_check(reason, layer)
                return
            prior = self.visual_frames.get(self.filename)
            changed = None if prior is None else await asyncio.to_thread(_frame_changed, prior, image)
            snapshot_before = self.visual_watch.last_snapshot_layer
            stall = (reason in {"layer_progress", "periodic"} and changed is False
                     and isinstance(layer, int) and layer >= 5
                     and snapshot_before and layer - snapshot_before >= self.visual_watch.profile["stall_layers"]
                     and self.visual_watch.alerted_stall_layer is None)
            if stall:
                reason = "stalled_layers"
                self.visual_watch.alerted_stall_layer = layer
            # A layer-progress probe that is not a stall must not move the
            # periodic clock or replace the baseline frame.
            if reason != "layer_progress":
                self.visual_frames[self.filename] = image
                self.visual_watch.record(layer, time.time(), image)
            # A layer-progress probe that is not a stall adopts the new frame
            # as the baseline without moving the periodic clock.
            if reason == "layer_progress":
                self.visual_frames[self.filename] = image
                self.visual_watch.last_snapshot = image
                if isinstance(layer, int):
                    self.visual_watch.last_snapshot_layer = max(self.visual_watch.last_snapshot_layer, layer)
                    self.visual_watch.progress_seen_layer = layer
                self.visual_watch.last_snapshot_layer = max(self.visual_watch.last_snapshot_layer, layer or 0)
                self.visual_watch.progress_seen_layer = layer or 0
                log(f"visual check file={self.filename!r} reason={reason} layer={layer} changed={changed} verdict=skipped")
                return
            prompt = "Is there plastic on the bed under the nozzle, or is there spaghetti/detachment?"
            verdict, detail = await asyncio.to_thread(_visual_verdict, image, prompt)
            suspicious = verdict in {"air", "spaghetti", "detached", "uncertain", "no", "unsafe"}
            if reason == "stalled_layers" and changed is False:
                # Levels 1 and 2 trust a healthy vision verdict over the pixel diff.
                suspicious = not (self.visual_watch.profile["vision_veto"] and verdict in VISUAL_HEALTHY_VERDICTS)
            if verdict == "uncertain":
                suspicious = True
            log(f"visual check file={self.filename!r} reason={reason} layer={layer} changed={changed} verdict={verdict} detail={detail!r}")
            if suspicious and image is not None:
                from . import print_alert_buttons as pab
                if await asyncio.to_thread(pab.visual_muted, self.filename, self._visual_identity()):
                    log(f"visual alert suppressed for muted print {self.filename!r}")
                else:
                    await asyncio.to_thread(_visual_alert, self.filename, image,
                                            f"{reason} at layer {layer or 'unknown'}: {verdict}; {detail or 'visual check needs operator review'}",
                                            identity=self._visual_identity())
        except Exception as exc:
            log(f"visual check failed file={self.filename!r} reason={reason}: {exc!r}")
            if image is not None:
                try:
                    from . import print_alert_buttons as pab
                    if await asyncio.to_thread(pab.visual_muted, self.filename, self._visual_identity()):
                        log(f"visual alert suppressed for muted print {self.filename!r}")
                    else:
                        await asyncio.to_thread(
                            _visual_alert, self.filename, image,
                            f"{reason} at layer {layer or 'unknown'}: the vision check could not be completed, "
                            "so treat this as unreviewed and check the print on the printer screen",
                            identity=self._visual_identity())
                except Exception as alert_exc:
                    log(f"visual alert failed file={self.filename!r}: {alert_exc!r}")

    async def on_status(self, print_stats, reason):
        self.last_stats.update(print_stats)
        new_state = print_stats.get("state", self.state)
        if "filename" in print_stats:
            filename = print_stats.get("filename")
            if filename and filename != self.filename:
                self.filename = filename
                self.visual_watch.reset()
                self.visual_frames.pop(filename, None)
        if "message" in print_stats:
            self.pause_message = print_stats.get("message") or ""
        if new_state is None or new_state == self.state:
            return
        old = self.state
        identity = _notification_identity({"start_time": start_claim_time(self.filename),
                                           **self.last_stats, "filename": self.filename})
        # A job that ends into standby (printer-side stop, job removed, Klipper
        # or printer restart during a long pause) never passes through a
        # TERMINAL state, but the job is just as over: #370. Treat it as a
        # terminal transition so it gets the same single claimed notice.
        gone = old in ("printing", "paused") and new_state == "standby"
        phase = "start" if new_state == "printing" and old != "paused" else ("terminal" if old in ("printing", "paused") and (new_state in TERMINAL or gone) else None)
        if phase and not _claim_notification(identity, phase):
            log(f"suppressed duplicate {phase} notice identity={identity!r}")
            self.state = new_state
            return
        self.state = new_state
        log(f"state {old} -> {new_state} file={self.filename!r} ({reason})")
        _record_transition_markers(old, new_state, self.filename, self.last_stats)
        if new_state == "printing" and old != "paused" and self.capture_session is None:
            # A fresh start (or a print already running when the listener
            # (re)connected): open the #246 stage 2 capture session. A
            # resume keeps the session the pause left open.
            self._capture_begin(identity)
        if new_state == "printing" and _config.cfg()["visual_watch"]["enabled"]:
            layer = _visual_layer(self.last_stats)
            reason_due = self.visual_watch.due(layer, time.time(), snapshot_changed=None)
            if reason_due:
                self.last_visual_task = asyncio.create_task(self.visual_check(reason_due, layer))
        if old is not None and old != "printing" and new_state == "printing":
            # Claimed starts already have the intake's one post; unclaimed starts (printer screen,
            # other tools) get exactly one canonical post here.
            if old == "paused":
                log(f"resume, no start post: {self.filename!r}")
                self.last_pause_was_runout = False
            else:
                self.slot_tracker.reset()
                self.visual_watch.reset()
                if start_claimed(self.filename):
                    log(f"start claimed by print-now; updating its message, no second start post: {self.filename!r}")
                    await asyncio.to_thread(announce_warmup_done, self.filename)
                else:
                    await asyncio.to_thread(post, start_message_with_roast(self.filename))
                # The live view's auto-start trigger (#311 stage 4):
                # fail-soft, and a no-op unless auto_start_on_print is on.
                await asyncio.to_thread(_live_auto_on_print_start)
        elif old == "printing" and new_state == "paused":
            self.last_pause_was_runout, slot = await self.classify_runout()
            if self.last_pause_was_runout:
                spool_id = _mapped_spool(slot) if slot else None
                await asyncio.to_thread(post_alert, paused_message(self.filename, runout=True,
                                                                   slot=slot, spool_id=spool_id),
                                        "paused", self.filename)
                self.pause_context = await self.open_question(slot, "runout")
            else:
                self.pause_context = None
                await asyncio.to_thread(post_alert, paused_message(self.filename), "paused", self.filename)
        elif old in ("printing", "paused") and (new_state in TERMINAL or gone):
            self.last_pause_was_runout = False
            # Ended into standby gets the cancelled notice: the print stopped
            # at the printer without completing, which is what the operator
            # needs to hear (#370). The Bambu listener maps the same
            # transition to "cancelled" ("a stop returns the printer to idle").
            effective = "cancelled" if gone else new_state
            if effective == "cancelled":
                await maintenance_cancel_reminder()
            # Completion, records, snapshot, and session reset stay in the announcer.
            # The announcer also owns the sole completion Discord post.
            if effective == "cancelled":
                # Acknowledge promptly; collecting the full Klipper report may block.
                await asyncio.to_thread(post, print_summary.format_event("cancelled", self.filename))
                task = asyncio.create_task(asyncio.to_thread(post_cancel_report, self.filename))
                self.background_tasks.add(task)
                task.add_done_callback(self.background_tasks.discard)
                from . import klipper_report
                if new_state == "cancelled" and not klipper_report.cancelled_by_bot():
                    self.start_screen_cancel_reboot("moonraker cancelled")
            elif new_state != "complete":
                await asyncio.to_thread(post, print_summary.format_event(new_state, self.filename))
        await asyncio.to_thread(run_announcer, f"{old}->{new_state}")
        if new_state in ("complete", "cancelled", "error", "standby") and old in ("printing", "paused"):
            self.visual_watch.reset()
            self.visual_frames.pop(self.filename, None)
            self._capture_end(new_state)
            # An auto-started live session ends with its print (#311 stage 4).
            await asyncio.to_thread(_live_auto_on_print_end)
            await self._retire_paused_prompt(new_state)
            await self.after_print(new_state)

    async def _retire_paused_prompt(self, new_state):
        """Retire this job's paused prompt now that the job has ended (#370).

        The prompt's Resume/Cancel buttons act on a live paused job. Left
        live, a later tap is the first anyone hears that the job ended —
        the operator discovers it is gone only by pressing Cancel. Discord
        only: buttonless platforms never recorded a prompt. Never raises
        into the status flow.
        """
        if _buttonless_standalone():
            return
        headline = {
            "complete": "Print complete.",
            "cancelled": "Print cancelled.",
            "error": "Print stopped with an error.",
            "standby": "Print ended at the printer.",
        }.get(new_state, "Print ended.")
        try:
            from . import print_alert_buttons as pab
            await asyncio.to_thread(
                pab.retire_alerts, _bot_token(), self.filename,
                "This paused prompt is closed; its buttons no longer act on a live job.",
                ("paused",), headline=headline)
        except Exception as exc:
            log(f"retire paused prompt failed file={self.filename!r}: {exc!r}")

    def start_screen_cancel_reboot(self, why):
        """Fire once per cancel, in the background, and only when the bot did not cancel it."""
        from . import klipper_report
        if not printers.current().has_native_screen:
            return False  # the screen-cancel firmware restart is a stock-screen workaround
        if klipper_report.cancelled_by_bot():
            log(f"cancel was the bot's ({why}); no auto restart")
            return False
        if self.screen_reboot_task is not None and not self.screen_reboot_task.done():
            log(f"screen cancel restart already running ({why})")
            return False
        log(f"screen cancel detected ({why}); auto restart")
        self.screen_reboot_task = asyncio.create_task(asyncio.to_thread(screen_cancel_reboot, self.filename))
        return True

    async def after_print(self, new_state):
        """Screen updates deferred during the print, then the next queued copy prompt."""
        self.slot_tracker.reset()
        try:
            from . import spool_sync
            # A listener instance (#336) flushes only its own printer's
            # deferred-screen queue (#335 keyed the queues per printer, so
            # an update can never reach another printer's screen); with no
            # instance identity (direct/Hermes runs) the legacy queue is
            # flushed exactly as before.
            from .. import listeners as _listeners
            instance_id = _listeners.instance_printer_id()
            pending = spool_sync._pending_path(None, instance_id) if instance_id else None
            flushed = await asyncio.to_thread(
                spool_sync.flush_pending_screen, pending_path=pending)
            if flushed:
                log(f"deferred screen sync applied to slots {flushed}")
        except Exception as exc:
            log(f"deferred screen sync failed: {exc!r}")
        if new_state == "complete":
            from . import print_control
            prompt = print_control.next_copy_prompt(self.filename)
            if prompt:
                await asyncio.to_thread(post, prompt)

    # -- #246 stage 2: in-container timelapse capture ---------------------
    # Capture is a side feature: every hook fails soft and, with
    # timelapse.capture_enabled off (the default), begin() returns None
    # and nothing here changes any existing behaviour.

    def _capture_begin(self, job_key):
        """Open a capture session for the job that just started. Never raises."""
        self._capture_end("superseded")
        try:
            self.capture_session = timelapse_capture.begin(
                job_key, self.filename, data=_config.cfg(), log=log)
        except Exception as exc:  # begin() already fails soft; belt and braces
            self.capture_session = None
            log(f"timelapse capture begin failed file={self.filename!r}: {exc!r}")

    def _capture_end(self, state):
        """Close the active capture session, if any. Never raises."""
        session, self.capture_session = self.capture_session, None
        if session is not None:
            try:
                session.stop(state)
            except Exception as exc:  # stop() already fails soft; belt and braces
                log(f"timelapse capture end failed file={self.filename!r}: {exc!r}")

    async def _capture_due(self, layer):
        """Store a frame when the active session's trigger is due.

        The due check is pure; only an actual capture (an HTTP fetch)
        leaves the event loop. Never raises into the status flow.
        """
        session = self.capture_session
        if session is None or self.state != "printing":
            return
        try:
            if session.due(layer=layer):
                await asyncio.to_thread(session.tick, layer)
        except Exception as exc:
            log(f"timelapse capture tick failed file={self.filename!r}: {exc!r}")

    async def session(self):
        self.ifs_monitor.baselined = False
        self.ifs_monitor.last_sample = {}
        self.ifs_monitor.stable_counts = {}
        self.ifs_monitor.transition_from = {}
        async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
            self.moonraker_connected = True
            await ws.send(SUBSCRIBE)
            last_tick = time.monotonic()
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    raw = None
                if raw:
                    msg = json.loads(raw)
                    method = msg.get("method")
                    if msg.get("id") == 1:
                        if "error" in msg:  # klippy not ready yet; notify_klippy_ready resubscribes
                            log(f"subscribe refused: {msg['error']}")
                        else:
                            status = ((msg.get("result") or {}).get("status") or {}).get("print_stats") or {}
                            await self.on_status(status, "subscribe")
                            await self._capture_due(_visual_layer(self.last_stats))
                    elif method == "notify_status_update":
                        ps = (msg.get("params") or [{}])[0].get("print_stats")
                        if ps:
                            await self.on_status(ps, "event")
                            await self._capture_due(_visual_layer(self.last_stats))
                            if self.state == "printing" and _config.cfg()["visual_watch"]["enabled"]:
                                layer = _visual_layer(self.last_stats)
                                reason_due = self.visual_watch.due(layer, time.time())
                                if reason_due:
                                    self.last_visual_task = asyncio.create_task(self.visual_check(reason_due, layer))
                    elif method == "notify_gcode_response":
                        for line in msg.get("params") or []:
                            if no_mesh_line(line):
                                log(f"no bed mesh at print start: {self.filename!r}")
                                await asyncio.to_thread(post, f"{NO_MESH_ALERT}\nPrint: {print_summary.safe_label(self.filename)}")
                    elif method in ("notify_klippy_disconnected", "notify_klippy_shutdown"):
                        log(f"{method} while state={self.state}")
                        if self.state in ("printing", "paused"):
                            if getattr(self, "shutdown_alerted", None) != self.filename:
                                self.shutdown_alerted = self.filename  # one firmware-stopped alert per job
                                await asyncio.to_thread(post_shutdown_alert, self.filename)
                            else:
                                log("firmware stop already alerted for this job; not posting again")
                            self.state = "error"
                    elif method == "notify_klippy_ready":
                        log("klippy ready; resubscribing")
                        await ws.send(SUBSCRIBE)
                if time.monotonic() - self.last_native_poll >= NATIVE_POLL_SECONDS:
                    self.last_native_poll = time.monotonic()
                    await self.poll_native_presence()
                    try:
                        await self.nag_if_due()
                    except Exception as exc:
                        log(f"spool nag failed: {exc!r}")
                if time.monotonic() - self.maintenance_last_check >= 3600:
                    self.maintenance_last_check = time.monotonic()
                    await maintenance_reminder_tick(self)
                if time.monotonic() - last_tick >= TICK_SECONDS:
                    last_tick = time.monotonic()
                    await asyncio.to_thread(run_announcer, "tick")

    async def heartbeat(self):
        """Adapted from contributor Docker commit 3bb0984; no printer probe."""
        while True:
            try:
                await asyncio.to_thread(healthcheck.beat,
                                        moonraker_connected=self.moonraker_connected,
                                        state=self.state)
            except Exception as exc:
                log(f"heartbeat write failed: {exc!r}")
            await asyncio.sleep(healthcheck.HEARTBEAT_S)

    async def forever(self):
        delay = 5
        self.moonraker_connected = False
        beating = asyncio.create_task(self.heartbeat())
        try:
            while True:
                try:
                    await self.session()
                except Exception as exc:
                    log(f"connection lost: {exc!r}; retry in {delay}s")
                finally:
                    self.moonraker_connected = False
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)
        finally:
            beating.cancel()
            await asyncio.gather(beating, return_exceptions=True)


def main():
    if not WS_URL:
        raise SystemExit("services.moonraker_url is not configured (or services.moonraker_ws_url). "
                         "Set it in config/local.yaml or config/local.toml; the listener has nothing to connect to.")
    route = "PRINT_VISION_URL" if os.environ.get("PRINT_VISION_URL") else (_VISION_BASE or "not configured")
    logs.configure()
    log(f"listener starting; camera watchdog initialized route={route} model={_VISION_MODEL}")
    asyncio.run(Listener().forever())


if __name__ == "__main__":
    main()
