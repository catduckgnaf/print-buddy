"""Guided physical nozzle change (#513).

Backs ``/nozzle change`` in the print-feedback plugin. The procedure mirrors
the cold pull's safety posture in :mod:`print_handy.hermes.print_control`:

* Heating is a physical printer action. It happens only after an explicit,
  fresh operator confirmation (5-minute window, captured *after* the button
  press), only while Klipper reports an idle job state, and under the same
  one-control-action-at-a-time lock discipline (its own lock here).
* The supported live-heat path is a Moonraker/Klipper printer, through the
  existing Moonraker client in ``print_control._send`` (``M104`` via
  ``/printer/gcode/script``) — no new raw transport is invented. Printers on
  other connections (Bambu LAN, PrusaLink, SDCP, stock FlashForge, OctoPrint)
  degrade gracefully: the flow gives a manual-heat instruction and waits for
  the operator's step confirmation instead of sending anything.
* Every heating step turns the heater back off on failure paths where that
  is possible, and the cooldown step refuses to declare completion until a
  live readback says the extruder is below the safe temperature — a timeout
  is reported as "still hot, check the printer", never as success.
* Completing the change records the new nozzle in ``printer_hardware.json``
  through :func:`record_nozzle_change`, which applies exactly the
  calibration invalidation ``printer_state set --nozzle`` applies (previous
  calibration is historical only, pressure advance marked stale) and leaves
  an explicit ``calibration_pending`` list for the post-change prompts.

Nothing in this module runs on import, and every printer-touching function
takes injectable sender/reader callables so tests never contact a printer.
"""

from __future__ import annotations

import datetime
import threading
import time
from typing import Any, Callable

# Diameters/materials the guided flow offers (issue #513 §1). Validation
# itself goes through nozzle.validate_nozzle_setting against the printer's
# supported sets when they are known.
GUIDED_DIAMETERS_MM: tuple[float, ...] = (0.2, 0.4, 0.6, 0.8)
GUIDED_TYPES: tuple[str, ...] = (
    "brass",
    "hardened_steel",
    "stainless_steel",
    "tungsten_carbide",
    "diamond",
)

LOOSEN_TEMP_C = 250          # hot-loosen / hot-torque temperature (issue §1)
SAFE_TEMP_C = 50             # cooldown completes only below this readback
CONFIRM_WINDOW_S = 300       # a heating confirmation is fresh for 5 minutes
HEAT_WAIT_TIMEOUT_S = 300    # give the hotend time to reach loosening temp
COOLDOWN_TIMEOUT_S = 900     # passive cooldown can take a while; never rushed
TORQUE_HINT = "1.5–2.5 Nm (use your hotend maker's spec)"

REMOVED_LABEL = "Old Nozzle Removed & New Nozzle Threaded"
TORQUED_LABEL = "Torqued hot — done"
COOLED_LABEL = "Cooled down — record the new nozzle"

# The step machine the plugin walks. ``heats`` marks the one step that may
# send a heater command — and only after its own explicit confirmation.
GUIDE_STEPS: tuple[dict[str, Any], ...] = (
    {"key": "select", "heats": False,
     "title": "Select the replacement nozzle diameter and material."},
    {"key": "confirm_heat", "heats": False,
     "title": "Operator confirms, in person at the printer, that the hotend "
              "may be heated for the change."},
    {"key": "heat_loosen", "heats": True,
     "title": f"Heat the hotend to {LOOSEN_TEMP_C} °C to melt residual plastic "
              "before loosening the old nozzle."},
    {"key": "removed_threaded", "heats": False,
     "title": f"Operator removes the old nozzle hot and threads the new one; "
              f"step confirmation: [{REMOVED_LABEL}]."},
    {"key": "hot_torque", "heats": False,
     "title": f"Hot-torque the new nozzle at temperature ({TORQUE_HINT}) "
              "while the heater stays at the loosening temperature."},
    {"key": "cooldown", "heats": False,
     "title": f"Heater off; wait for a live readback below {SAFE_TEMP_C} °C."},
    {"key": "record", "heats": False,
     "title": "Record the new nozzle in printer_hardware.json and invalidate "
              "the previous calibration."},
    {"key": "calibration", "heats": False,
     "title": "Offer the post-change calibrations: Z-offset (--sync-z), bed "
              "mesh leveling, pressure advance / flow check."},
)

_CONTROL_LOCK = threading.Lock()
_IDLE_STATES = {"standby", "complete", "cancelled", "error"}


