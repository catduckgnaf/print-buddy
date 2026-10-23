"""Bambu Lab vendor profile, and the printer profile shape that inherits from it.

Layout, vendor first, then printer:

    vendor.py   BAMBU_LAB: what every Bambu Lab printer shares here (slicer and profile release, G-code dialect,
                job formats, start-code family, connection types, handoff methods, the support matrix and the
                Print Buddy changes applied to every vendor Orca profile).
    a1.py       the A1 printer profile (dimensions, exclusions, nozzles, materials, AMS Lite) plus its MODEL.
    p1s.py      not written yet; a P1S printer profile and MODEL go here, inheriting BAMBU_LAB the same way.

A printer profile looks a fact up in its own facts first, then the vendor's, and its support matrix is the
vendor's with the printer's overrides on top. Templates stay in templates/orca/bambulab_<printer>.

Sources for every Fact:
  ORCA     OrcaSlicer's own Bambu Lab (BBL) vendor profiles at the release pinned below, read directly from
           that commit, or OrcaSlicer's output with those profiles.
  BAMBU    Bambu Lab product and tech-spec pages. Not reachable from the sandbox that wrote these files; read
           from search-result extracts. Re-check against bambulab.com before relying on them.
  DERIVED  Computed from the ORCA G-code templates, not published by Bambu. Unverified on hardware.
verified=True means the value was read from its source directly; False means it must be re-checked.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Fact:
    value: object
    source: str
    verified: bool


@dataclass(frozen=True)
class VendorProfile:
    key: str
    name: str
    # OrcaSlicer release whose vendor profiles the templates are flattened from: (tag, commit).
    orca_release: tuple[str, str]
    # Print Buddy's only changes to the vendor's Orca profiles, by profile kind (machine, process, filament).
    orca_overrides: dict
    facts: dict
    support: dict
    # Firmware and authentication modes validated for live use.
    live_modes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PrinterProfile:
    key: str
    vendor: VendorProfile
    # printer_model as OrcaSlicer writes it into G-code, e.g. "Bambu Lab A1".
    printer_model: str
    # First line of the vendor machine start G-code; identifies the printer's own start sequence.
    vendor_start: str
    # Orca vendor profile names flattened into templates/orca/<templates>, by kind.
    orca_profiles: dict
    templates: str
    facts: dict
    support: dict = field(default_factory=dict)

    def fact(self, name) -> Fact:
        """This printer's fact, else the vendor's. KeyError when neither has it."""
        return self.facts[name] if name in self.facts else self.vendor.facts[name]

    def value(self, name):
        return self.fact(name).value

    @property
    def all_facts(self) -> dict:
        return {**self.vendor.facts, **self.facts}

    @property
    def capabilities(self) -> dict:
        return {**self.vendor.support, **self.support}

    @property
    def live_modes(self) -> tuple[str, ...]:
        return self.vendor.live_modes


BAMBU_LAB = VendorProfile(
    key="bambulab",
    name="Bambu Lab",
    orca_release=("v2.4.2", "8500fcdccaa10b5099ac20d252af3a7c560046f1"),
    orca_overrides={
        # The shared post-slice guard allows only Normal Lift and no arc fitting on every printer.
        "machine": {"z_hop_types": ["Normal Lift"]},
        "process": {"enable_arc_fitting": "0", "enable_prime_tower": "0", "brim_type": "outer_only"},
        "filament": {"filament_colour": ["#FFFFFF"], "filament_z_hop_types": ["Normal Lift"]},
        # Plus printer_settings_id / print_settings_id / filament_settings_id set to the profile names.
    },
    facts={
        "slicer": Fact("OrcaSlicer with the BBL vendor profiles, flattened into Print Buddy templates", "ORCA", True),
        # Orca writes Bambu-dialect G-code for BBL profiles: "; FEATURE:" role tags, "; CHANGE_LAYER" layers.
        "gcode_dialect": Fact("bambu", "ORCA", True),
        "print_buddy_output": Fact(".gcode", "ORCA", True),
        # Bambu printers take .gcode.3mf jobs from Bambu Studio, LAN and cloud. Plain .gcode from microSD is unverified.
        "native_job_format": Fact(".gcode.3mf", "BAMBU", False),
        # The printer's own Orca profile start/end G-code, used verbatim. Never Klipper or ZMod macros.
        "start_code_family": Fact("vendor start/end G-code from the Orca BBL profile", "ORCA", True),
        "connection_types": Fact(("LAN (MQTT status, FTPS upload, access code)", "Bambu cloud"), "BAMBU", False),
        "handoff_methods": Fact(("manual file copy", "Bambu Studio", "LAN upload", "cloud"), "BAMBU", False),
    },
    # What Print Buddy does for Bambu Lab printers today. Everything not True is refused, never approximated.
    support={
        "offline_slicing": True,
        "fit_checks": True,
        "gcode_validation": True,
        "file_handoff": "manual",         # the operator copies the verified G-code; nothing is sent
        "live_telemetry": False,          # no MQTT, LAN or cloud status
        "file_upload": False,             # no FTPS, LAN or cloud upload
        "print_control": False,           # no start, pause, resume, stop
        "ams_multicolor": False,          # single filament only; multi-color sources are refused
        "bambu_studio_handoff": False,    # upstream issue #123, out of scope here
    },
)
