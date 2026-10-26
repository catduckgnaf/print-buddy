"""The Discord Activity core for live camera viewing (issue #311, stage 3).

The Stage 0 audit settled the shape: Discord's official bot API cannot
send video, the custom-sender lineage is selfbot-only, and catduck chose
the Embedded App (Activity) fallback — a web page in a sandboxed iframe
inside the voice channel, served from the *same* Discord application as
the bot (no second bot). This module is the offline-buildable core of
that page's server side. It is stdlib-only and performs no I/O of its
own except through injected transports, so every behaviour is testable
offline:

- :func:`authenticate_code` — the OAuth allowlist check. The page gets
  a one-time code from the Discord client; the *server* exchanges it
  for an access token and reads ``GET /users/@me`` itself (Discord's
  networking guide is explicit: do not trust identity data coming from
  the client), then allows only the configured Discord user IDs. Deny
  is the default on every failure. Codes and access tokens are secrets
  in transit: they are never stored on the result and never appear in
  errors or logs.
- Session markers — a short-lived HMAC-signed token
  (:func:`make_session_token` / :func:`verify_session_token`) the
  server sets as a cookie after a successful exchange. The signing
  secret is never a setting: it lives in the environment variable
  :data:`SESSION_SECRET_ENV` names, the same indirection as every
  other Print Buddy secret; the Discord client secret likewise lives
  in :data:`CLIENT_SECRET_ENV`.
- :data:`ACTIVITY_PAGE` — the single self-contained page. It speaks
  go2rtc's MSE-over-WebSocket protocol on ``/api/ws`` (on MediaSource
  open it sends ``{"type": "mse", "value": [<codecs>]}``, the server
  answers with the mime type, then binary fMP4 frames are appended to
  a SourceBuffer), building the WebSocket URL from a same-origin
  relative path plus a stream-name parameter, and shows a plain
  fallback message when the feed cannot start. Everything the page
  loads is itself — strict CSP, no external hosts. How the page
  becomes reachable from Discord clients (Developer Portal URL
  mappings, a tunnel, the ``discordsays.com`` proxy) is deployment
  wiring for stage 4, not this module's concern; the audit found
  WebRTC is not supported through that proxy, which is why MSE is
  the in-Activity transport.
- :func:`make_server` — a stdlib ``http.server`` factory.
  ``GET /health`` answers openly (it reveals nothing: no stream name,
  no configuration). ``POST /api/token`` runs the code exchange and
  sets the session cookie. ``GET /`` serves the page only with a
  valid session cookie and 403 otherwise. The default bind is
  loopback; this module never publishes anything to the internet.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping, Protocol

__all__ = [
    "ACTIVITY_PAGE",
    "CLIENT_SECRET_ENV",
    "DEFAULT_STREAM_NAME",
    "SESSION_COOKIE",
    "SESSION_SECRET_ENV",
    "SESSION_TTL_S",
    "ActivityAuthError",
    "AuthResult",
    "OAuthTransport",
    "UrllibOAuthTransport",
    "authenticate_code",
    "client_secret",
    "make_server",
    "make_session_token",
    "session_secret",
    "verify_session_token",
]

TOKEN_URL = "https://discord.com/api/oauth2/token"
USER_URL = "https://discord.com/api/users/@me"
CLIENT_SECRET_ENV = "DISCORD_CLIENT_SECRET"
SESSION_SECRET_ENV = "LIVE_STREAM_SESSION_SECRET"
SESSION_COOKIE = "pb_live_session"
SESSION_TTL_S = 3600
DEFAULT_STREAM_NAME = "printer"
_MAX_TOKEN_BODY = 4096

_PAGE_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
             "connect-src 'self' ws: wss:; media-src 'self' blob:; img-src 'self' data:; "
             "base-uri 'none'; form-action 'none'")


class ActivityAuthError(RuntimeError):
    """The Activity sign-in was refused. Messages never carry the code or any token."""


@dataclass(frozen=True)
class AuthResult:
    """An allowlisted Discord identity. Deliberately holds no token."""

    user_id: str
    username: str = ""


class OAuthTransport(Protocol):
    """The two Discord calls the auth check needs, injected for tests."""

    def exchange_code(self, code: str) -> str:
        """Trade the one-time OAuth code for an access token, or raise."""
        ...

    def fetch_user(self, access_token: str) -> Mapping:
        """GET /users/@me with the token, as a mapping, or raise."""
        ...


class UrllibOAuthTransport:
    """The production transport: stdlib urllib against discord.com.

    The client secret comes from the environment (see
    :func:`client_secret`), never from a settings file. Response bodies
    are never included in errors — a Discord error body is not needed to
    refuse a sign-in, and the discipline keeps codes and tokens out of
    logs by construction.
    """

    def __init__(self, client_id, client_secret_value, *, opener=None, timeout=10):
        self.client_id = str(client_id)
        self._client_secret = str(client_secret_value)
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout

    def exchange_code(self, code):
        body = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self._client_secret,
            "grant_type": "authorization_code",
            "code": code,
        }).encode()
        request = urllib.request.Request(
            TOKEN_URL, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except Exception:
            raise ActivityAuthError("the Discord sign-in exchange failed") from None
        token = str((payload or {}).get("access_token") or "")
        if not token:
            raise ActivityAuthError("the Discord sign-in exchange failed")
        return token

    def fetch_user(self, access_token):
        request = urllib.request.Request(
            USER_URL, headers={"Authorization": f"Bearer {access_token}"})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except Exception:
            raise ActivityAuthError("the Discord profile could not be read") from None
        if not isinstance(payload, Mapping):
            raise ActivityAuthError("the Discord profile could not be read")
        return payload


def client_secret(environ=None, env_name=CLIENT_SECRET_ENV):
    """The Discord application's client secret *value* from the environment ("" if unset)."""
    environ = os.environ if environ is None else environ
    return environ.get(env_name) or ""


