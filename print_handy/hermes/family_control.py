"""Start/pause parity for the non-Moonraker printer families (#460).

One shared mechanism, not five copies. Moonraker has had the full event
contract all along — start posts (launched and external), pause posts
with Resume/Cancel buttons, chat resume/cancel — from its domain
listener plus ``print_control`` / ``print_stop``. Every other family had
only a launched-print monitor that posts the terminal post and treats
"paused" as a silent active state. This module is the shared machinery
that closes that gap:

- ``FamilyControl`` — resume/cancel for one family's printer through the
  family's *own* adapter ``control()`` operation, with the same
  discipline the Moonraker paths use: re-read the state first, refuse
  when the state no longer matches, refuse when a different file is
  loaded than the one the operator confirmed, send at most one command,
  then report what the read-back actually shows. Nothing here ever
  points the Moonraker transport at a non-Moonraker endpoint.
- The pause-alert posting path (``post_pause_alert`` /
  ``retire_pause_alerts`` / ``PauseAlerts``) — the same Discord button
  alert the Moonraker listener posts (``print_alert_buttons``), with the
  alert record carrying its connection (and roster printer id) so the
  gateway's click handler can route the press back here instead of to
  the Moonraker control path.
- ``status_fn_for`` — the one place that knows how each family's
  adapter reads a normalised status (the same reads the launched-print
  monitors poll), shared by the control path, the monitors and the
  polling listener domains.
- ``BambuEventSink`` — the consumer that wires the Bambu domain
  listener's already-detected transitions (#299 Stage B) to these
  posts. The listener detected pauses all along; its sink was log-only.

Who posts what, per print — exactly one owner for each post:

- A print Print Handy launched is claimed by the print path
  (``model_job.claim_start_announcement``, the same claim the Moonraker
  listener honours): its pause alerts come from its launched-print
  monitor (``PauseAlerts``), its start confirmation and completion from
  the print path and the monitor, exactly as before this change.
- A print started outside Print Handy has no monitor: the family's
  listener domain (the Bambu listener's sink, or
  ``family_event_listener`` for the polling families) posts its start,
  its pause alerts and its completion, and retires its pause alerts
  when it ends.
- The listener retires pause alerts at a print's end even for claimed
  prints: retiring is idempotent (the alert record is claimed under a
  lock by whoever retires first), and it covers the case where the
  monitor that posted the alert is gone by the time the print ends.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .. import logs
from . import discord_print_summary as print_summary

logger = logging.getLogger(__name__)

# The families this module serves: every connection with an adapter
# control surface and no Moonraker transport. Moonraker keeps its own
# listener/control path (the reference); offline has no printer contact.
FAMILY_CONNECTIONS = ("bambulab_lan", "prusalink", "elegoo_sdcp",
                      "flashforge_stock", "octoprint")

ACTIVE = ("printing", "paused")
# States a print ends in, as the adapters' normalised statuses name them.
# "standby" is a terminal observation too: a print that returns to standby
# without a terminal state was stopped at the printer (#370's rule).
TERMINAL_STATES = ("complete", "cancelled", "error", "standby")

_RETIRE_HEADLINES = {
    "complete": "Print complete.",
    "cancelled": "Print cancelled.",
    "error": "Print stopped with an error.",
    "standby": "Print ended at the printer.",
}


def log(line):
    logger.info("%s", logs.redact(str(line)))


def connection_of(adapter) -> str | None:
    """An adapter's connection, asked the way the rest of the codebase asks.

    Adapters have no ``vendor`` attribute: the connection is the
    adapter's ``connection`` property (the vendor profile's connection),
    with the adapter's ``transport`` as the fallback (#409).
    """
    return getattr(adapter, "connection", None) or getattr(adapter, "transport", None)


def status_fn_for(adapter):
    """A zero-arg callable returning the adapter's normalised status.

    The one place that knows each family's raw status read — the same
    reads the launched-print monitors poll in their ``start_monitor``.
    The client is built per call, as ``print_stop.status`` does for
    Bambu: a control click or a listener poll never holds a stale
    client, and an unconfigured family raises here, where the caller
    treats it as a failed read.
    """
    connection = connection_of(adapter)
    if connection == "bambulab_lan":
        return lambda: adapter.normalize_status(adapter.client().snapshot())
    if connection == "prusalink":
        return lambda: adapter.normalize_status(adapter.client().snapshot())
    if connection == "elegoo_sdcp":
        return lambda: adapter.normalize_status(adapter.client().status())
    if connection == "octoprint":
        return lambda: adapter.normalize_status(adapter.client().status())
    if connection == "flashforge_stock":
        return lambda: adapter.normalize_status(adapter.client().detail())
    raise ValueError(f"no normalised status read for connection {connection!r}")


def adapter_for(printer_id: str | None = None):
    """The configured printer's adapter, or one roster entry's (#335)."""
    from print_handy import printers
    if not printer_id:
        return printers.current()
    from print_handy import settings
    return printers.get(settings.by_id(printer_id)["model"], settings.view_for(printer_id))


class FamilyControl:
    """Resume/cancel for one non-Moonraker printer, through its own adapter.

    Mirrors ``print_control.resume`` / ``print_stop.cancel``: re-read
    first, one command at most, read back, truthful text. State and
    filename checks run against the family's normalised status; where a
    family's status carries no filename, the filename check degrades to
    the state check alone (the same both-known rule the monitors use).
    """

    def __init__(self, adapter, *, status_fn=None, sleep=time.sleep):
        self.adapter = adapter
        self.connection = connection_of(adapter)
        self._status_fn = status_fn or status_fn_for(adapter)
        self._sleep = sleep

    def status(self) -> dict[str, Any]:
        return self._status_fn()

    def resume(self, expected_filename: str = "", wait_s: float = 20,
               poll_s: float = 1.0) -> tuple[bool, str]:
        """One resume for the confirmed paused file, then read back. Never retried."""
        before = self.status()
        state = str(before.get("state") or "unknown")
        if state == "printing":
            return False, "Nothing to resume: it's already printing. Nothing sent."
        if state != "paused":
            return False, f"Nothing paused to resume (printer is {state}). Nothing sent."
        if expected_filename and before.get("filename") and before["filename"] != expected_filename:
            return False, "A different print is paused than the one in this alert. Nothing sent."
        self.adapter.control("resume")
        deadline = time.monotonic() + wait_s
        after = before
        while time.monotonic() < deadline:
            self._sleep(poll_s)
            try:
                after = self.status()
            except Exception:
                continue
            if after.get("state") == "printing":
                break
        if after.get("state") == "printing":
            where = where_text(after)
            return True, f"Resumed. Printer now reports printing{', ' + where if where else ''}."
        return True, (f"Resume sent, but the printer still reports {after.get('state')} "
                      f"after {wait_s:.0f}s. Check the printer screen. Not retrying.")

    def cancel(self, expected_filename: str = "", wait_s: float = 20,
               poll_s: float = 1.0) -> tuple[bool, str]:
        """One cancel, only if the same file is still printing or paused. Never retried."""
        before = self.status()
        state = str(before.get("state") or "unknown")
        if state not in ACTIVE:
            return False, f"Nothing to stop: printer is {state}. Nothing sent."
        if expected_filename and before.get("filename") and before["filename"] != expected_filename:
            return False, "A different print is running now than the one in this alert. Nothing sent."
        self.adapter.control("stop")
        deadline = time.monotonic() + wait_s
        after = before
        while time.monotonic() < deadline:
            self._sleep(poll_s)
            try:
                after = self.status()
            except Exception:
                continue
            if after.get("state") not in ACTIVE:
                break
        if after.get("state") in ACTIVE:
            return True, (f"Cancel sent, but the printer still reports {after['state']} "
                          f"after {wait_s:.0f}s. Check the printer screen. Not retrying.")
        if self.connection == "bambulab_lan" and after.get("state") == "error":
            # A Bambu printer reports a stopped job as FAILED until the
            # operator clears it on the screen (print_stop.cancel's rule).
            return True, ("Stopped. The printer shows the cancelled job as an error "
                          "until you acknowledge it on its screen.")
        return True, f"Stopped. Printer now reports {after.get('state')}."


def control_for(printer_id: str | None = None) -> FamilyControl | None:
    """The family control for the configured (or one roster) printer.

    None when the printer is not one of the parity families — Moonraker
    keeps its own control path, and offline never contacts the printer.
    """
    adapter = adapter_for(printer_id)
    if connection_of(adapter) not in FAMILY_CONNECTIONS:
        return None
    return FamilyControl(adapter)


def where_text(st: dict[str, Any]) -> str:
    """'layer 12/240, 42% done' from a normalised status; '' when unknown."""
    bits = []
    if st.get("layer") and st.get("total_layer"):
        bits.append(f"layer {st['layer']}/{st['total_layer']}")
    if isinstance(st.get("progress"), (int, float)) and st["progress"]:
        bits.append(f"{st['progress'] * 100:.0f}% done")
    return ", ".join(bits)


# --------------------------------------------------------------------- posts

def _mel():
    from . import moonraker_event_listener as mel
    return mel


def paused_text(filename: str, status: dict[str, Any] | None = None) -> str:
    """The family pause alert text: the shared 'paused' format_event shape.

    The Moonraker alert adds its where clause from print_stop.status();
    here the where comes from the family's normalised status the caller
    already read. No typed commands are named: /print-resume and
    /print-stop are Moonraker-shaped, so the text points at the buttons
    and the printer screen only.
    """
    where = where_text(status) if status else ""
    extra = (f"Paused at {where}. " if where else "") + \
        "Fix it at the printer, then tap Resume or Cancel below."
    return print_summary.format_event("paused", filename, extra=extra)


def post_pause_alert(filename: str, connection: str, printer_id: str | None = None,
                     status: dict[str, Any] | None = None) -> bool:
    """Post one pause alert with Resume/Cancel buttons, Moonraker-shaped.

    The alert record carries the connection (and roster printer id), so
    ``print_alert_buttons.handle_click`` routes a press to this family's
    control instead of the Moonraker path. On buttonless standalone
    platforms (Telegram/Matrix) the alert is plain text, exactly as the
    Moonraker listener's post_alert behaves there; a failed button post
    falls back to plain text the same way.
    """
    mel = _mel()
    text = paused_text(filename, status)
    if mel._buttonless_standalone():
        return mel.post(text)
    try:
        from . import moonraker_discord_announcements as announcer
        from . import print_alert_buttons as pab
        if pab.post_with_buttons(mel._bot_token(), announcer.DISCORD_CHAT_ID,
                                 text, "paused", filename,
                                 connection=connection, printer_id=printer_id):
            log(f"post buttons kind=paused family={connection} {text.splitlines()[0][:120]!r}")
            return True
        log("family button post failed; falling back to plain text")
    except Exception as exc:
        log(f"family button post error: {exc!r}")
    return mel.post(text)


def retire_pause_alerts(filename: str | None, headline: str = "Print ended.") -> int:
    """Strip the buttons from this job's live pause alerts and say why (#370's rule)."""
    mel = _mel()
    if mel._buttonless_standalone():
        return 0
    try:
        from . import print_alert_buttons as pab
        return pab.retire_alerts(
            mel._bot_token(), filename,
            "This paused prompt is closed; its buttons no longer act on a live job.",
            ("paused",), headline=headline)
    except Exception as exc:
        log(f"retire family paused prompt failed file={filename!r}: {exc!r}")
        return 0


def retire_headline(state: str) -> str:
    """The retire headline for a terminal state, mirroring the Moonraker listener's."""
    return _RETIRE_HEADLINES.get(str(state or ""), "Print ended.")


def post_family_event(kind: str, filename: str) -> bool:
    """A plain lifecycle post (start / terminal) in the shared format_event shape."""
    return _mel().post(print_summary.format_event(kind, filename))


class PauseAlerts:
    """Transition tracker a launched-print monitor feeds its polls into.

    The monitor owns its launched print's pause alerts: a printing ->
    paused transition posts exactly one alert (per pause episode), and
    the terminal transition retires the print's alerts so no stale
    Resume/Cancel buttons outlive the job. A resume at the printer
    leaves the alert live, exactly as the Moonraker listener leaves
    its: the buttons re-read state on a press and refuse truthfully.
    Repeated polls of the same state post nothing. Never raises.
    """

    def __init__(self, filename, connection, printer_id=None, *, poster=None, retirer=None):
        self.filename = filename or ""
        self.connection = connection
        self.printer_id = printer_id
        self._poster = poster or post_pause_alert
        self._retirer = retirer or retire_pause_alerts
        self._prev: str | None = None

    def note(self, state, status=None):
        state = str(state or "unknown")
        prev, self._prev = self._prev, state
        if prev is None:
            return  # the first observation is a baseline, never a transition
        if state == "paused" and prev == "printing":
            try:
                self._poster(self.filename, self.connection, self.printer_id, status)
            except Exception as exc:
                log(f"pause alert post failed file={self.filename!r}: {exc!r}")
        elif prev in ACTIVE and state in TERMINAL_STATES:
            try:
                self._retirer(self.filename, retire_headline(state))
            except Exception as exc:
                log(f"pause alert retire failed file={self.filename!r}: {exc!r}")


def pause_alerts_for(adapter, filename, printer_id=None) -> PauseAlerts | None:
    """A PauseAlerts for a monitor's adapter, or None for non-family printers."""
    connection = connection_of(adapter)
    if connection not in FAMILY_CONNECTIONS:
        return None
    if printer_id is None:
        from .. import listeners
        printer_id = listeners.instance_printer_id()
    return PauseAlerts(filename, connection, printer_id)


# ------------------------------------------------------------- Bambu sink

class BambuEventSink:
    """Posts the Bambu domain listener's transitions for external prints.

    The Bambu listener (#299 Stage B) detected started / paused /
    resumed / cancelled / completion / error all along, but its events
    went to a log. This sink is the consumer ``main()`` wires in: for a
    print started outside Print Handy (no start claim from the print
    path) it posts the start, the pause alerts and the terminal post —
    the Moonraker listener's contract. A claimed (Print Handy-launched)
    print is the launched-print monitor's: the sink stays silent for it
    and only retires its pause alerts when it ends.

    Baseline rule, the Moonraker listener's own: a print already active
    when this sink first observes the printer is never classified — no
    start post, no pause post, no terminal post for it. Only a start
    transition witnessed after an observed inactive state classifies a
    print, via the same start-claim file the Moonraker listener reads.
    """

    def __init__(self, *, claim_fn=None, start_poster=None, pause_poster=None,
                 terminal_poster=None, retirer=None, printer_id=None):
        self._claim_fn = claim_fn
        self._start_poster = start_poster or post_family_event
        self._pause_poster = pause_poster or post_pause_alert
        self._terminal_poster = terminal_poster or post_family_event
        self._retirer = retirer or retire_pause_alerts
        self._printer_id = printer_id
        self._saw_inactive = False
        self._external: set[str] = set()

    def _claimed(self, filename) -> bool:
        if self._claim_fn is not None:
            return bool(self._claim_fn(filename))
        return bool(_mel().start_claimed(filename))

    def __call__(self, kind, event):
        status = (event or {}).get("status") or {}
        filename = status.get("filename") or ""
        state = str(status.get("state") or "unknown")
        transition = (event or {}).get("transition")
        try:
            if kind == "status":
                if state in TERMINAL_STATES or state == "unknown":
                    self._saw_inactive = True
                if transition == "started" and filename:
                    if self._saw_inactive and not self._claimed(filename):
                        self._external.add(filename)
                        self._start_poster("started", filename)
                    else:
                        self._external.discard(filename)
                elif transition == "paused" and filename in self._external:
                    self._pause_poster(filename, "bambulab_lan", self._printer_id, status)
                elif transition == "cancelled" and filename:
                    self._terminal(filename, "cancelled")
            elif kind == "completion" and filename:
                self._terminal(filename, "complete")
            elif kind == "error" and filename:
                self._terminal(filename, "error")
        except Exception as exc:
            log(f"bambu event sink failed kind={kind} file={filename!r}: {exc!r}")

    def _terminal(self, filename, kind):
        external = filename in self._external
        self._external.discard(filename)
        self._saw_inactive = True
        if external:
            self._terminal_poster(kind, filename)
        self._retirer(filename, retire_headline(
            "complete" if kind == "complete" else kind))


def bambu_event_sink(printer_id=None) -> BambuEventSink:
    """The sink the Bambu listener's main() wires as its emit target."""
    return BambuEventSink(printer_id=printer_id)
