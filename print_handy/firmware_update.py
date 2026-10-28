"""Printer firmware update state, guarded component updates and manual
update guidance, through Moonraker's Update Manager (issue #561).

Print Handy talks to many printer families, but exactly one programmatic
firmware path is safe enough to drive: Moonraker's Update Manager on
printers whose firmware Print Handy may treat as upstream — ZMod
(``firmware_family = zmod``) and vanilla Klipper (``firmware_family =
klipper`` from a non-fork vendor). Everything else in this module is
read-only reporting or plain-language guidance:

- **Stage 1 (check/report)** reads ``GET /machine/update/status`` and
  reports each component's current and available version. A user-invoked
  check may first ``POST /machine/update/refresh``; the plain read never
  refreshes (upstream Moonraker guidance is to refresh only on request —
  Moonraker also refreshes periodically by itself).
- **Stage 2 (guarded apply)** posts exactly one
  ``POST /machine/update/upgrade`` for one component, only after the
  operator confirms the exact ``current -> available`` change, only while
  the printer is idle (checked at prepare time and again at send time),
  and the outcome is verified by re-reading the status — a successful
  POST alone never counts as success. Eligibility is a property of the
  printer profile (see :func:`apply_block_reason`): vendor Klipper forks
  (Elegoo, Creality, QIDI, Anycubic) are refused even though they speak
  Moonraker, because driving a fork's Update Manager at upstream remotes
  is the vendors' documented breakage path (Elegoo says so explicitly
  for the Neptune 4).
- **Stage 3 (guides)** covers the two AD5X layers with no safe API —
  the ZMod base (USB / ``ZFLASH``) and the stock firmware underneath it
  (touchscreen / USB) — as step-by-step operator instructions. The
  guides never claim Print Handy performed any of those steps.
- **Stage 4 (guidance)** gives every other registry family a short
  statement of what Print Handy can report, the manual update steps,
  and why apply is not offered.

The transport is the spool_sync.moonraker client shape: a callable
taking ``(method, path, body=None)`` and returning the parsed JSON body.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

UPDATE_STATUS_PATH = "/machine/update/status"
UPDATE_REFRESH_PATH = "/machine/update/refresh"
UPDATE_UPGRADE_PATH = "/machine/update/upgrade"
SYSTEM_INFO_PATH = "/machine/system_info"
PRINT_STATE_PATH = "/printer/objects/query?print_stats=state"
MCU_STATE_PATH = "/printer/objects/query?mcu"

COULD_NOT_READ_TEXT = ("Could not read the printer's firmware state from Moonraker. "
                       "Nothing was sent to the printer.")
UPDATE_COULD_NOT_READ_TEXT = ("Could not read the printer's firmware state from Moonraker, so "
                              "there is no live status to update from. Nothing was sent "
                              "to the printer.")
READ_ONLY_NOTE = ("Read-only: Print Handy sent nothing to the printer but read requests. "
                  "To apply one update on an eligible printer, use "
                  "`/print-firmware update <component>` — it asks first and refuses while "
                  "a print is running.")
UPDATE_LABEL = "Update now"
CANCEL_LABEL = "Cancel"

# Klipper print_stats states in which no job is on the printer — the same
# set the macro run guard uses. Anything else — printing, paused, or a
# state Print Handy does not recognise — refuses the update (fail closed).
IDLE_STATES = frozenset({"standby", "complete", "cancelled", "error"})
BUSY_STATES = frozenset({"printing", "paused"})

# Apply eligibility (stage 2): upstream-tracking firmware families only,
# and never a vendor fork. The fork list is vendors, not models: a future
# Elegoo/Creality/QIDI/Anycubic Moonraker model is refused by the same
# rule until per-vendor evidence clears that vendor.
ELIGIBLE_FAMILIES = frozenset({"zmod", "klipper"})
FORK_VENDORS = frozenset({"elegoo", "creality", "qidi", "anycubic"})


class FirmwareError(RuntimeError):
    """The printer's firmware state could not be read. Nothing was sent when this is raised."""


class FirmwareRefusal(RuntimeError):
    """An update was refused before anything was sent; the message is user-ready."""