def supports_live_heat(connection: str | None) -> bool:
    """Only the Moonraker/Klipper connection can be commanded to heat here."""
    return str(connection or "").casefold() == "moonraker"


def manual_heat_instructions(temp_c: int = LOOSEN_TEMP_C) -> str:
    """The graceful degradation for printers Print Handy cannot heat."""
    return (f"This printer is not on a Moonraker/Klipper connection, so I can't heat it from here. "
            f"On the printer's own screen, heat the hotend to {temp_c} °C, remove the old nozzle hot, "
            f"thread the new one, and torque it hot ({TORQUE_HINT}). Then turn the heater off and let "
            f"it cool below {SAFE_TEMP_C} °C before confirming here — the state record and calibration "
            "prompts still apply.")


def _state_view(reader: Callable[[], dict[str, Any]] | None,
                printer_id: str | None) -> dict[str, Any]:
    if reader is not None:
        return reader() or {}
    from . import print_control as pc
    data = pc._send("/printer/objects/query?print_stats&extruder&webhooks",
                    printer_id=printer_id)
    return ((data.get("result") or {}).get("status") or {})


def _send_gcode(script: str, printer_id: str | None,
                sender: Callable[[str], Any] | None) -> None:
    if sender is not None:
        sender(script)
        return
    from . import print_control as pc
    pc._send("/printer/gcode/script", method="POST", data={"script": script},
             timeout=30, printer_id=printer_id)


def _job_state(status: dict[str, Any]) -> str:
    return str((status.get("print_stats") or {}).get("state") or "unknown").casefold()


def _extruder(status: dict[str, Any]) -> dict[str, Any]:
    return status.get("extruder") or {}


def _fresh_confirmation(confirmed_at: float) -> bool:
    return not (time.time() - float(confirmed_at) > CONFIRM_WINDOW_S
                or float(confirmed_at) > time.time() + 2)


def heat_for_loosen(*, confirmed_at: float, temp_c: int = LOOSEN_TEMP_C,
                    gcode_sender: Callable[[str], Any] | None = None,
                    reader: Callable[[], dict[str, Any]] | None = None,
                    printer_id: str | None = None,
                    wait_timeout_s: float = HEAT_WAIT_TIMEOUT_S,
                    poll_s: float = 2.0) -> tuple[bool, str]:
    """Heat to the loosening temperature, once, after a fresh confirmation.

    Fail-closed like ``print_control.coldpull``: expired confirmation, a busy
    or non-idle printer, or a missing temperature readback all refuse with
    nothing (further) sent. On a failed heat-up the heater is turned off
    before returning, so a refused flow never leaves the hotend heating
    unattended.
    """
    if temp_c != LOOSEN_TEMP_C:
        return False, f"Refused: {temp_c} °C is not the guided loosening temperature. Nothing sent."
    if not _fresh_confirmation(confirmed_at):
        return False, "Refused: confirmation expired. Nothing sent."
    if not _CONTROL_LOCK.acquire(blocking=False):
        return False, "Refused: another nozzle-change action is in flight. Nothing sent."
    try:
        try:
            st = _state_view(reader, printer_id)
        except Exception as exc:
            return False, f"Refused: printer state could not be read ({type(exc).__name__}). Nothing sent."
        job_state = _job_state(st)
        if job_state in {"printing", "paused"}:
            return False, f"Refused: printer is {job_state}. Nothing sent."
        if job_state not in _IDLE_STATES:
            return False, f"Refused: printer state is {job_state}. Nothing sent."
        try:
            _send_gcode(f"M104 S{int(temp_c)}", printer_id, gcode_sender)
        except Exception as exc:
            return False, f"Heating command failed ({type(exc).__name__}). Check the printer screen; do not retry blindly."
        deadline = time.monotonic() + wait_timeout_s
        last = None
        while True:
            try:
                st = _state_view(reader, printer_id)
            except Exception:
                st = {}
            ext = _extruder(st)
            last = ext.get("temperature")
            if isinstance(last, (int, float)) and float(last) >= temp_c - 10:
                if float(ext.get("target") or 0) != float(temp_c):
                    return False, (f"Hotend reached {float(last):.0f} °C but its target readback is "
                                   f"{ext.get('target')!r}, not {temp_c}. Check the printer; do not proceed.")
                return True, (f"Hotend is at {float(last):.0f} °C (target {temp_c} °C). "
                              "Remove the old nozzle now, thread the new one, then confirm.")
            if time.monotonic() >= deadline:
                break
            time.sleep(poll_s)
        # Never leave a heater running unattended behind a failed step.
        try:
            _send_gcode("M104 S0", printer_id, gcode_sender)
        except Exception:
            pass
        return False, (f"Hotend did not reach {temp_c} °C within {wait_timeout_s:.0f}s "
                       f"(last readback {last!r}). Heater turned off. Check the printer screen.")
    finally:
        _CONTROL_LOCK.release()


