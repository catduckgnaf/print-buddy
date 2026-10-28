"""Sourced hardware facts and template provenance for Elegoo Neptune 4 printers.

Supplemental metadata only, following the bambulab/prusa facts conventions: ORCA values were
read directly from the Elegoo vendor profiles of OrcaSlicer v2.4.2 (vendor profiles
02.04.00.06) and v2.5.0-alpha (02.04.00.11, as its JSON tree and as the packed preset cache
an installed 2.5 serves) with the shared flatten pipeline, ELEGOO values come from Elegoo's published product
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


ORCA_RELEASE = ("v2.5.0-alpha", "3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2")
ORCA_PROFILE_ROOT = "resources/profiles/Elegoo"
_IDENTITY_LABEL = "OrcaSlicer 2.4.2 (Elegoo vendor profiles 02.04.00.06)"
_IDENTITY_LABEL_25A = "OrcaSlicer 2.5.0-alpha (Elegoo vendor profiles 02.04.00.11)"
_IDENTITY_LABEL_25A_PACKED = "OrcaSlicer 2.5.0-alpha (Elegoo vendor profiles 02.04.00.11, packed cache)"
_FILAMENT_N4 = "fe0188ae6e4e0b5fcfdab17a70e59accd256cbe9ca7fdcbaf493141128388006"
# The same shared filament profile under 2.5.0-alpha, per packaging (see bambulab/facts.py).
_FILAMENT_N4_25A = "4f0a4133320f0ea3f045d15b0c8331c4d9ca6d339f0abf0bcf43c02d915642c4"
_FILAMENT_N4_25A_PACKED = "cf65738dbbd56b1cc558d6c3487cc53aee9b13138dc313a7d0c3c06e9f498b72"


def _identities(machines, processes):
    """The checked identities for a Neptune, oldest first: OrcaSlicer 2.4.2's JSON tree, then
    OrcaSlicer 2.5.0-alpha's tree and its packed preset cache. All four Neptunes share the one
    filament profile, so only the machine and process hashes are per-model."""
    return Fact((
        {"label": _IDENTITY_LABEL, "vendor_version": "02.04.00.06",
          "sha256": {"machine": machines[0], "process": processes[0], "filament": _FILAMENT_N4}},
        {"label": _IDENTITY_LABEL_25A, "vendor_version": "02.04.00.11",
          "sha256": {"machine": machines[1], "process": processes[1], "filament": _FILAMENT_N4_25A}},
        {"label": _IDENTITY_LABEL_25A_PACKED, "vendor_version": "02.04.00.11",
          "sha256": {"machine": machines[2], "process": processes[2], "filament": _FILAMENT_N4_25A_PACKED}},
    ), "ORCA", True)


def _neptune(model_name, machine, process, machines, processes, bed, height, marketed):
    return {
        "printer_model": Fact(model_name, "ORCA", True),
        "orca_profiles": Fact({"machine": machine, "process": process,
                               "filament": "Elegoo PLA @EN4 Series"}, "ORCA", True),
        "orca_identity": _identities(machines, processes),
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
    ("0559b184001fb3c86508d15bf7c6ef0b6770dc59d53d3ef6856f1c279a03451a", "35d3db360b9ee5dd896743c0455bb2cfb37170070296f124b5215a6e0963f4ef", "bb44a83a075d6b64c50c20672b833e66d5d0a8350d23c63dc376fa553fa5aa6e"),
    ("de69f0be2a3abee76a18c87deb4ce57abe32732a342abc18020cf9c2a4f010b8", "ca8a2f597bcbd619f0cef8851cffd1f78a361a5831c74269034b35034f8c0999", "b8e63ce3011e02a6e155c174f3de343bde5fc3bd2fbebc1a680552830226b06f"),
    (230.0, 230.0), 265.0, (235, 235))

NEPTUNE4PRO = _neptune(
    "Elegoo Neptune 4 Pro", "Elegoo Neptune 4 Pro 0.4 nozzle", "0.20mm Standard @Elegoo N4Pro 0.4 nozzle",
    ("4dda0b54b8093ce1edc8714e75064830e69592b50ae696723bf1b9c7d2b6aa21", "f0508d8e41a5c61c3907523e10860d2cf243d61b457c5c6bed580596311575f4", "4eb275e73a69ce6381b6144629ee934a74481078e56e89e57762afde6726bb1e"),
    ("3fbc64a93daadbca35dc112bb181d2329924cf37eca21c5f5cb043ba45f7588a", "113b4cac2f8659b2d0ab26c91b41dc124dd2b601d6ad07b44009f012cde983b6", "3d3a50ba87b5793a0b627cf12bc87923f1d3d458034d1dba3984f8ab997513c2"),
    (230.0, 230.0), 265.0, (235, 235))

NEPTUNE4PLUS = _neptune(
    "Elegoo Neptune 4 Plus", "Elegoo Neptune 4 Plus 0.4 nozzle", "0.20mm Standard @Elegoo N4Plus 0.4 nozzle",
    ("ed6596f9d5f6de2b6af65de459743a340443b8d31d4ff917bad22334214c5e64", "3dc31ba44feeffb18c6f9a076a7bd63ceedcb1f8b490ec2a904f14c7dcea21d4", "82e927eb3f748bbe900d87ef762dfc0c8c8a03aab63d24f8435631ec89e96679"),
    ("f8f137a5030a210383fb432677599051484d177ffb21233e4198405c54473a4f", "2af81ebcff1eb05f82618b30e5c52d6a62f1a8b1168aeda4623de736c31dcdf3", "4806bfe3cff1bc55bea32b5364b08081b9dbd63ab0c289b3a0370d043ec44c4c"),
    (325.0, 325.0), 385.0, (320, 320))

NEPTUNE4MAX = _neptune(
    "Elegoo Neptune 4 Max", "Elegoo Neptune 4 Max 0.4 nozzle", "0.20mm Standard @Elegoo N4Max 0.4 nozzle",
    ("c81f012fd7aa9fe168e3119ab175c1528c6248b119a6de2571d507c0c4a7af97", "24450502d19a879604d43d7bb06321c97897cbb1168ffebb68335bff2e25e4d5", "a9864b00724bf8c73adbcc127e14005ce6783c5f0daf3618c31a976f288cd894"),
    ("471efa32df2554991436dc56b846962736af03a88ecbd83132f9b95e072c39a4", "64df1b5392656065643c5b2693a98038b4f2d09deb6cf7c29b1332b5feebdbad", "cac24f355eb97be71e70f514c78d9fa0643661441676fdf150da6eebaab25c7b"),
    (426.0, 426.0), 480.0, (420, 420))
