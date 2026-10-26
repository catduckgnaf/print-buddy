"""Stock Flashforge camera source: what /detail advertises, nothing assumed (#373).

Protocol facts are from the same public Flashforge API docs the LAN client
is built on (Parallel-7/flashforge-api-docs: the AD5X endpoint schemas for
firmware 1.1.7 and 1.2.1 — 3.1.0 documents the same endpoint set — the
capability matrix, and the HTTP REST API reference):

- The AD5X has **no built-in camera** (capability matrix: Built-in Camera
  "No", Camera Port (8080) "No", Aftermarket Camera "Yes"). A camera is an
  accessory; the 5M-series firmware's stream server serves it only when
  one is installed and enabled.
- ``/detail`` carries ``cameraStreamUrl`` on every model: empty when no
  camera is installed or the camera is disabled, otherwise the MJPEG
  stream URL, documented in the AD5X schema as
  ``http://<ip>:8080/?action=stream``. The printer is the only authority
  on whether it has a camera, so this module reads the field and never
  constructs a URL the printer did not advertise.
- ``streamCtrl_cmd`` (``/control``, args ``{"action": "open"|"close"}``)
  starts and stops the stream. It is accepted on the AD5X and actuates
  only when a camera is installed.
- The 8080 stream carries no credentials in any documented example; the
  serial number + check code authentication belongs to the 8898 API.

None of this is verified on a live AD5X: no Print Buddy code has yet read
a real AD5X ``cameraStreamUrl`` or frame. Until an operator confirms it on
hardware, the docs describe this as protocol-documented, not verified.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from .client import StockLanError

STREAM_CMD = "streamCtrl_cmd"


def advertised_stream_url(detail, host) -> str:
    """The camera stream URL /detail advertises, or "" when there is none.

    The URL is trusted only as far as the printer that sent it: it must be
    a plain http URL, carry no userinfo (a credential would end up in logs
    and the capture manifest), and point at the configured printer host —
    a firmware or proxy oddity advertising some other host is refused
    rather than followed.
    """
    detail = detail if isinstance(detail, dict) else {}
    raw = str(detail.get("cameraStreamUrl") or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    host = str(host or "").strip().lower()
    if parts.scheme != "http" or parts.username or parts.password:
        return ""
    if not host or (parts.hostname or "").lower() != host:
        return ""
    return raw


def stream_url_for(client, host) -> str:
    """One /detail read reduced to its advertised camera stream URL ("" if none).

    Raises StockLanError when the printer cannot be read at all; callers
    treat that as "no camera source this time", never as a print failure.
    """
    return advertised_stream_url(client.detail(), host)


def set_stream(client, action) -> None:
    """Open or close the camera stream via streamCtrl_cmd. Raises on refusal."""
    if action not in ("open", "close"):
        raise StockLanError(f"invalid stream action {action!r}")
    client.control(STREAM_CMD, {"action": action})
