"""Listener domains: the registry behind the supervisor and healthcheck (#299).

Print Buddy's listeners are split by *domain* — the configured printer's
connection / firmware type (`print_buddy.printers.base.CONNECTIONS`). The
domain selects the listener *type*; a listener *instance* serves one
configured printer. Today exactly one instance exists per installation (one
printer per instance, #257), but nothing here is a global singleton: the
registry answers "which listener, if any, serves this connection", so a
future multi-printer supervisor asks once per printer instance and
supervises and healthchecks each instance independently — one instance
failing must never take down the bot, Spoolman, or another instance (#256).

Availability is three-valued, and the distinction matters to the supervisor:

- ``implemented`` — a listener module exists and is started.
- ``planned``     — the domain is known but has no listener yet. This is a
  normal state, not an error: the supervisor starts nothing for the domain
  and the container idles exactly as it did before the registry existed.
- ``none``        — the connection has no listener by definition (offline:
  Print Buddy never contacts the printer).

An *unresolvable configuration* is none of these; callers keep the #256
handling for it (the gate exits 2 and the supervisor stops with the settings
error rather than guessing).

Normalised contract
-------------------
Every domain listener observes its printer and reports through one shared
shape, the shape the printer adapters' ``normalize_status`` already returns
and the Moonraker listener already works with internally:

- Status fields (``STATUS_FIELDS``): ``state``, ``filename``, ``progress``
  (0..1 or None), ``hotend_c`` / ``bed_c`` and their ``*_target_c``
  companions, plus optional ``remaining_min``, ``layer`` and ``total_layer``.
  ``validate_status`` pins the core of that shape.
- Event kinds (``EVENT_KINDS``): ``status`` (a fresh status snapshot),
  ``completion`` (a print finished), ``error`` (the printer reports an
  error; the payload keeps the domain's raw representation — for Bambu
  that includes its HMS entries), and ``snapshot_available`` (a camera
  snapshot can be fetched for this printer now). Consumers (Discord posts,
  the camera watchdog, timelapse) subscribe by kind and never need to know
  which domain produced the event.

Liveness is the existing heartbeat (print_buddy.healthcheck): a running
listener beats with its domain's ``runtime`` identity, and the container
healthcheck requires that heartbeat exactly when the registry says a
listener is implemented for the configured connection.
"""
from __future__ import annotations

import runpy
import sys
from dataclasses import dataclass

from .printers import base as _printer_base

IMPLEMENTED = "implemented"
PLANNED = "planned"
NONE = "none"

# Core status fields every domain reports (adapters' normalize_status).
STATUS_FIELDS = ("state", "filename", "progress", "hotend_c", "bed_c")
# Optional status fields a domain reports when its protocol carries them.
STATUS_OPTIONAL_FIELDS = ("hotend_target_c", "bed_target_c", "remaining_min",
                          "layer", "total_layer")
# Event kinds a listener may emit into the bot core.
EVENT_KINDS = ("status", "completion", "error", "snapshot_available")


@dataclass(frozen=True)
class ListenerDomain:
    """One listener domain: a connection type and the listener serving it."""

    name: str  # the domain name; today identical to the connection it serves
    connection: str  # one of printers.base.CONNECTIONS
    availability: str  # IMPLEMENTED, PLANNED or NONE
    module: str | None = None  # `python3 -m` target when implemented
    runtime: str | None = None  # heartbeat identity when implemented
    transport: str = ""  # how the listener talks to the printer, for docs

    @property
    def implemented(self) -> bool:
        return self.availability == IMPLEMENTED


DOMAINS = {
    "moonraker": ListenerDomain(
        name="moonraker", connection="moonraker", availability=IMPLEMENTED,
        module="print_buddy.hermes.moonraker_event_listener",
        runtime="moonraker_event_listener", transport="Moonraker websocket"),
    "bambulab_lan": ListenerDomain(
        name="bambulab_lan", connection="bambulab_lan", availability=PLANNED,
        transport="Bambu LAN MQTT (long-lived; #299 Stage B)"),
    "prusalink": ListenerDomain(
        name="prusalink", connection="prusalink", availability=PLANNED,
        transport="PrusaLink HTTP polling (#299 Stage C)"),
    "elegoo_sdcp": ListenerDomain(
        name="elegoo_sdcp", connection="elegoo_sdcp", availability=PLANNED,
        transport="Elegoo SDCP websocket (#299 Stage C)"),
    "octoprint": ListenerDomain(
        name="octoprint", connection="octoprint", availability=PLANNED,
        transport="OctoPrint HTTP (evaluated in #299 Stage C)"),
    "flashforge_stock": ListenerDomain(
        name="flashforge_stock", connection="flashforge_stock", availability=PLANNED,
        transport="Stock Flashforge LAN (evaluated in #299 Stage C)"),
    "offline": ListenerDomain(
        name="offline", connection="offline", availability=NONE,
        transport="none: Print Buddy never contacts the printer"),
}

# The registry covers every connection a vendor may declare; a connection
# added to CONNECTIONS without a domain is a programming error, not a new
# supervisor state.
_missing = [c for c in _printer_base.CONNECTIONS if c not in DOMAINS]
if _missing:
    raise RuntimeError(f"listener registry has no domain for connections {_missing}")


def domain_for_connection(connection):
    """The listener domain serving `connection`, or None when unknown."""
    return DOMAINS.get(connection)


def implemented_connections():
    """Connections whose domain has a listener implementation today."""
    return tuple(c for c, domain in DOMAINS.items() if domain.implemented)


def validate_status(status):
    """Problems with a normalised status dict; empty when it fits the contract."""
    if not isinstance(status, dict):
        return ["status is not a dict"]
    problems = [f"missing status field {field!r}" for field in STATUS_FIELDS
                if field not in status]
    if "state" in status and not isinstance(status["state"], str):
        problems.append("status 'state' must be a string")
    if "filename" in status and not isinstance(status["filename"], str):
        problems.append("status 'filename' must be a string")
    for field in ("progress", "hotend_c", "bed_c"):
        value = status.get(field)
        if value is not None and (isinstance(value, bool)
                                  or not isinstance(value, (int, float))):
            problems.append(f"status {field!r} must be a number or None")
    progress = status.get("progress")
    if isinstance(progress, (int, float)) and not isinstance(progress, bool) \
            and not 0 <= progress <= 1:
        problems.append("status 'progress' must be within 0..1")
    return problems


def launch(data=None):
    """Run the configured printer instance's listener in this process.

    Returns the supervisor-facing exit code when there is nothing to run
    (3 = the instance's domain has no listener yet or by definition); an
    implemented listener runs until it exits or raises, exactly as if its
    module had been started directly. Configuration problems propagate as
    settings.SettingsError, like the gate's unresolved case.
    """
    from . import healthcheck

    domain = healthcheck.listener_domain(data)
    if domain is None:
        print(f"listener: connection {healthcheck.listener_connection(data)!r} "
              "has no registered listener domain; not starting one")
        return 3
    if not domain.implemented:
        print(f"listener: domain {domain.name!r} has no listener yet; not starting one")
        return 3
    runpy.run_module(domain.module, run_name="__main__")
    return 0


def main():
    try:
        return launch()
    except Exception as exc:  # settings errors name themselves; keep the code 2 contract
        from . import settings

        if isinstance(exc, settings.SettingsError):
            print(f"listener: configuration unresolved: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