def authenticate_code(code, *, transport, allowlist):
    """Allow only an allowlisted Discord user, checked server-side.

    `transport` is an :class:`OAuthTransport`; `allowlist` is an
    iterable of Discord user IDs (the ``[discord] approval_user_id``
    and ``allowed_user_ids`` the deployment chooses). Every failure —
    no code, an empty allowlist, a refused exchange, an unreadable
    profile, an ID that is not listed — raises
    :class:`ActivityAuthError` with a message that contains neither
    the code nor the access token.
    """
    code = str(code or "").strip()
    allowed = {str(user).strip() for user in (allowlist or ()) if str(user).strip()}
    if not code:
        raise ActivityAuthError("no sign-in code was provided")
    if not allowed:
        raise ActivityAuthError("no Discord user is on the live view allowlist")
    try:
        token = transport.exchange_code(code)
    except ActivityAuthError:
        raise
    except Exception:
        raise ActivityAuthError("the Discord sign-in exchange failed") from None
    if not token:
        raise ActivityAuthError("the Discord sign-in exchange failed")
    try:
        user = transport.fetch_user(token)
    except ActivityAuthError:
        raise
    except Exception:
        raise ActivityAuthError("the Discord profile could not be read") from None
    user_id = str((user or {}).get("id") or "").strip()
    if not user_id:
        raise ActivityAuthError("the Discord profile could not be read")
    if user_id not in allowed:
        raise ActivityAuthError("this Discord account is not on the live view allowlist")
    return AuthResult(user_id=user_id, username=str(user.get("username") or ""))


# --------------------------------------------------------------------- session markers

def session_secret(environ=None, env_name=SESSION_SECRET_ENV):
    """The session signing secret as bytes, from the environment (b"" if unset)."""
    environ = os.environ if environ is None else environ
    return (environ.get(env_name) or "").encode()


