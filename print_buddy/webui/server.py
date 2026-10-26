"""Read-only Web UI status server (#286, stage 2).

A stdlib-only HTTP server (``http.server``; no new dependency, no build
step) serving three read-only routes:

- ``GET /`` — a simple server-rendered status page (plain HTML, every
  interpolated value escaped, no JavaScript);
- ``GET /api/status`` — the status snapshot as JSON
  (:mod:`print_buddy.webui.status`);
- ``GET /healthz`` — the bot heartbeat evaluation, with the same
  200/503 + JSON shape as the standalone bot's own health server.

Anything else is 404, and any non-GET method is 405: this stage writes
nothing. The picker configuration page is stage 3.

The server starts only when ``[webui] enabled`` is true and ``port`` is
above 0. Access control: the access token lives only in the environment
variable ``[webui] access_token_env`` names (default
``WEBUI_ACCESS_TOKEN``) and is sent as the ``X-WebUI-Token`` header,
compared with ``hmac.compare_digest``. When the bind host is not
loopback, a token is mandatory — an empty token refuses the start with a
clear error, because a LAN-reachable status page must not be open. On
loopback the token is optional, and honoured when set. The token value
itself is never rendered, logged, or included in any response.
"""
from __future__ import annotations

import hmac
import html
import ipaddress
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .. import settings
from ..bot import health as bot_health
from . import status as status_module

TOKEN_HEADER = "X-WebUI-Token"
LOOPBACK_NAMES = frozenset({"localhost"})


class WebUIServerError(RuntimeError):
    """The Web UI server was refused: disabled, unconfigured, or unsafe."""


def is_loopback(host):
    """True for loopback bind hosts (127.0.0.0/8, ::1, "localhost") only."""
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def access_token(data, environ=None):
    """The configured access token's *value* from the environment ("" if unset).

    Only the name is a setting (``[webui] access_token_env``); the value
    comes from the environment and is never a setting, like every other
    Print Buddy secret.
    """
    environ = os.environ if environ is None else environ
    return environ.get(data["webui"]["access_token_env"]) or ""


def check_start(data, environ=None):
    """Refuse an unsafe or unconfigured start; return (host, port, token)."""
    webui = data["webui"]
    if not webui["enabled"]:
        raise WebUIServerError(
            "webui: not started: [webui] enabled is false (the Web UI is "
            "optional and off by default; set enabled = true and a port to run it)")
    port = int(webui["port"] or 0)
    if port <= 0:
        raise WebUIServerError(
            "webui: not started: [webui] port is 0 (unset); set a port above 0 to run it")
    host = webui["host"]
    token = access_token(data, environ)
    if not is_loopback(host) and not token:
        raise WebUIServerError(
            f"webui: refusing to bind {host}: a non-loopback bind requires an "
            f"access token in ${webui['access_token_env']} (the environment variable "
            f"[webui] access_token_env names); set the token or bind 127.0.0.1")
    return host, port, token


def healthz(data=None, heartbeat=None):
    """(http_code, body_dict) for /healthz: the bot-health evaluation.

    Mirrors print_buddy.bot.health.serve: 200 when evaluate() passes,
    503 otherwise, with the reason and the heartbeat record. The record
    is whitelisted to the same safe keys the snapshot shows.
    """
    data = settings.load() if data is None else data
    if heartbeat is None:
        try:
            heartbeat = bot_health.read()
        except Exception:  # an unreadable heartbeat file reads as no heartbeat
            heartbeat = None
    ok, reason = bot_health.evaluate(heartbeat, stale_s=data["bot"]["health_stale_s"])
    body = {"ok": ok, "reason": reason}
    if isinstance(heartbeat, dict):
        body.update({key: heartbeat[key] for key in status_module.HEARTBEAT_KEYS
                     if key in heartbeat})
    return (200 if ok else 503), body


