"""Hardware facts for the Snapmaker U1.

Every value is the manufacturer's published specification, and every fact is
unverified: Print Handy has not measured a U1 or hashed a Snapmaker slicer
profile. Templates are generic files this project wrote, not those profiles.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fact:
    value: object
    source: str
    verified: bool


U1 = {
    "printer_model": Fact("Snapmaker U1", "SNAPMAKER", False),
    "bed_mm": Fact((270.0, 270.0), "SNAPMAKER", False),
    "max_print_height_mm": Fact(270.0, "SNAPMAKER", False),
    "tools": Fact(4, "SNAPMAKER", False),
    "kinematics": Fact("CoreXY", "SNAPMAKER", False),
    "stock_nozzle": Fact((0.4, "stainless_steel"), "SNAPMAKER", False),
    "max_hotend_c": Fact(300, "SNAPMAKER", False),
    "max_bed_c": Fact(100, "SNAPMAKER", False),
    "ideal_materials": Fact(("PLA", "PETG", "TPU", "PVA", "PCTG"), "SNAPMAKER", False),
    "enclosed": Fact(False, "SNAPMAKER", False),
}
