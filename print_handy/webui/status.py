"""Read-only status snapshot for the Web UI (#286, stage 2).

One plain dict describing this Print Handy instance, built entirely from
the pieces that already own each fact — nothing here reimplements them:

- configuration from ``settings.load()`` (printer model and its vendor
  connection, bot platform/mode, configured service URLs);
- the standalone bot's heartbeat via ``print_handy.bot.health``
  (``read()`` + ``evaluate()``, the same pair the bot's own ``/healthz``
  and the container healthcheck use);
- listener required/running semantics from ``print_handy.healthcheck``
  (``listener_required()`` + ``check()``, #256);
- Spoolman reachability by probing ``/api/v1/health`` — the endpoint the
  container healthcheck probes — with bundled-vs-external following the
  container rule (``PRINT_HANDY_BUNDLED_SPOOLMAN``; the bundled API is
  loopback-only inside the container, so a loopback Spoolman URL with no
  explicit setting is the bundled one);
- the doctor checks from ``print_handy.doctor``, reused function by
  function and rendered as data: a failing check is a ``fail`` row, never
  an exception. The two live Discord REST probes (``check_discord_login``
  and ``check_shared_token``) are the only doctor rows left out: they
  need the bot token and up to a 10 s network call, so they stay with
  ``python3 -m print_handy.doctor`` where an operator asked for them.

No secret values appear anywhere in the snapshot: no tokens, no API keys,
and no values of the environment variables the ``*_env`` settings name
(the names themselves are not included either — URLs and IDs only).
"""
from __future__ import annotations

import json
import os
import socket
from urllib.parse import urlparse

from .. import __version__, doctor, healthcheck, printers, settings
from ..bot import health as bot_health

# Heartbeat record keys that are safe and useful to show. The record is
# written by the bot itself; whitelisting keeps anything unexpected (and
# anything secret-shaped a future field might add) out of the snapshot.
HEARTBEAT_KEYS = ("connected", "user", "handlers", "mode", "platform", "heartbeat_at")

# Default for snapshot()/healthz()'s heartbeat argument: read the record
# from disk. An explicit None means "there is no heartbeat" — the two must
# not be conflated, or a caller reporting a missing heartbeat silently
# gets whatever stale file another process left behind.
READ_HEARTBEAT = object()

_PROBE_TIMEOUT_S = 2


def _loopback(url):
    host = urlparse(url).hostname or ""
    return host in ("127.0.0.1", "::1", "localhost")


def spoolman_bundled(data, environ):
    """True when the Spoolman answering for this instance is the bundled one.

    Mirrors docker/healthcheck.py: an explicit PRINT_HANDY_BUNDLED_SPOOLMAN
    decides; without one, the bundled API is the loopback-only container
    service, so a loopback configured URL means bundled and any other URL
    means an external Spoolman the operator runs.
    """
    flag = environ.get("PRINT_HANDY_BUNDLED_SPOOLMAN")
    if flag is not None:
        return flag.strip().lower() == "true"
    url = (data.get("services", {}).get("spoolman_url") or "").strip()
    return bool(url) and _loopback(url)


def probe_spoolman(url, timeout=_PROBE_TIMEOUT_S):
    """(ok, detail) for one Spoolman base URL's /api/v1/health. Never raises.

    Through the one Spoolman client (#387); a down service is data, not a
    server error, exactly as the wrapper's health probe reports it.
    """
    from ..core import spoolman_client
    return spoolman_client.health(base_url=url, timeout=timeout)


def _bot_section(data, heartbeat):
    record = heartbeat
    ok, reason = bot_health.evaluate(record, stale_s=data["bot"]["health_stale_s"])
    shown = None
    if isinstance(record, dict):
        shown = {key: record[key] for key in HEARTBEAT_KEYS if key in record}
    return {
        "platform": data["bot"]["platform"],
        "mode": data["bot"]["mode"],
        "ok": ok,
        "reason": reason,
        "heartbeat": shown,
    }


def _listener_section(data):
    entries = settings.printers(data)
    if len(entries) <= 1:
        required = healthcheck.listener_required(data)
        if not required:
            return {"required": False, "ok": None,
                    "reason": f"not required for connection "
                              f"{healthcheck.listener_connection(data)!r}"}
        ok, reason = healthcheck.check(data)
        return {"required": True, "ok": ok, "reason": reason}
    # Multi-printer (#336): one listener instance per printer, aggregated —
    # required when any printer's domain is implemented, ok only when every
    # required printer's heartbeat checks out.
    statuses = healthcheck.listener_statuses(data)
    required = any(row["required"] for row in statuses.values())
    ok = None
    if required:
        ok = all(row["ok"] for row in statuses.values() if row["required"])
    reason = "; ".join(f"{printer_id}: {row['reason']}"
                       for printer_id, row in statuses.items())
    return {"required": required, "ok": ok, "reason": reason,
            "printers": statuses}


def _spoolman_section(data, environ, probe):
    configured = (data.get("services", {}).get("spoolman_url") or "").strip()
    bundled = spoolman_bundled(data, environ)
    if bundled:
        port = environ.get("SPOOLMAN_PORT") or (urlparse(configured).port if configured else None) or 8000
        url = f"http://127.0.0.1:{port}"
    else:
        url = configured
    if not url:
        return {"bundled": bundled, "url": "", "ok": False, "detail": "not configured"}
    ok, detail = probe(url)
    return {"bundled": bundled, "url": url, "ok": ok, "detail": detail}