# --------------------------------------------------------------------- profiles

def printer_entry(model_key, registry=None):
    """The printers/registry.toml entry for a model key, or None when unregistered."""
    if registry is None:
        from . import knowledge
        registry = knowledge.default_registry()
    for entry in registry.printers:
        if entry.key == model_key:
            return entry
    return None


def apply_block_reason(entry) -> str | None:
    """Why stage 2 apply is not offered for this registry entry, or None when it is.

    Eligibility is a property of the printer profile — firmware family,
    vendor and connection from printers/registry.toml — never of what the
    printer's Update Manager happens to offer.
    """
    if entry is None:
        return ("Print Handy does not have this printer's profile in its registry, so it "
                "cannot judge whether driving its firmware updates is safe.")
    if entry.connection != "moonraker":
        return (f"This printer does not connect over Moonraker (it uses the "
                f"{entry.connection} connection), and Print Handy has no programmatic "
                f"firmware update path for that connection.")
    if entry.vendor in FORK_VENDORS:
        return (f"This printer runs {entry.vendor}'s own Klipper-based firmware — a vendor "
                f"fork, not upstream Klipper. Driving a vendor fork's Update Manager at "
                f"upstream releases is the vendors' documented breakage path (Elegoo "
                f"warns that updating a Neptune 4 to official Klipper/Moonraker makes the "
                f"machine not work properly), so Print Handy never applies firmware "
                f"updates on it.")
    if entry.firmware_family not in ELIGIBLE_FAMILIES:
        return (f"This printer's firmware family ({entry.firmware_family or 'none'}) is not "
                f"one Print Handy can update: only ZMod and vanilla Klipper printers are "
                f"eligible.")
    return None


def is_apply_eligible(entry) -> bool:
    return apply_block_reason(entry) is None


# --------------------------------------------------------------------- status

@dataclass(frozen=True)
class Component:
    """One Update Manager component: current vs available version."""

    name: str
    current: str | None = None
    remote: str | None = None
    package_count: int = 0

    @property
    def update_available(self) -> bool:
        if self.package_count:
            return True
        return bool(self.remote) and self.remote != (self.current or "")


@dataclass(frozen=True)
class UpdateStatus:
    components: tuple = ()          # tuple[Component, ...]

    def component(self, name):
        wanted = str(name or "").casefold()
        for component in self.components:
            if component.name.casefold() == wanted:
                return component
        return None

    @property
    def updates_available(self):
        return tuple(c for c in self.components if c.update_available)


