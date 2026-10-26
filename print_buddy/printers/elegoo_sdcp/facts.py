"""Sourced hardware facts and template provenance for the Elegoo Centauri Carbon.

Same conventions as elegoo/facts.py. The Centauri Carbon runs closed firmware and speaks
SDCP v3.0 on the LAN; it is a separate vendor (elegoo_sdcp) from the Klipper Neptunes.
Elegoo markets a 260 mm cube; the pinned Orca profile slices 256 x 256 x 256 mm with a real
exclusion rectangle at the front-right of the bed, and the ORCA values are recorded.
"""
from __future__ import annotations

from ..elegoo.facts import Fact

_IDENTITY_LABEL = "OrcaSlicer 2.4.2 (Elegoo vendor profiles 02.04.00.06)"

CENTAURI_CARBON = {
    "printer_model": Fact("Elegoo Centauri Carbon", "ORCA", True),
    "orca_profiles": Fact({"machine": "Elegoo Centauri Carbon 0.4 nozzle",
                           "process": "0.20mm Standard @Elegoo CC 0.4 nozzle",
                           "filament": "Elegoo PLA @ECC"}, "ORCA", True),
    "orca_identity": Fact(({"label": _IDENTITY_LABEL, "vendor_version": "02.04.00.06",
                            "sha256": {"machine": "89d9362556251bb8e8ba86fd3c5292250cdbf3939386a5e0cc6b2886d3875c6b",
                                       "process": "63138f2262732f8770dfeaee574cdc9f91f7fa0656031d2a557b0843411c89f5",
                                       "filament": "0aa0ddc000c02228370c550fce2f7d0fe491c86ac3daf167e529fd457455d749"}},), "ORCA", True),
    "bed_mm": Fact((256.0, 256.0), "ORCA", True),
    "max_print_height_mm": Fact(256.0, "ORCA", True),
    # Orca lists the exclusion as its four corners: (246,0) (256,0) (256,20) (246,20).
    "bed_exclude_area": Fact(((246.0, 0.0), (256.0, 0.0), (256.0, 20.0), (246.0, 20.0)), "ORCA", True),
    "motion_envelope_mm": Fact((0.0, 0.0, 256.0, 256.0), "DERIVED", False),
    "travel_z_headroom_mm": Fact(1.0, "DERIVED", False),
    "stock_nozzle": Fact((0.4, "hardened_steel"), "ELEGOO", False),
    "nozzle_sizes_mm": Fact((0.2, 0.4, 0.6, 0.8), "ORCA", True),
    "max_hotend_c": Fact(320, "ELEGOO", False),
    "max_bed_c": Fact(110, "ELEGOO", False),
    "ideal_materials": Fact(("PLA", "PETG", "TPU", "ABS", "ASA", "PC", "PA", "PA-CF", "PETG-CF"), "ELEGOO", False),
    "tools": Fact(1, "ELEGOO", False),
    "enclosed": Fact(True, "ELEGOO", False),
    "marketed_bed_mm": Fact((260, 260), "ELEGOO", False),
}
