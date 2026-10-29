"""Events that already have a chat post, plus one MQTT subscriber (#622).

Off unless [notify] mqtt_enabled is true and mqtt_host is set. The password
is MQTT_PASSWORD from the environment, never from YAML and never from chat.
A delivery failure is logged and does not raise, so chat and the print continue.
"""
from __future__ import annotations

import logging
import os
import socket

log = logging.getLogger("print_handy.notify")

EVENTS = ("print_started", "paused", "runout", "watchdog_offer", "complete", "failed", "spool_added")

_FROM_FORMAT = {
    "started": "print_started",
    "paused": "paused",
    "complete": "complete",
    "error": "failed",
    "cancelled": "failed",
}


def event_for(kind, extra=None) -> str:
    """The bus name for a chat format_event kind, or "" when it is not on the list."""
    if kind == "paused" and extra and "runout" in str(extra).lower():
        return "runout"
    return _FROM_FORMAT.get(kind, "")


def emit(kind, summary, *, printer_id="", connector=None) -> bool:
    """Publish one event. Returns False when MQTT is off or the publish fails.

    ``connector`` is a test seam: ``connector(host, port)`` returns an object
    with ``sendall`` and ``close``. Production uses a TCP connection.
    """
    try:
        return _emit(kind, summary, printer_id=printer_id, connector=connector)
    except Exception as exc:
        log.warning("mqtt publish failed: %s", exc)
        return False


def _settings():
    from . import settings
    data = settings.current()
    return data.get("notify") if isinstance(data, dict) else None


def _emit(kind, summary, *, printer_id, connector) -> bool:
    if kind not in EVENTS:
        return False
    cfg = _settings() or {}
    if cfg.get("mqtt_enabled") is not True:
        return False
    host = str(cfg.get("mqtt_host") or "").strip()
    if not host:
        return False
    port = int(cfg.get("mqtt_port") or 1883)
    topic_root = str(cfg.get("mqtt_topic") or "print-handy").strip("/") or "print-handy"
    topic = f"{topic_root}/{kind}"
    payload = str(summary or "").splitlines()[0][:240]
    if printer_id:
        payload = f"{printer_id}: {payload}"
    username = str(cfg.get("mqtt_username") or "")
    password = os.environ.get("MQTT_PASSWORD") or ""
    packet = _publish_packet(topic, payload, username=username, password=password)
    opener = connector or (lambda h, p: socket.create_connection((h, p), timeout=3))
    sock = opener(host, port)
    try:
        sock.sendall(packet)
    finally:
        closer = getattr(sock, "close", None)
        if closer:
            closer()
    return True


def _encode(text: str) -> bytes:
    raw = text.encode("utf-8")
    return len(raw).to_bytes(2, "big") + raw


def _rest(length: int) -> bytes:
    out = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length:
            digit |= 0x80
        out.append(digit)
        if not length:
            return bytes(out)


def _publish_packet(topic, payload, *, username="", password="") -> bytes:
    """MQTT 3.1.1 CONNECT plus one QoS 0 PUBLISH. No subscribe, no retain."""
    flags = 0x02  # clean session
    if username:
        flags |= 0x80
        if password:
            flags |= 0x40
    variable = _encode("MQTT") + bytes([4, flags]) + (60).to_bytes(2, "big") + _encode("print-handy")
    if username:
        variable += _encode(username)
        if password:
            variable += _encode(password)
    connect = bytes([0x10]) + _rest(len(variable)) + variable
    body = _encode(topic) + payload.encode("utf-8")
    publish = bytes([0x30]) + _rest(len(body)) + body
    return connect + publish