def heater_off(*, gcode_sender: Callable[[str], Any] | None = None,
               printer_id: str | None = None) -> tuple[bool, str]:
    """Best-effort heater off for a cancelled flow. No waiting, no recording."""
    try:
        _send_gcode("M104 S0", printer_id, gcode_sender)
    except Exception as exc:
        return False, f"Heater-off command failed ({type(exc).__name__}). Turn the heater off on the printer screen NOW."
    return True, "Heater turned off. Nothing was recorded."


def cooldown(*, gcode_sender: Callable[[str], Any] | None = None,
             reader: Callable[[], dict[str, Any]] | None = None,
             printer_id: str | None = None,
             timeout_s: float = COOLDOWN_TIMEOUT_S,
             poll_s: float = 2.0) -> tuple[bool, str]:
    """Heater off, then wait for a live readback below SAFE_TEMP_C.

    A timeout is a failure ("still hot"), never a silent success: the state
    record is only written after this returns True.
    """
    if not _CONTROL_LOCK.acquire(blocking=False):
        return False, "Refused: another nozzle-change action is in flight. Nothing sent."
    try:
        try:
            _send_gcode("M104 S0", printer_id, gcode_sender)
        except Exception as exc:
            return False, f"Heater-off command failed ({type(exc).__name__}). Turn the heater off on the printer screen."
        deadline = time.monotonic() + timeout_s
        last = None
        while True:
            try:
                st = _state_view(reader, printer_id)
            except Exception:
                st = {}
            ext = _extruder(st)
            last = ext.get("temperature")
            if isinstance(last, (int, float)) and float(last) < SAFE_TEMP_C:
                if float(ext.get("target") or 0) != 0.0:
                    return False, (f"Hotend readback is {float(last):.0f} °C but the heater target is "
                                   f"{ext.get('target')!r}, not 0. Check the printer; not recording the change yet.")
                return True, f"Hotend is at {float(last):.0f} °C with the heater off. Safe to record the new nozzle."
            if time.monotonic() >= deadline:
                return False, (f"Hotend is still at {last!r} after {timeout_s:.0f}s (needs < {SAFE_TEMP_C} °C). "
                               "Nothing was recorded. Check the printer and re-run /nozzle change to finish.")
            time.sleep(poll_s)
    finally:
        _CONTROL_LOCK.release()


def record_nozzle_change(state: dict[str, Any], diameter_mm: float,
                         nozzle_type: str, *, today: str | None = None,
                         supported_sizes=None, supported_types=None) -> dict[str, Any]:
    """Record a completed change in a printer_hardware state dict (in place).

    Applies the same invalidation as ``printer_state set --nozzle``: the
    recorded nozzle is replaced, the user Z offset is cleared and marked
    unverified, the calibration authority records that the previous
    calibration is historical only, and a tuned pressure advance is marked
    stale. Adds the explicit ``calibration_pending`` list the post-change
    prompts work from, plus a ``nozzle_change`` audit record. Raises
    ``NozzleError`` for an unsupported diameter/type — nothing is mutated
    before validation passes.
    """
    from ..core.nozzle import validate_nozzle_setting

    dia, norm_type = validate_nozzle_setting(
        diameter_mm, nozzle_type,
        supported_sizes=supported_sizes, supported_types=supported_types)
    installed = today or datetime.date.today().isoformat()
    previous = dict(state.get("nozzle") or {})
    state["nozzle"] = {"diameter_mm": dia, "type": norm_type, "installed": installed}
    state["z_offset_verified"] = False
    state["z_offset_mm"] = None
    state["calibration_authority"] = {
        "mode": None, "operator_confirmed": False,
        "reason": "Nozzle changed; previous calibration is historical only"}
    state["z_offset_note"] = ("Nozzle changed; calibration needs a measured confirmation "
                              "for the active mode. --sync-z only records the probe trigger.")
    if state.get("pressure_advance"):
        state["pressure_advance"]["stale"] = True
    state["calibration_pending"] = ["z_offset", "bed_mesh", "pressure_advance_flow"]
    state["bed_mesh_stale"] = True
    state["nozzle_change"] = {
        "recorded": installed,
        "previous": {"diameter_mm": previous.get("diameter_mm"), "type": previous.get("type")},
        "new": {"diameter_mm": dia, "type": norm_type},
        "procedure": "guided /nozzle change (#513)",
    }
    return state