def render_status_html(snap):
    """The / page: the snapshot as plain escaped HTML tables. No scripts."""
    esc = html.escape
    bot, listener, spoolman = snap["bot"], snap["listener"], snap["spoolman"]
    heartbeat = bot["heartbeat"] or {}
    rows = [
        ("Version", snap["version"]),
        ("Host", snap["host"]),
        ("Printer", f"{snap['printer']['name']} ({snap['printer']['model']})"),
        ("Connection", snap["printer"]["connection"]),
        ("Bot", f"{bot['platform']} / {bot['mode']} — {bot['reason']}"),
        ("Bot connected", str(heartbeat.get("connected", "unknown"))),
        ("Listener", "not required" if not listener["required"]
         else ("ok" if listener["ok"] else "FAIL") + f" — {listener['reason']}"),
        ("Spoolman", ("bundled" if spoolman["bundled"] else "external")
         + f" {spoolman['url'] or '(not configured)'} — "
         + ("ok" if spoolman["ok"] else "down") + f" ({spoolman['detail']})"),
    ]
    services = "".join(
        f"<tr><th>{esc(key)}</th><td>{esc(str(value))}</td></tr>"
        for key, value in snap["services"].items())
    doctor = "".join(
        f"<tr><td>{esc(row['label'])}</td><td>{esc(row['status'])}</td>"
        f"<td>{esc(row['detail'])}</td></tr>" for row in snap["doctor"])
    main_rows = "".join(
        f"<tr><th>{esc(label)}</th><td>{esc(str(value))}</td></tr>" for label, value in rows)
    return ("<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>Print Buddy {esc(snap['version'])} — status</title></head><body>"
            "<h1>Print Buddy status</h1>"
            f"<p>Overall: {'ok' if snap['ok'] else 'attention needed'} (read-only page; "
            "configuration happens in the YAML settings file)</p>"
            f"<table>{main_rows}</table>"
            + (f"<h2>Services</h2><table>{services}</table>" if services else "")
            + f"<h2>Doctor checks</h2><table>{doctor}</table>"
            "</body></html>\n")


class _Handler(BaseHTTPRequestHandler):
    server_version = "PrintBuddyWebUI/1"
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------
    def log_message(self, *args):  # keep stdout clean; errors still surface as 500s
        pass

    def _send(self, code, body, content_type):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload, indent=1, sort_keys=True, default=str),
                   "application/json")

    def _authorized(self):
        token = self.server.webui_token
        if not token:
            return True
        provided = self.headers.get(TOKEN_HEADER) or ""
        return hmac.compare_digest(provided, token)

    # -- routes -----------------------------------------------------------
    def do_GET(self):
        try:
            if not self._authorized():
                self._json(401, {"ok": False, "reason": f"missing or wrong {TOKEN_HEADER}"})
                return
            path = urlparse(self.path).path
            if path == "/":
                snap = self.server.snapshot_func()
                self._send(200, render_status_html(snap), "text/html; charset=utf-8")
            elif path == "/api/status":
                self._json(200, self.server.snapshot_func())
            elif path == "/healthz":
                code, body = healthz(self.server.settings_data)
                self._json(code, body)
            else:
                self._json(404, {"ok": False, "reason": "try /, /api/status or /healthz"})
        except Exception as exc:  # a broken snapshot is a 500, never a dropped connection
            self._json(500, {"ok": False, "reason": f"{type(exc).__name__}: {exc}"})

    def _read_only(self):
        self._json(405, {"ok": False,
                         "reason": "the Web UI status server is read-only (GET only)"})

    do_POST = _read_only
    do_PUT = _read_only
    do_DELETE = _read_only
    do_PATCH = _read_only
    do_HEAD = _read_only
    do_OPTIONS = _read_only


def make_server(data=None, *, environ=None, host=None, port=None, snapshot_func=None):
    """A bound (not yet serving) ThreadingHTTPServer for the Web UI.

    ``host``/``port`` override the settings (tests bind port 0 for an
    ephemeral loopback port; the access-control rules then come from the
    *effective* bind host). Raises WebUIServerError when the start is
    refused, before any socket is bound.
    """
    environ = os.environ if environ is None else environ
    data = settings.load(environ=environ) if data is None else data
    cfg_host, cfg_port, token = check_start(data, environ)
    bind_host = cfg_host if host is None else host
    bind_port = cfg_port if port is None else int(port)
    if not is_loopback(bind_host) and not token:
        raise WebUIServerError(
            f"webui: refusing to bind {bind_host}: a non-loopback bind requires an "
            f"access token in ${data['webui']['access_token_env']}")
    server = ThreadingHTTPServer((bind_host, bind_port), _Handler)
    server.settings_data = data
    server.webui_token = token
    server.snapshot_func = snapshot_func or (
        lambda: status_module.snapshot(data, environ=environ))
    return server


def serve(data=None, *, environ=None):
    """Run the server until interrupted; returns a process exit code."""
    try:
        server = make_server(data, environ=environ)
    except WebUIServerError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    host, port = server.server_address[:2]
    print(f"webui: status server on http://{host}:{port}/ (read-only, Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv=None):
    """``python3 -m print_buddy.webui``: load settings and serve (stage 2)."""
    try:
        data = settings.load()
    except settings.SettingsError as exc:
        print(f"webui: configuration unresolved: {exc}", file=sys.stderr)
        return 2
    return serve(data)


if __name__ == "__main__":
    sys.exit(main())
