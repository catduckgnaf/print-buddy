"""Bambu Lab A1 facts and what Print Buddy does with them, each value with its source.

Sources:
  ORCA     OrcaSlicer v2.4.2 (tag commit 8500fcdccaa10b5099ac20d252af3a7c560046f1), resources/profiles/BBL:
           machine/"Bambu Lab A1 0.4 nozzle.json" -> fdm_bbl_3dp_001_common -> fdm_machine_common, plus the five
           "Bambu Lab A1 0.4 nozzle template *_gcode.json" includes. Read directly from that commit.
  BAMBU    Bambu Lab A1 store/tech-spec pages (bambulab.com, store.bambulab.com product A1). Not reachable from the
           sandbox that wrote this file; values were read from search-result extracts of those pages. Re-check
           against https://bambulab.com/en/a1/tech-specs before relying on them.
  DERIVED  Computed from the ORCA G-code templates, not published by Bambu. Unverified on hardware.

verified=True means the value was read from its source directly; False means it must be re-checked.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fact:
    value: object
    source: str
    verified: bool


A1 = {
    # Geometry: printable_area 0x0..256x256 and printable_height 256 (ORCA); Bambu also publishes 256 x 256 x 256 mm.
    "bed_mm": Fact((256.0, 256.0), "ORCA", True),
    "max_print_height_mm": Fact(256.0, "ORCA", True),
    # The A1 profile overrides the X1 family's corner exclusion with an empty list: no printable-area exclusion.
    "bed_exclude_area": Fact((), "ORCA", True),
    # Where the firmware's head-wrap (nozzle clump) check runs. Orca only marks it; it is not an exclusion.
    "head_wrap_detect_zone_mm": Fact(((226, 224), (256, 224), (256, 256), (226, 256)), "ORCA", True),
    # Extremes of the absolute XY moves in the vendor start/end/change/timelapse G-code (wiper at X-48.2,
    # cutter at X267, purge lane at Y-0.5 and Y262.5). Toolpath extrusion must still stay on the 256 mm bed.
    "motion_envelope_mm": Fact((-48.2, -0.5, 267.0, 262.5), "DERIVED", False),
    "gcode_flavor": Fact("marlin", "ORCA", True),
    # Stock 0.4 mm stainless steel; 0.2, 0.6 and 0.8 mm hotends exist. Only 0.4 has a template here.
    "stock_nozzle": Fact((0.4, "stainless_steel"), "ORCA", True),
    "nozzle_sizes_mm": Fact((0.2, 0.4, 0.6, 0.8), "BAMBU", False),
    "max_hotend_c": Fact(300, "BAMBU", False),
    "max_bed_c": Fact(100, "BAMBU", False),
    # Bambu lists PLA, PETG, TPU and PVA as ideal; ABS, ASA, PC, PA, PET and CF/GF fills as not recommended
    # (open frame). CF/GF and glow fills need a hardened steel nozzle.
    "ideal_materials": Fact(("PLA", "PETG", "TPU", "PVA"), "BAMBU", False),
    "not_recommended_materials": Fact(("ABS", "ASA", "PC", "PA", "PET"), "BAMBU", False),
    # AMS Lite: four spool holders feeding one hotend (A1 Combo). Not driven by Print Buddy in phase 1.
    "ams_lite_slots": Fact(4, "BAMBU", False),
}

# What Print Buddy does for the A1 today. Everything not True is refused, never approximated.
SUPPORT = {
    "offline_slicing": True,          # OrcaSlicer with templates/orca/bambulab_a1
    "fit_checks": True,               # 256 x 256 x 256 mm, no exclusion area, same deterministic checks as other models
    "gcode_validation": True,         # printers.bambulab.guard, after slicing and again before handoff
    "file_handoff": "manual",         # the operator copies the verified G-code to the printer; nothing is sent
    "live_telemetry": False,          # no MQTT, LAN or cloud status
    "file_upload": False,             # no FTPS, LAN or cloud upload
    "print_control": False,           # no start, pause, resume, stop
    "ams_lite_multicolor": False,     # single filament only; multi-color sources are refused
    "bambu_studio_handoff": False,    # upstream issue #123, out of scope
}

# Firmware and authentication modes Print Buddy has validated for live use. None yet.
LIVE_MODES: tuple[str, ...] = ()
