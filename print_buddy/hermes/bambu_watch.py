"""Bambu camera parity: status images, and a launched-print monitor (#294).

Bambu printers have no Moonraker listener (#256 keeps the listener
Moonraker-only), so the places the Moonraker path shows a camera image —
status, the completion post, and the camera watchdog — are served here
instead, from the Bambu LAN path itself:

- ``status_camera()`` is the on-demand piece: one snapshot from the
  configured printer's camera (printers/bambulab/camera.py), saved as a
  frame file a chat post can attach, or a plain note saying why not. It
  never raises: a status answer must not fail because a camera did.
- ``BambuPrintMonitor`` watches one print Print Buddy itself launched
  (started by the print path in core/model_job._print_bambu on a confirmed
  start): it polls the printer's normalised status on the adapter, and
  when the print reaches a terminal state it makes the completion post —
  the same format_event text the Moonraker path uses — carrying the final
  camera snapshot through the MEDIA: marker when one could be taken.

The monitor runs on a daemon thread inside whichever process launched the
print (normally the bot). It is deliberately not a supervised process and
keeps no state on disk: if that process restarts mid-print, monitoring
stops with it — a stated limitation (docs/BAMBU-LAB.md), not a silent one.
Prints started outside Print Buddy are never watched, for the same reason:
nothing here polls a printer nobody launched a print on.

Everything network- or chat-shaped is injectable (status_fn, camera_fn,
post) so the whole lifecycle is testable offline with fakes.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from .. import logs
from . import _config
from . import discord_print_summary as print_summary

logger = logging.getLogger(__name__)

POLL_S = 30.0
MAX_MONITOR_S = 48 * 3600.0
_ACTIVE = ("printing", "paused")
_TERMINAL = {"complete": "complete", "cancelled": "cancelled", "error": "error", "standby": "complete"}


def log(line):
    logger.info("%s", logs.redact(str(line)))


def write_frame(filename, image) -> Path:
    """Save one camera frame where chat posts can attach it (the listener's frame dir)."""
    target = Path(os.environ.get("PRINT_WATCH_FRAME_DIR") or _config.cache_dir() / "print-watch")
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{int(time.time())}-{Path(filename or 'print').stem}.jpg"
    path.write_bytes(image)
    return path


def status_camera(adapter):
    """(frame path, note) for the configured Bambu printer's camera. Never raises.

    On success the note is empty. On any failure — LAN not configured, a
    model whose camera path has not landed, an unreachable camera — the
    path is None and the note is the camera layer's own plain-language
    error (which never carries the access code).
    """
    try:
        image = adapter.camera_snapshot()
    except Exception as exc:
        return None, str(exc)
    try:
        return write_frame("bambu-camera", image), ""
    except Exception as exc:
        return None, f"the camera image could not be saved: {exc}"


def status_with_camera(adapter) -> dict:
    """The Bambu status snapshot, with the camera image alongside it (#294 stage 2).

    Mirrors print_stop.status()'s Bambu shape. The camera is best-effort:
    its outcome lands in `camera_note` (empty on success), and
    `camera_image_path` names the saved frame when one was taken. With no
    LAN host configured this returns the status-only answer plus the
    "camera is not configured" note instead of raising.
    """
    if not adapter.lan_configured():
        return {"state": "unknown", "filename": "", "layer": None, "total_layer": None,
                "progress": None, "print_duration": None, "camera_image_path": None,
                "camera_note": "camera is not configured: set [bambu] lan_host and lan_serial and "
                               "supply the LAN access code via the environment to see camera images"}
    live = adapter.normalize_status(adapter.client().snapshot())
    st = {"state": str(live.get("state") or "unknown"), "filename": live.get("filename") or "",
          "layer": live.get("layer"), "total_layer": live.get("total_layer"),
          "progress": live.get("progress"), "print_duration": None}
    path, note = status_camera(adapter)
    st["camera_image_path"] = str(path) if path else None
    st["camera_note"] = note
    return st


class BambuPrintMonitor:
    """Poll one launched Bambu print to its end; post its completion, with the final image.

    Alert-only by construction: the monitor reads status and the camera and
    posts to chat. It holds no printer-control callable at all — the
    watchdog's Pause is the operator pressing the alert's button, which the
    gateway routes to the adapter's control("pause") (print_stop.pause).
    """

    def __init__(self, filename, *, status_fn, camera_fn, post,
                 clock=time.monotonic, wall=time.time, sleep=time.sleep, poll_s=POLL_S):
        self.filename = filename or ""
        self._status_fn = status_fn
        self._camera_fn = camera_fn
        self._post = post
        self._clock = clock
        self._wall = wall
        self._sleep = sleep
        self._poll_s = poll_s
        self.outcome = None

    def _terminal_post(self, state):
        kind = _TERMINAL[state]
        text = print_summary.format_event(kind, self.filename)
        try:
            image = self._camera_fn()
            path = write_frame(self.filename, image)
            self._post(text + f"\n{path}\nMEDIA:{path}")
        except Exception as exc:
            log(f"bambu completion image unavailable for {self.filename!r}: {exc!r}")
            self._post(text)
        return kind

    def run(self):
        """Poll until the launched print ends. Returns the terminal kind, or None."""
        started = self._clock()
        seen_active = False
        while self._clock() - started <= MAX_MONITOR_S:
            try:
                st = self._status_fn()
            except Exception as exc:
                log(f"bambu monitor status read failed for {self.filename!r}: {exc!r}")
                self._sleep(self._poll_s)
                continue
            state = str(st.get("state") or "unknown")
            fname = st.get("filename") or ""
            if state in _ACTIVE:
                if fname and self.filename and fname != self.filename:
                    log(f"bambu monitor: a different print {fname!r} is running; {self.filename!r} is gone")
                    return None
                seen_active = True
                self.poll_active(st)
            elif state in _TERMINAL:
                if seen_active or not self.filename or fname == self.filename:
                    self.outcome = self._terminal_post(state)
                    return self.outcome
                return None
            self._sleep(self._poll_s)
        log(f"bambu monitor gave up on {self.filename!r} after {MAX_MONITOR_S / 3600:g}h without a terminal state")
        return None

    def poll_active(self, st):
        """One active-print poll. The camera watchdog hooks in here (#294 stage 3)."""


def _default_post(message):
    from . import moonraker_event_listener as mel
    return mel.post(message)


def _post_target_configured():
    """True when a completion post would have somewhere to go.

    Mirrors the listener post path's own checks: in standalone mode the
    configured platform's chat, otherwise the announcer's Discord chat.
    A print launched with no chat configured (a CLI run, a test) gets no
    monitor — there is nobody to post the completion or alerts to.
    """
    try:
        from . import moonraker_event_listener as mel
        if _config.standalone():
            platform = str(_config.cfg()["bot"].get("platform") or "discord")
            if platform == "telegram":
                return bool(mel._telegram_chat_id())
            if platform == "matrix":
                return bool(mel._matrix_room_id())
        from . import moonraker_discord_announcements as announcer
        return bool(announcer.DISCORD_CHAT_ID)
    except Exception:
        return False


def start_monitor(adapter, filename, *, post=None, camera_fn=None, status_fn=None, thread_factory=None):
    """Start a BambuPrintMonitor for a just-launched print on a daemon thread.

    Returns the thread (or None when monitoring could not start — a failed
    monitor must never fail the print that launched it).
    """
    if post is None and status_fn is None and camera_fn is None and not _post_target_configured():
        log(f"bambu monitor not started for {filename!r}: no chat is configured to post to")
        return None
    try:
        monitor = BambuPrintMonitor(
            filename,
            status_fn=status_fn or (lambda: adapter.normalize_status(adapter.client().snapshot())),
            camera_fn=camera_fn or adapter.camera_snapshot,
            post=post or _default_post)
        factory = thread_factory or (lambda target: threading.Thread(target=target, daemon=True,
                                                                     name=f"bambu-watch-{filename}"))
        thread = factory(monitor.run)
        thread.start()
        return thread
    except Exception as exc:
        log(f"bambu monitor could not start for {filename!r}: {exc!r}")
        return None