def _sign(payload, secret):
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def make_session_token(user_id, *, secret, now, ttl_s=SESSION_TTL_S):
    """A signed ``<user_id>.<expiry>.<hmac>`` marker for one allowlisted user."""
    user_id = str(user_id or "").strip()
    if not user_id or "." in user_id:
        raise ActivityAuthError("a session marker needs a plain Discord user ID")
    if not secret:
        raise ActivityAuthError("the live session secret is not configured")
    expiry = int(now) + int(ttl_s)
    payload = f"{user_id}.{expiry}"
    return f"{payload}.{_sign(payload, secret)}"


def verify_session_token(token, *, secret, now):
    """The user ID a session marker proves, or None for anything invalid or expired."""
    if not token or not secret:
        return None
    parts = str(token).split(".")
    if len(parts) != 3:
        return None
    user_id, expiry, signature = parts
    if not user_id or not hmac.compare_digest(signature, _sign(f"{user_id}.{expiry}", secret)):
        return None
    try:
        expiry_s = int(expiry)
    except ValueError:
        return None
    if float(now) >= expiry_s:
        return None
    return user_id


# --------------------------------------------------------------------- the page

ACTIVITY_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Print Buddy live camera</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 1rem; background: #1e1f22; color: #f2f3f5; }
  video { width: 100%; max-height: 80vh; background: #000; }
  #status { padding: 0.75rem; border: 1px solid #4e5058; border-radius: 6px; }
</style>
</head>
<body>
<h1>Printer camera</h1>
<video id="feed" autoplay muted playsinline></video>
<p id="status" hidden></p>
<script>
(function () {
  "use strict";
  var status = document.getElementById("status");
  var video = document.getElementById("feed");
  function unavailable(message) {
    status.textContent = message;
    status.hidden = false;
  }
  var params = new URLSearchParams(location.search);
  var stream = (params.get("src") || "printer").replace(/[^A-Za-z0-9_-]/g, "");
  if (!stream) {
    unavailable("No camera stream was named for this page.");
    return;
  }
  if (!("MediaSource" in window) || !("WebSocket" in window)) {
    unavailable("This Discord client cannot play the live feed (MediaSource is unavailable).");
    return;
  }
  // go2rtc MSE over WebSocket, on the same origin this page was served
  // from: ws(s)://<host>/api/ws?src=<stream>. On MediaSource open the
  // client offers its codecs as {"type": "mse", "value": [<codecs>]};
  // go2rtc answers with the mime type to build the SourceBuffer with,
  // then sends binary fMP4 frames. Any failure lands on the plain
  // fallback message below; the watchdog snapshots in chat keep working.
  var scheme = location.protocol === "https:" ? "wss:" : "ws:";
  var url = scheme + "//" + location.host + "/api/ws?src=" + encodeURIComponent(stream);
  var codecs = ['video/mp4; codecs="avc1.64001f,mp4a.40.2"',
                'video/mp4; codecs="avc1.42e01f,mp4a.40.2"'];
  var ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";
  var mediaSource = new MediaSource();
  video.src = URL.createObjectURL(mediaSource);
  var buffer = null;
  var queue = [];
  function append(chunk) {
    if (!buffer) { return; }
    if (buffer.updating || queue.length) { queue.push(chunk); }
    else { buffer.appendBuffer(chunk); }
  }
  mediaSource.addEventListener("sourceopen", function () {
    ws.send(JSON.stringify({type: "mse", value: codecs}));
  });
  ws.onmessage = function (event) {
    if (typeof event.data === "string") {
      var message;
      try { message = JSON.parse(event.data); } catch (e) { return; }
      if (message.type === "mse" && !buffer) {
        try {
          buffer = mediaSource.addSourceBuffer(message.value);
          buffer.addEventListener("updateend", function () {
            if (queue.length && !buffer.updating) { buffer.appendBuffer(queue.shift()); }
          });
        } catch (e) {
          unavailable("The live feed's format is not playable in this Discord client.");
          ws.close();
        }
      } else if (message.type === "error") {
        unavailable("The camera feed is unavailable right now. Nothing is wrong with the print; try again in a moment.");
      }
      return;
    }
    append(event.data);
  };
  ws.onerror = function () {
    if (!buffer) {
      unavailable("The camera feed could not be reached. Nothing is wrong with the print; try again in a moment.");
    }
  };
  ws.onclose = function () {
    if (!buffer) {
      unavailable("The camera feed is unavailable right now. Nothing is wrong with the print; try again in a moment.");
    }
  };
})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------- the HTTP surface

def make_handler(*, transport, allowlist, secret, page=ACTIVITY_PAGE, clock=time.time):
    """A BaseHTTPRequestHandler class bound to the given auth pieces.

    Routes: ``GET /health`` (open; reveals nothing), ``POST /api/token``
    (the OAuth exchange; sets the session cookie on success, 403 on any
    refusal), ``GET /`` (the page, with a valid session cookie only,
    403 otherwise). Everything else is 404, and other methods are 405.
    Request logging is silenced: request lines can carry codes and
    cookies, and neither belongs in a log.
    """

    class ActivityHandler(BaseHTTPRequestHandler):
        server_version = "PrintBuddyLive/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            pass

        # ---------------------------------------------------------- plumbing

        def _send(self, status, body, content_type, extra=()):
            payload = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in extra:
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def _json(self, status, payload, extra=()):
            self._send(status, json.dumps(payload), "application/json", extra)

        def _session_user(self):
            header = self.headers.get("Cookie") or ""
            for part in header.split(";"):
                name, _, value = part.strip().partition("=")
                if name == SESSION_COOKIE and value:
                    return verify_session_token(value, secret=secret, now=clock())
            return None

        # ---------------------------------------------------------- routes

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/health":
                self._json(200, {"ok": True, "service": "print-buddy-live"})
                return
            if path == "/":
                if self._session_user() is None:
                    self._send(403, "Not authorised. Open the Print Buddy activity "
                                    "from the Discord voice channel and sign in there.",
                               "text/plain; charset=utf-8")
                    return
                self._send(200, page, "text/html; charset=utf-8",
                           extra=(("Content-Security-Policy", _PAGE_CSP),))
                return
            self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path != "/api/token":
                self._json(404, {"ok": False, "error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if 0 < length <= _MAX_TOKEN_BODY else b""
            code = ""
            if raw:
                try:
                    code = str(json.loads(raw).get("code") or "")
                except (ValueError, AttributeError):
                    form = urllib.parse.parse_qs(raw.decode("utf-8", "replace"))
                    code = (form.get("code") or [""])[0]
            try:
                result = authenticate_code(code, transport=transport, allowlist=allowlist)
                marker = make_session_token(result.user_id, secret=secret, now=clock())
            except ActivityAuthError as exc:
                self._json(403, {"ok": False, "error": str(exc)})
                return
            cookie = (f"{SESSION_COOKIE}={marker}; Path=/; HttpOnly; Secure; "
                      "SameSite=None; Partitioned")
            self._json(200, {"ok": True, "user_id": result.user_id},
                       extra=(("Set-Cookie", cookie),))

        def _method_not_allowed(self):
            self._json(405, {"ok": False, "error": "method not allowed"})

        do_PUT = _method_not_allowed
        do_DELETE = _method_not_allowed
        do_PATCH = _method_not_allowed

    return ActivityHandler


def make_server(host="127.0.0.1", port=0, **handler_kwargs):
    """A ThreadingHTTPServer for the Activity core; loopback unless told otherwise.

    The caller runs ``serve_forever`` (a later stage supervises it).
    Binding anything beyond loopback is deployment wiring (stage 4)
    and goes through the Discord proxy/tunnel design, never a bare
    public bind of this server.
    """
    return ThreadingHTTPServer((host, port), make_handler(**handler_kwargs))
