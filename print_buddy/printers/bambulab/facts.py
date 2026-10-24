"""Sourced hardware facts and template provenance for Bambu Lab printers. Supplemental metadata only.

Connection, start code, slicers, delivery, defaults and registration are decided by VENDOR (bambulab/__init__.py)
and each MODEL; nothing here overrides them. These are the values the A1 guard enforces, each with its source:

  ORCA     OrcaSlicer's own Bambu Lab (BBL) vendor profiles at ORCA_RELEASE, read directly from that commit,
           or OrcaSlicer's output with those profiles.
  BAMBU    Bambu Lab product and tech-spec pages. Not reachable from the sandbox that wrote these files; read
           from search-result extracts. Re-check against bambulab.com before relying on them.
  DERIVED  Computed from the ORCA G-code templates, not published by Bambu. Not a hardware certification.
verified=True means the value was read from its source directly; False means it must be re-checked.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fact:
    value: object
    source: str
    verified: bool


# OrcaSlicer release whose BBL vendor profiles the templates are flattened from: (tag, commit). Copied third-party
# material under AGPL-3.0; see docs/BAMBU-LAB.md "Provenance and licence" (an open maintainer decision).
ORCA_RELEASE = ("v2.4.2", "8500fcdccaa10b5099ac20d252af3a7c560046f1")
ORCA_PROFILE_ROOT = "resources/profiles/BBL"
# Print Buddy's only changes to the flattened vendor profiles, by kind. The shared post-slice guard allows only
# Normal Lift and no arc fitting; settings IDs let it match the effective settings Orca writes back.
ORCA_OVERRIDES = {
    "machine": {"z_hop_types": ["Normal Lift"]},
    # The plate is chosen explicitly: Orca's CLI otherwise resolves "Cool Plate", and the vendor start G-code's
    # Textured PEI nozzle offset (G29.1 Z-0.02) depends on it. The guard refuses any other plate.
    "process": {"enable_arc_fitting": "0", "enable_prime_tower": "0", "brim_type": "outer_only",
                "curr_bed_type": "Textured PEI Plate"},
    "filament": {"filament_colour": ["#FFFFFF"], "filament_z_hop_types": ["Normal Lift"]},
}
SETTINGS_IDS = {"machine": "printer_settings_id", "process": "print_settings_id", "filament": "filament_settings_id"}

# Vendor-wide claims, documented here only; VENDOR holds the behaviour.
VENDOR_FACTS = {
    # Orca writes Bambu-dialect G-code for BBL profiles: "; FEATURE:" role tags and "; CHANGE_LAYER" layers.
    "gcode_dialect": Fact("bambu", "ORCA", True),
    # Bambu Studio, LAN and cloud jobs are .gcode.3mf. Whether an A1 runs Print Buddy's package, or a plain .gcode
    # from microSD, has not been tested.
    "native_job_format": Fact(".gcode.3mf", "BAMBU", False),
    "connection_types": Fact(("LAN (MQTT status, FTPS upload, access code)", "Bambu cloud"), "BAMBU", False),
}

A1 = {
    # printer_model as Orca writes it into G-code, and the first line of the vendor machine start G-code.
    "printer_model": Fact("Bambu Lab A1", "ORCA", True),
    "vendor_start": Fact(";===== machine: A1 ", "ORCA", True),
    "orca_profiles": Fact({"machine": "Bambu Lab A1 0.4 nozzle", "process": "0.20mm Standard @BBL A1",
                           "filament": "Generic PLA @BBL A1"}, "ORCA", True),
    # printable_area 0x0..256x256 and printable_height 256; Bambu also publishes 256 x 256 x 256 mm.
    "bed_mm": Fact((256.0, 256.0), "ORCA", True),
    "max_print_height_mm": Fact(256.0, "ORCA", True),
    # The A1 profile empties the X1 family's corner exclusion: no printable-area exclusion.
    "bed_exclude_area": Fact((), "ORCA", True),
    # Where the firmware's head-wrap (nozzle clump) check runs. Orca only marks it; not an exclusion.
    "head_wrap_detect_zone_mm": Fact(((226, 224), (256, 224), (256, 256), (226, 256)), "ORCA", True),
    # Extremes of the absolute XY moves in the vendor G-code (wiper X-48.2, cutter X267, purge lane Y-0.5/262.5),
    # plus the highest travel Z allowed above the print (z-hop and timelapse lift). Not hardware certification.
    "motion_envelope_mm": Fact((-48.2, -0.5, 267.0, 262.5), "DERIVED", False),
    "travel_z_headroom_mm": Fact(1.0, "DERIVED", False),
    "gcode_flavor": Fact("marlin", "ORCA", True),
    # The vendor profile's default plate; the start G-code lowers the nozzle 0.02 mm only for this plate type.
    "default_plate": Fact("Textured PEI Plate", "ORCA", True),
    # Stock 0.4 mm stainless steel; 0.2, 0.6 and 0.8 mm hotends exist. Only 0.4 has a template here.
    "stock_nozzle": Fact((0.4, "stainless_steel"), "ORCA", True),
    "nozzle_sizes_mm": Fact((0.2, 0.4, 0.6, 0.8), "BAMBU", False),
    "max_hotend_c": Fact(300, "BAMBU", False),
    "max_bed_c": Fact(100, "BAMBU", False),
    # Bambu lists PLA, PETG, TPU and PVA as ideal; ABS, ASA, PC, PA, PET and CF/GF fills as not recommended
    # (open frame). CF/GF and glow fills need a hardened steel nozzle.
    "ideal_materials": Fact(("PLA", "PETG", "TPU", "PVA"), "BAMBU", False),
    "not_recommended_materials": Fact(("ABS", "ASA", "PC", "PA", "PET"), "BAMBU", False),
    # AMS Lite: four spool holders feeding one hotend (A1 Combo). Not driven by Print Buddy.
    "ams": Fact(("AMS Lite", 4), "BAMBU", False),
}
