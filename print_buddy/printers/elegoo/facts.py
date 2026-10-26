"""Sourced hardware facts and template provenance for Elegoo Neptune 4 printers.

Supplemental metadata only, following the bambulab/prusa facts conventions: ORCA values were
read directly from OrcaSlicer v2.4.2's Elegoo vendor profiles (vendor profiles 02.04.00.06)
with the shared flatten pipeline, ELEGOO values come from Elegoo's published product
specifications, DERIVED values are computed from the ORCA templates.

One disagreement matters: Elegoo markets the Neptune 4 bed as 235 x 235 mm (Plus 320 x 320,
Max 420 x 420) while the pinned Orca profiles slice to a printable area of 230 x 230 mm
(Plus 325 x 325, Max 426 x 426). bed_mm records the ORCA printable area — the value slicing
actually enforces — and the marketed figure is kept alongside it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fact:
    value: object
    source: str
    verified: bool


ORCA_RELEASE = ("v2.4.2", "8500fcdccaa10b5099ac20d252af3a7c560046f1")
ORCA_PROFILE_ROOT = "resources/profiles/Elegoo"
_IDENTITY_LABEL = "OrcaSlicer 2.4.2 (Elegoo vendor profiles 02.04.00.06)"
_FILAMENT_N4 = "fe0188ae6e4e0b5fcfdab17a70e59accd256cbe9ca7fdcbaf493141128388006"


def _identity(machine, process, filament):
    return Fact(({"label": _IDENTITY_LABEL, "vendor_version": "02.04.00.06",
                  "sha256": {"machine": machine, "process": process, "filament": filament}},), "ORCA", True)


def _neptune(model_name, machine, process, machine_sha, process_sha, bed, height, marketed):
    return {
        "printer_model": Fact(model_name, "ORCA", True),
        "orca_profiles": Fact({"machine": machine, "process": process,
                               "filament": "Elegoo PLA @EN4 Series"}, "ORCA", True),
        "orca_identity": _identity(machine_sha, process_sha, _FILAMENT_N4),
        "bed_mm": Fact(bed, "ORCA", True),
        "max_print_height_mm": Fact(height, "ORCA", True),
        "bed_exclude_area": Fact((), "ORCA", True),
        "motion_envelope_mm": Fact((0.0, 0.0, bed[0], bed[1]), "DERIVED", False),
        "travel_z_headroom_mm": Fact(1.0, "DERIVED", False),
        "stock_nozzle": Fact((0.4, "stainless_steel"), "ELEGOO", False),
        "nozzle_sizes_mm": Fact((0.2, 0.4, 0.6, 0.8, 1.0), "ORCA", True),
        "max_hotend_c": Fact(300, "ELEGOO", False),
        "max_bed_c": Fact(110, "ELEGOO", False),
        "ideal_materials": Fact(("PLA", "PETG", "TPU", "ABS", "ASA", "PC"), "ELEGOO", False),
        "tools": Fact(1, "ELEGOO", False),
        "enclosed": Fact(False, "ELEGOO", False),
        "marketed_bed_mm": Fact(marketed, "ELEGOO", False),
    }


NEPTUNE4 = _neptune(
    "Elegoo Neptune 4", "Elegoo Neptune 4 0.4 nozzle", "0.20mm Standard @Elegoo N4 0.4 nozzle",
    "0559b184001fb3c86508d15bf7c6ef0b6770dc59d53d3ef6856f1c279a03451a",
    "de69f0be2a3abee76a18c87deb4ce57abe32732a342abc18020cf9c2a4f010b8",
    (230.0, 230.0), 265.0, (235, 235))

NEPTUNE4PRO = _neptune(
    "Elegoo Neptune 4 Pro", "Elegoo Neptune 4 Pro 0.4 nozzle", "0.20mm Standard @Elegoo N4Pro 0.4 nozzle",
    "4dda0b54b8093ce1edc8714e75064830e69592b50ae696723bf1b9c7d2b6aa21",
    "3fbc64a93daadbca35dc112bb181d2329924cf37eca21c5f5cb043ba45f7588a",
    (230.0, 230.0), 265.0, (235, 235))

NEPTUNE4PLUS = _neptune(
    "Elegoo Neptune 4 Plus", "Elegoo Neptune 4 Plus 0.4 nozzle", "0.20mm Standard @Elegoo N4Plus 0.4 nozzle",
    "ed6596f9d5f6de2b6af65de459743a340443b8d31d4ff917bad22334214c5e64",
    "f8f137a5030a210383fb432677599051484d177ffb21233e4198405c54473a4f",
    (325.0, 325.0), 385.0, (320, 320))

NEPTUNE4MAX = _neptune(
    "Elegoo Neptune 4 Max", "Elegoo Neptune 4 Max 0.4 nozzle", "0.20mm Standard @Elegoo N4Max 0.4 nozzle",
    "c81f012fd7aa9fe168e3119ab175c1528c6248b119a6de2571d507c0c4a7af97",
    "471efa32df2554991436dc56b846962736af03a88ecbd83132f9b95e072c39a4",
    (426.0, 426.0), 480.0, (420, 420))