def doctor_checks(data):
    """The doctor's checks as data: [{label, status, detail}].

    Reuses print_handy.doctor's own check functions with its report
    pattern (a check returns detail text, None to skip, or raises to
    fail). Status is one of "ok", "skip", "fail", "warn". The live
    Discord REST probes are excluded (see the module docstring).
    """
    rows = []

    def report(label, func, *args):
        try:
            detail = func(*args)
        except Exception as exc:  # every failure is reported, none stops the others
            rows.append({"label": label, "status": "fail", "detail": str(exc)})
            return
        if detail is None:
            rows.append({"label": label, "status": "skip", "detail": "not set"})
        else:
            rows.append({"label": label, "status": "ok", "detail": str(detail)})

    report("settings", doctor.check_settings, data)
    report("printer model", doctor.check_model, data)
    report("orca templates", doctor.check_templates, data)
    report("core", doctor.check_core, data)
    report("hardware record", doctor.check_hardware, data)
    report("orca cli", doctor.check_orca, data)
    for key in doctor.SERVICE_PATHS:
        report(key.replace("_url", ""), doctor.check_service, data, key)
    report("bot mode", doctor.check_bot, data)
    report("hermes discord platform", doctor.check_hermes_platform, data)
    report("logging", doctor.check_logging, data)
    try:
        heartbeat_warning = doctor.check_listener_heartbeats(data)
    except Exception as exc:  # a scan problem is a warning, never a failed check
        heartbeat_warning = f"could not check: {exc}"
    rows.append({"label": "listener heartbeats",
                 "status": "warn" if heartbeat_warning else "ok",
                 "detail": heartbeat_warning or "healthy or not required"})
    try:
        warning = doctor.check_strays(data)
    except Exception as exc:  # a scan problem is a warning, never a failed check
        warning = f"could not scan: {exc}"
    rows.append({"label": "stray state files",
                 "status": "warn" if warning else "ok",
                 "detail": warning or "none"})
    try:
        debug_row = doctor.check_debug_mode(data)
    except Exception as exc:  # a state problem is a row, never a failed snapshot
        debug_row = f"could not check: {exc}"
    rows.append({"label": "debug mode",
                 "status": "warn" if debug_row else "ok",
                 "detail": debug_row or "off"})
    return rows


def snapshot(data=None, *, environ=None, heartbeat=READ_HEARTBEAT, probe=None, checks=None):
    """The full status snapshot as a JSON-safe dict.

    ``data`` is a loaded settings dict (``settings.load()`` when omitted).
    ``heartbeat`` overrides the bot heartbeat record (read from disk when
    omitted; an explicit None means no heartbeat); ``probe`` overrides the
    Spoolman probe; ``checks`` overrides the doctor rows. The overrides
    exist for tests and for the server embedding this in another process.
    """
    environ = os.environ if environ is None else environ
    data = settings.load(environ=environ) if data is None else data
    if heartbeat is READ_HEARTBEAT:
        try:
            heartbeat = bot_health.read()
        except Exception:  # an unreadable heartbeat file reads as no heartbeat
            heartbeat = None
    bot = _bot_section(data, heartbeat)
    listener = _listener_section(data)
    spoolman = _spoolman_section(data, environ, probe or probe_spoolman)
    rows = doctor_checks(data) if checks is None else checks
    model_key = data["printer"]["model"]
    model = printers.MODELS[model_key]
    services = {key: value for key, value in sorted(data.get("services", {}).items())
                if key.endswith("_url") and value}
    ok = (bot["ok"] and listener["ok"] is not False and spoolman["ok"]
          and all(row["status"] != "fail" for row in rows))
    return {
        "version": __version__,
        "host": socket.gethostname(),
        "printer": {
            "model": model_key,
            "name": data["printer"].get("name") or model.label,
            "vendor": data["printer"].get("vendor") or model.vendor.key,
            "connection": healthcheck.listener_connection(data),
        },
        "bot": bot,
        "listener": listener,
        "printers": _roster_section(data),
        "spoolman": spoolman,
        "services": services,
        "doctor": rows,
        "ok": ok,
    }


def _roster_section(data):
    """The printer roster, read-only (#337).

    Stage 2e decision, recorded in docs/WEBUI.md: the catalog keeps addressing
    global fields only in v1, so the status page lists the roster (id, name,
    model, vendor, connection and non-secret endpoints) but nothing here edits
    it — roster edits stay in the config file / setup wizard. Secret material
    is excluded by construction: no ``*_env`` variable names and no serial or
    access-code values, matching the module docstring's rule.
    """
    rows = []
    try:
        entries = settings.printers(data)
        default_id = settings.default_printer_id(data)
    except Exception:  # a broken roster never breaks the status page
        return rows
    for entry in entries:
        view = settings.view_for(entry["id"], data)
        row = {
            "id": entry["id"],
            "name": entry.get("name") or "",
            "model": entry.get("model") or "",
            "vendor": view["printer"].get("vendor") or "",
            "connection": healthcheck.listener_connection(view),
            "chat_id": entry.get("chat_id") or "",
            "default": entry["id"] == default_id,
        }
        for key in ("moonraker_url", "octoprint_url", "camera_snapshot_url",
                    "lan_host", "link_host", "host"):
            if entry.get(key):
                row[key] = entry[key]
        rows.append(row)
    return rows


def snapshot_json(**kwargs):
    """The snapshot as a JSON string (the /api/status body)."""
    return json.dumps(snapshot(**kwargs), indent=1, sort_keys=True, default=str)
