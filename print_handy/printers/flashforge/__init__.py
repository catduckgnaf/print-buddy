"""Flashforge vendor profile: ZMod Klipper behind Moonraker, START_PRINT ... MESH= start code, OrcaSlicer, .gcode.

Delivery format (#564): [printer] zmod_delivery_format defaults to "auto" for this
vendor — the sliced job uploads as .gcode.3mf when the printer reports ZMod
1.7.5+ (the first release with 3MF support), and as plain .gcode otherwise.
"""
from ..base import SHARED_SETTINGS, VendorProfile, merge_settings

VENDOR = VendorProfile(
    key="flashforge",
    label="Flashforge",
    connection="moonraker",
    start_code="zmod",
    settings=merge_settings(SHARED_SETTINGS, {
        "printer": {
            "firmware": "ZMod Klipper",
            # ZMod start/end live in each printer's Orca template; these names only document them.
            "start_macro": "START_PRINT",
            "end_macro": "END_PRINT",
            # #564: "auto" = .gcode.3mf on a known ZMod 1.7.5+, .gcode otherwise.
            "zmod_delivery_format": "auto",
        },
    }),
)
