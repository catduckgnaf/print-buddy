"""Full Klipper report for a cancelled print, posted to #3d-printer.

Read only: Moonraker object queries, the console history (gcode_store), and the tail of klippy.log.
Nothing here sends a command to the printer.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from . import _config

BASE = _config.moonraker_url()
BOT_CANCEL = _config.state_file("PRINT_BOT_CANCEL_MARKER", "last_bot_cancel.json")
BOT_WINDOW_S = 120
QUERY = ("/printer/objects/query?webhooks&print_stats&virtual_sdcard=progress&extruder=temperature,target"
         "&heater_bed=temperature,target&toolhead=position,homed_axes&gcode_move=gcode_position")
NOISE = re.compile(r"^(ok|B:|T:|// Klipper state: Ready|echo:)", re.I)
ALARM = re.compile(r"error|shutdown|nozzle hit|weight|heater|thermal|adc|timer too close|mcu '\\w+' shutdown|lost communication|"
                   r"cancel|abort|!!|exception|failed|runout", re.I)


def _url(path: str) -> str:
    return _config.require(BASE, "services.moonraker_url") + path


def _get(path: str, timeout: float = 10) -> Any:
    with urllib.request.urlopen(_url(path), timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw) if path.startswith(("/printer", "/server/gcode")) else raw.decode("utf-8", "replace")


def mark_bot_cancel(now: float | None = None) -> None:
    """Called by print_stop.cancel so the report can say who cancelled."""
    try:
        BOT_CANCEL.parent.mkdir(parents=True, exist_ok=True)
        BOT_CANCEL.write_text(json.dumps({"at": time.time() if now is None else now}))
    except OSError:
        pass


def cancelled_by_bot(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    try:
        return now - float(json.loads(BOT_CANCEL.read_text()).get("at", 0)) < BOT_WINDOW_S
    except (OSError, ValueError, TypeError):
        return False


def _hm(seconds: Any) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return "unknown"
    return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m {s % 60:02d}s"


def _temp(obj: dict[str, Any]) -> str:
    t, tgt = obj.get("temperature"), obj.get("target")
    if t is None:
        return "unknown"
    return f"{t:.0f}°C" + (f" (target {tgt:.0f}°C)" if tgt else " (off)")


def console_lines(store: list[dict[str, Any]], since: float, limit: int = 8) -> list[str]:
    """Distinct, meaningful console lines since `since` (epoch), newest last."""
    out: list[str] = []
    for entry in store:
        if float(entry.get("time") or 0) < since:
            continue
        for line in str(entry.get("message") or "").splitlines():
            line = line.lstrip("/! ").strip()
            if not line or NOISE.match(line) or line in out:
                continue
            out.append(line)
    return out[-limit:]


def log_alarms(text: str, limit: int = 6) -> list[str]:
    """Alarm-looking lines from the klippy.log tail, deduplicated, newest last."""
    seen: list[str] = []
    for line in text.splitlines()[1:]:  # first line of a ranged read is usually partial
        line = line.strip()
        if line and ALARM.search(line) and "mcu_awake" not in line and not line.startswith(("Stats ", "Receive:", "Sent ")):
            line = line[:220]
            if line in seen:
                seen.remove(line)
            seen.append(line)
    return seen[-limit:]


def build(filename: str, status: dict[str, Any], store: list[dict[str, Any]], log_tail: str,
          *, by_bot: bool, now: float | None = None) -> str:
    from . import print_alert_buttons as pab
    now = time.time() if now is None else now
    ps = status.get("print_stats") or {}
    wh = status.get("webhooks") or {}
    info = ps.get("info") or {}
    who = "by the print bot (/print-stop or a button)" if by_bot else "from the printer screen or another client"
    lines = [f"**Print cancelled {who}.** Klipper report:"]
    where = []
    if info.get("current_layer") and info.get("total_layer"):
        where.append(f"layer {info['current_layer']}/{info['total_layer']}")
    prog = (status.get("virtual_sdcard") or {}).get("progress")
    if isinstance(prog, (int, float)) and prog:
        where.append(f"{prog * 100:.0f}% of the file")
    pos = (status.get("gcode_move") or {}).get("gcode_position") or (status.get("toolhead") or {}).get("position")
    if pos and len(pos) >= 3:
        where.append(f"nozzle at Z={pos[2]:.2f} mm")
    lines.append("Stopped at: " + (", ".join(where) or "position unknown"))
    lines.append(f"Printed for {_hm(ps.get('print_duration'))} (job open {_hm(ps.get('total_duration'))}), "
                 f"{(ps.get('filament_used') or 0) / 1000:.2f} m filament used")
    lines.append(f"Nozzle {_temp(status.get('extruder') or {})}, bed {_temp(status.get('heater_bed') or {})}")
    klippy = wh.get("state") or "unknown"
    lines.append(f"Klipper: {klippy}" + (f", Moonraker job message: {ps['message']}" if ps.get("message") else ""))
    if klippy in ("shutdown", "error"):
        lines.append("**Why it stopped:** " + pab.explain(wh.get("state_message") or ""))
        lines.append("Klipper is still in an emergency stop. It needs one firmware restart (/print-reboot) "
                     "before it will accept anything else.")
    since = now - max(float(ps.get("total_duration") or 0), 600) - 60
    console = console_lines(store, since)
    if console:
        lines.append("Last console messages:\n```\n" + "\n".join(console) + "\n```")
    alarms = log_alarms(log_tail)
    if alarms:
        lines.append("klippy.log warnings (most recent):\n```\n" + "\n".join(alarms) + "\n```")
    if not console and not alarms and klippy == "ready":
        lines.append("No errors in the console or klippy.log. Looks like a plain manual cancel.")
    text = "\n".join(lines)
    return text if len(text) <= 1990 else text[:1950].rsplit("\n", 1)[0] + "\n(report trimmed)\n```"


def report(filename: str) -> str:
    """Collect everything live and build the text. Each source fails independently."""
    status: dict[str, Any] = {}
    store: list[dict[str, Any]] = []
    tail = ""
    try:
        status = (_get(QUERY).get("result") or {}).get("status") or {}
    except Exception:
        pass
    try:
        store = (_get("/server/gcode_store?count=100").get("result") or {}).get("gcode_store") or []
    except Exception:
        pass
    try:
        req = urllib.request.Request(_url("/server/files/klippy.log"), headers={"Range": "bytes=-20000"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            tail = resp.read().decode("utf-8", "replace")
    except Exception:
        pass
    text = build(filename, status, store, tail, by_bot=cancelled_by_bot())
    if not status:
        text += "\n(Couldn't read live printer state; report is partial.)"
    return text
