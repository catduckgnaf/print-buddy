"""Sourced hardware facts and template provenance for Prusa printers. Supplemental metadata only.

Connection, start code, slicers, delivery, defaults and registration are decided by VENDOR
(prusa/__init__.py) and each MODEL; nothing here overrides them. Values follow the bambulab/facts.py
conventions: ORCA values were read directly from OrcaSlicer v2.4.2's Prusa vendor profiles at
ORCA_RELEASE (flattened with the shared profile pipeline; identities reproduce the same way the
Bambu ones do), PRUSA values come from Prusa's published product specifications and were not
reached from the sandbox that wrote these files, DERIVED values are computed from the ORCA
templates. verified=True means the value was read from its source directly.

The Prusa vendor profiles in OrcaSlicer v2.4.2 are version 02.04.00.03 (newer than the BBL
tree's 02.01.00.19). Their machine profiles store start/end G-code as a list of lines; profiles.py
joins them into the string form every other vendor's templates use when it writes templates.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fact:
    value: object
    source: str
    verified: bool


ORCA_RELEASE = ("v2.4.2", "8500fcdccaa10b5099ac20d252af3a7c560046f1")
ORCA_PROFILE_ROOT = "resources/profiles/Prusa"
_IDENTITY_LABEL = "OrcaSlicer 2.4.2 (Prusa vendor profiles 02.04.00.03)"


def _identity(machine, process, filament):
    return Fact(({"label": _IDENTITY_LABEL, "vendor_version": "02.04.00.03",
                  "sha256": {"machine": machine, "process": process, "filament": filament}},), "ORCA", True)


MK4S = {
    "printer_model": Fact("Prusa MK4S", "ORCA", True),
    "orca_profiles": Fact({"machine": "Prusa MK4S 0.4 nozzle", "process": "0.20mm SPEED @MK4S 0.4",
                           "filament": "Prusa Generic PLA @MK4S"}, "ORCA", True),
    "orca_identity": _identity("a6e0656b4ca33570eca4b22fc8f0875b320a81bfc637cba442de6e27391acf92",
                               "a883e071bbbd1b7f40f23ea8ae0b0b4fa2419aae08efa4a3af377d0b4e33bebf",
                               "ee4d5ee2806a3786400f38d625832aac261a1451d7f2cc5e0eb51672dc252a21"),
    "bed_mm": Fact((250.0, 210.0), "ORCA", True),
    "max_print_height_mm": Fact(220.0, "ORCA", True),
    "bed_exclude_area": Fact((), "ORCA", True),
    "motion_envelope_mm": Fact((0.0, -4.0, 250.0, 210.0), "DERIVED", False),
    "travel_z_headroom_mm": Fact(1.0, "DERIVED", False),
    "stock_nozzle": Fact((0.4, "brass"), "PRUSA", False),
    "nozzle_sizes_mm": Fact((0.25, 0.4, 0.6, 0.8), "PRUSA", False),
    "max_hotend_c": Fact(290, "PRUSA", False),
    "max_bed_c": Fact(120, "PRUSA", False),
    "ideal_materials": Fact(("PLA", "PETG", "TPU", "ABS", "ASA", "PC", "PA"), "PRUSA", False),
    "tools": Fact(1, "PRUSA", False),
    "enclosed": Fact(False, "PRUSA", False),
}

COREONE = {
    "printer_model": Fact("Prusa CORE One", "ORCA", True),
    "orca_profiles": Fact({"machine": "Prusa CORE One 0.4 nozzle", "process": "0.20mm SPEED @CORE One 0.4",
                           "filament": "Prusament PLA @CORE One"}, "ORCA", True),
    "orca_identity": _identity("0f459a1a7c43c5686c14b52052c29ac75cdd4891c9250094885a16d3370db361",
                               "c4685e5445632fea68f223771f9d2a41c6602e0daaddcb60ef6593e4d6890aa6",
                               "91ee9aba52aa662d6ee067e5e3215771d2c7ec034730dde1263608ee621070bb"),
    "bed_mm": Fact((250.0, 220.0), "ORCA", True),
    "max_print_height_mm": Fact(270.0, "ORCA", True),
    "bed_exclude_area": Fact((), "ORCA", True),
    "motion_envelope_mm": Fact((0.0, -9.0, 250.0, 220.0), "DERIVED", False),
    "travel_z_headroom_mm": Fact(1.0, "DERIVED", False),
    "stock_nozzle": Fact((0.4, "brass"), "PRUSA", False),
    "nozzle_sizes_mm": Fact((0.25, 0.4, 0.6, 0.8), "PRUSA", False),
    "max_hotend_c": Fact(290, "PRUSA", False),
    "max_bed_c": Fact(120, "PRUSA", False),
    "ideal_materials": Fact(("PLA", "PETG", "TPU", "ABS", "ASA", "PC", "PA"), "PRUSA", False),
    "tools": Fact(1, "PRUSA", False),
    "enclosed": Fact(True, "PRUSA", False),
}

XL = {
    # The 5-tool XL: Print Buddy slices single-tool jobs only; the other toolheads are not driven.
    "printer_model": Fact("Prusa XL 5T", "ORCA", True),
    "orca_profiles": Fact({"machine": "Prusa XL 5T 0.4 nozzle", "process": "0.20mm Speed @Prusa XL 5T 0.4",
                           "filament": "Prusa Generic PLA @XL 5T"}, "ORCA", True),
    "orca_identity": _identity("374fecdd33aeb7fdf3d7e2fb9299d3870890fd2be7487feaaebe01502d2fc32a",
                               "58d27bec25b44655d8acacb1438e338702a706cbc249806583713f9676dce4b4",
                               "c52476ebdcdc2b86a24e8eb9ce8d837ee86f546da16ca40f2d7676d07a78e7d4"),
    "bed_mm": Fact((360.0, 360.0), "ORCA", True),
    "max_print_height_mm": Fact(360.0, "ORCA", True),
    # The flattened profile's bed_exclude_area is ["0x0"], a single origin point: no exclusion.
    "bed_exclude_area": Fact((), "ORCA", True),
    "motion_envelope_mm": Fact((0.0, 0.0, 360.0, 360.0), "DERIVED", False),
    "travel_z_headroom_mm": Fact(1.0, "DERIVED", False),
    "stock_nozzle": Fact((0.4, "brass"), "PRUSA", False),
    "nozzle_sizes_mm": Fact((0.25, 0.4, 0.6, 0.8), "PRUSA", False),
    "max_hotend_c": Fact(290, "PRUSA", False),
    "max_bed_c": Fact(120, "PRUSA", False),
    "ideal_materials": Fact(("PLA", "PETG", "TPU", "ABS", "ASA", "PC", "PA"), "PRUSA", False),
    "tools": Fact(5, "PRUSA", False),
    "enclosed": Fact(False, "PRUSA", False),
}

MINIPLUS = {
    # The MINI+ runs the MINI profiles: Orca's machine printer_model is "Prusa MINI".
    "printer_model": Fact("Prusa MINI", "ORCA", True),
    "orca_profiles": Fact({"machine": "Prusa MINI 0.4 nozzle", "process": "0.20mm Standard @MINI",
                           "filament": "Prusa Generic PLA"}, "ORCA", True),
    "orca_identity": _identity("b4bb5458837a5c118cb60d158010b7a1bb265696671ad32f1acdd207297f7d6d",
                               "fc4f42973415e07680e30915a1884ce02d1ea1284c1b599e3d2a0a772d70a8d8",
                               "cff434489029840d6f489e41f87aa46b422e8f9d4c7927dc0ed224e941780a97"),
    "bed_mm": Fact((180.0, 180.0), "ORCA", True),
    "max_print_height_mm": Fact(180.0, "ORCA", True),
    "bed_exclude_area": Fact((), "ORCA", True),
    "motion_envelope_mm": Fact((0.0, -2.0, 180.0, 180.0), "DERIVED", False),
    "travel_z_headroom_mm": Fact(1.0, "DERIVED", False),
    "stock_nozzle": Fact((0.4, "brass"), "PRUSA", False),
    "nozzle_sizes_mm": Fact((0.25, 0.4, 0.6, 0.8), "PRUSA", False),
    "max_hotend_c": Fact(280, "PRUSA", False),
    "max_bed_c": Fact(100, "PRUSA", False),
    "ideal_materials": Fact(("PLA", "PETG", "TPU"), "PRUSA", False),
    "tools": Fact(1, "PRUSA", False),
    "enclosed": Fact(False, "PRUSA", False),
}