def calibration_prompts(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The post-change calibration offers for the recorded nozzle (#513 §3).

    Each offer names what it does and its command path; offers that would
    move or heat the printer (bed mesh) stay offers — running one goes
    through its own confirmation in :func:`run_bed_mesh`.
    """
    nozzle = state.get("nozzle") or {}
    dia = nozzle.get("diameter_mm", 0.4)
    prompts = [
        {"key": "z_offset", "label": "Z-offset calibration",
         "detail": "A nozzle change moves the tip, so the old offset is historical only. "
                   "Measure at the printer, then record the live probe store with "
                   "`printer_state set --sync-z` (that records the probe trigger only; "
                   "a measured user offset is recorded separately with `--z-offset N`).",
         "command": "--sync-z", "moves_printer": False},
        {"key": "bed_mesh", "label": "Run Bed Mesh Leveling",
         "detail": "The saved mesh predates this nozzle, so its stale-mesh warning stays "
                   "until a fresh mesh is probed. Running it homes and probes the bed.",
         "command": "BED_MESH_CALIBRATE", "moves_printer": True},
    ]
    pa_detail = ("Pressure advance and flow were tuned for the previous nozzle; retune both "
                 "before trusting extrusion.")
    if dia != 0.4:
        pa_detail = (f"A {dia:g} mm nozzle changes extrusion volume versus the 0.4 mm baseline: "
                     "pressure advance and flow calibration are strongly recommended, not optional.")
    prompts.append({"key": "pressure_advance_flow", "label": "Pressure Advance / Flow check",
                    "detail": pa_detail, "command": None, "moves_printer": False})
    return prompts


def calibration_text(state: dict[str, Any]) -> str:
    """The post-change prompt block shown when a change is recorded."""
    nozzle = state.get("nozzle") or {}
    lines = [f"Recorded: {nozzle.get('diameter_mm')} mm {nozzle.get('type')} nozzle. "
             "Previous calibration is historical only. Before the next print:"]
    for prompt in calibration_prompts(state):
        lines.append(f"- **{prompt['label']}** — {prompt['detail']}")
    lines.append("Bed mesh leveling is offered as the next prompt in this flow; the other "
                 "checks can be done later — prints keep warning until the mesh and offset "
                 "are refreshed.")
    return "\n".join(lines)


def run_bed_mesh(*, confirmed_at: float,
                 gcode_sender: Callable[[str], Any] | None = None,
                 reader: Callable[[], dict[str, Any]] | None = None,
                 printer_id: str | None = None) -> tuple[bool, str]:
    """Send BED_MESH_CALIBRATE once, after a fresh confirmation, while idle."""
    if not _fresh_confirmation(confirmed_at):
        return False, "Refused: confirmation expired. Nothing sent."
    if not _CONTROL_LOCK.acquire(blocking=False):
        return False, "Refused: another nozzle-change action is in flight. Nothing sent."
    try:
        try:
            st = _state_view(reader, printer_id)
        except Exception as exc:
            return False, f"Refused: printer state could not be read ({type(exc).__name__}). Nothing sent."
        job_state = _job_state(st)
        if job_state in {"printing", "paused"}:
            return False, f"Refused: printer is {job_state}. Nothing sent."
        if job_state not in _IDLE_STATES:
            return False, f"Refused: printer state is {job_state}. Nothing sent."
        try:
            _send_gcode("BED_MESH_CALIBRATE", printer_id, gcode_sender)
        except Exception as exc:
            return False, f"Bed mesh command failed ({type(exc).__name__}). Check the printer screen."
        return True, "Bed mesh leveling sent once. It homes and probes; wait for it to finish on the printer screen."
    finally:
        _CONTROL_LOCK.release()


def finish_change(state: dict[str, Any], diameter_mm: float, nozzle_type: str,
                  *, printer_id: str | None = None, **kwargs) -> str:
    """Record the change in printer_hardware.json and return the prompt text.

    Uses printer_state's own load/save so the per-printer file layout (#334)
    is honoured. ``state`` is accepted for callers/tests that already loaded
    it; when it is empty the record is loaded from disk instead.
    """
    from ..core import printer_state

    st = state if state else printer_state.load(printer_id)
    record_nozzle_change(st, diameter_mm, nozzle_type, **kwargs)
    printer_state.save(st, printer_id)
    return calibration_text(st)