def _version_str(value):
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def parse_update_status(payload) -> UpdateStatus:
    """Per-component versions from a Moonraker update-status response.

    Accepts the documented shape (``{"result": {"version_info": {name:
    {...}}}}``); the current version is read from ``version`` (or
    ``current_version``) and the available one from ``remote_version``
    (or ``available_version`` / ``latest_version``), so recorded variants
    replay unchanged. The ``system`` component reports a package count
    instead of versions. Anything structurally off raises FirmwareError
    rather than guessing at versions.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise FirmwareError("Moonraker's update-status response had no result")
    info = payload["result"].get("version_info")
    if not isinstance(info, dict) or not info:
        raise FirmwareError("Moonraker's update-status response had no version_info")
    components = []
    for name, raw in info.items():
        if not isinstance(raw, dict):
            raise FirmwareError(f"Moonraker's update-status entry for {name!r} was not an object")
        current = _version_str(raw.get("version")) or _version_str(raw.get("current_version"))
        remote = (_version_str(raw.get("remote_version"))
                  or _version_str(raw.get("available_version"))
                  or _version_str(raw.get("latest_version")))
        count = raw.get("package_count")
        components.append(Component(name=str(name), current=current, remote=remote,
                                    package_count=count if isinstance(count, int)
                                    and not isinstance(count, bool) else 0))
    return UpdateStatus(tuple(components))


def fetch_status(transport, *, refresh=False) -> UpdateStatus:
    """Read the update status through `transport`.

    With ``refresh=True`` (a user-invoked check) a refresh is requested
    first — the refresh response has the status shape, so it is parsed
    directly — and a failed refresh falls back to the plain status read
    rather than failing the report. The plain path makes exactly one
    GET. Any transport failure or malformed response raises
    FirmwareError; nothing is ever sent on this path beyond the refresh
    request itself.
    """
    if refresh:
        try:
            return parse_update_status(transport("POST", UPDATE_REFRESH_PATH))
        except Exception:
            pass  # fall through to the plain read below
    try:
        payload = transport("GET", UPDATE_STATUS_PATH)
    except FirmwareError:
        raise
    except Exception as exc:
        raise FirmwareError(f"the update-status request failed: {exc}") from exc
    return parse_update_status(payload)


# ------------------------------------------------------- ZMod pairing and MCU

_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)")


def version_parts(version):
    """The leading dotted-numeric parts of a version string, as ints, or ()."""
    match = _VERSION_RE.match(str(version or "").strip())
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def pairing_state(os_version, zmod_version) -> str:
    """"match", "mismatch" or "unknown" for the ZMod OS <-> zmod pairing rule.

    ZMod pairs its OS distribution and its ``zmod`` component in the
    first two version components (OS 1.9.4 needs ZMod 1.9.x). A mismatch
    is only claimed when both versions parse to at least two components
    and those differ; anything unreadable is "unknown", never a mismatch.
    """
    os_parts, zmod_parts = version_parts(os_version), version_parts(zmod_version)
    if len(os_parts) < 2 or len(zmod_parts) < 2:
        return "unknown"
    return "match" if os_parts[:2] == zmod_parts[:2] else "mismatch"


def os_version_from_system_info(payload):
    """The OS distribution version from a /machine/system_info response, or None."""
    try:
        distribution = payload["result"]["system_info"]["distribution"]
    except (TypeError, KeyError):
        return None
    if not isinstance(distribution, dict):
        return None
    return _version_str(distribution.get("version")) or _version_str(distribution.get("version_id"))


def fetch_os_version(transport):
    """Best-effort OS distribution version; None when unreadable (never raises)."""
    try:
        return os_version_from_system_info(transport("GET", SYSTEM_INFO_PATH))
    except Exception:
        return None


def mcu_version_from_objects(payload):
    """The MCU firmware version from a Klipper objects query, or None.

    Klipper's ``mcu`` object reports ``mcu_version`` in its status (the
    version of the firmware build running on the MCU, from the same
    Klipper checkout the host was built from). Any other shape is
    unknown, not an error.
    """
    try:
        mcu = payload["result"]["status"]["mcu"]
    except (TypeError, KeyError):
        return None
    if not isinstance(mcu, dict):
        return None
    return _version_str(mcu.get("mcu_version"))


def fetch_mcu_version(transport):
    """Best-effort MCU firmware version; None when unreadable (never raises)."""
    try:
        return mcu_version_from_objects(transport("GET", MCU_STATE_PATH))
    except Exception:
        return None


def mcu_currency(host_version, mcu_version) -> str:
    """"match", "mismatch" or "unknown" for Klipper 13 host <-> MCU currency.

    ZMod's Klipper 13 installs need ``UPDATE_MCU`` to keep the MCU in
    step with the host. Currency is only judged for a Klipper 13 host
    (0.13.x) and only when both versions parse to a release triple:
    differing triples are a mismatch, anything else unreadable is
    "unknown". Other host versions are not judged here.
    """
    host, mcu = version_parts(host_version), version_parts(mcu_version)
    if len(host) < 3 or host[:2] != (0, 13) or len(mcu) < 3:
        return "unknown"
    return "match" if host[:3] == mcu[:3] else "mismatch"


# --------------------------------------------------------------------- report

def _component_line(component, *, eligible):
    if component.name == "system" and not component.current and not component.remote:
        if component.update_available:
            return f"- **system**: {component.package_count} system packages available"
        return "- system: system packages up to date"
    current = component.current or "version not reported"
    if component.update_available:
        line = f"- **{component.name}**: {current} -> {component.remote} available"
        if eligible:
            line += f" — update with `/print-firmware update {component.name}`"
        return line
    return f"- {component.name}: {current} (up to date)"


def report_text(status, entry, *, pairing="unknown", os_version=None,
                mcu_state="unknown", mcu_versions=None) -> str:
    """The chat-ready stage 1 report for one parsed update status."""
    eligible = is_apply_eligible(entry)
    label = entry.label if entry is not None else "your printer"
    lines = [f"**Firmware on {label}** (read live from Moonraker's Update Manager):"]
    lines += [_component_line(c, eligible=eligible) for c in status.components]
    if not status.updates_available:
        lines.append("\nEverything Print Handy can check here is up to date.")
    if entry is not None and entry.vendor in FORK_VENDORS:
        lines.append("\nThis printer runs its vendor's own Klipper-based firmware. These "
                     "versions are the vendor fork's, reported for information only — "
                     "Print Handy does not apply updates on vendor forks (see "
                     "`/print-firmware` guidance in docs/FIRMWARE-UPDATE.md).")
    if pairing == "mismatch":
        zmod = status.component("zmod")
        lines.append(f"\n**ZMod version mismatch:** the printer's OS reports "
                     f"{os_version or 'an unreadable version'} but the `zmod` component "
                     f"is {zmod.current if zmod else 'unreadable'}. ZMod pairs the OS and "
                     "the `zmod` component in their first two version numbers, and "
                     "component updates fail while they disagree. Update the ZMod base "
                     "from USB instead — `/print-firmware guide zmod` walks through it.")
    elif pairing == "match":
        lines.append("\nZMod base and component versions pair correctly "
                     f"({'.'.join(str(p) for p in version_parts(os_version)[:2])}.x).")
    if mcu_state == "mismatch" and mcu_versions is not None:
        host, mcu = mcu_versions
        lines.append(f"\n**MCU out of step:** Klipper on the host is {host} but the MCU "
                     f"firmware is {mcu}. On Klipper 13, run ZMod's `UPDATE_MCU` macro "
                     "(or your install's MCU update step) to bring the MCU in step "
                     "before printing.")
    if entry is not None and entry.firmware_family == "zmod":
        lines.append("\nNot covered by this check: the ZMod base itself and the stock "
                     "Flashforge firmware underneath it update by hand — "
                     "`/print-firmware guide zmod` and `/print-firmware guide stock` "
                     "walk through both.")
    if eligible:
        lines.append("\n" + READ_ONLY_NOTE)
    else:
        lines.append("\nRead-only: this report sent nothing to the printer but read "
                     "requests, and Print Handy does not apply firmware updates on "
                     "this printer.")
    return "\n".join(lines)


def firmware_report(transport, entry, *, refresh=False) -> str:
    """Read the status (and, for ZMod, the pairing/MCU extras) and build the report.

    The status read is the only required one: its failure raises
    FirmwareError. The pairing and MCU reads are best-effort and
    unknown-tolerant — absent data is simply not reported.
    """
    status = fetch_status(transport, refresh=refresh)
    pairing, os_version = "unknown", None
    mcu_state, mcu_versions = "unknown", None
    if entry is not None and entry.firmware_family == "zmod":
        os_version = fetch_os_version(transport)
        zmod = status.component("zmod")
        pairing = pairing_state(os_version, zmod.current if zmod else None)
    klipper = status.component("klipper")
    if klipper is not None and klipper.current:
        mcu_version = fetch_mcu_version(transport)
        mcu_state = mcu_currency(klipper.current, mcu_version)
        if mcu_state == "mismatch":
            mcu_versions = (klipper.current, mcu_version)
    return report_text(status, entry, pairing=pairing, os_version=os_version,
                       mcu_state=mcu_state, mcu_versions=mcu_versions)


def not_moonraker_text(connection) -> str:
    """The plain fallback when a printer's family has no Moonraker endpoint and
    no registry entry to build guidance from."""
    where = f" (it uses the {connection} connection)" if connection else ""
    return (f"This printer has no Moonraker Update Manager{where}, so Print Handy cannot "
            "read its firmware update state. Its firmware updates run at the printer "
            "itself — see docs/FIRMWARE-UPDATE.md for the per-family guide. "
            "Nothing was sent to the printer.")
