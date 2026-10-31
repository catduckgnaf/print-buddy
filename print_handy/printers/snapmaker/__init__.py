"""Snapmaker vendor profile: the U1 tool changer on its Klipper-based firmware and Moonraker.

The U1 is a four-toolhead machine, not an IFS feeder. Print Handy ships generic
Orca templates it wrote itself. Snapmaker's and OrcaSlicer's own profiles are
not copied. Nothing here has been checked on a U1.
"""
from ..base import SHARED_SETTINGS, VendorProfile, merge_settings

VENDOR = VendorProfile(
    key="snapmaker",
    label="Snapmaker",
    connection="moonraker",
    start_code="klipper_macro",
    slicers=("orca",),
    file_formats=(".gcode",),
    settings=merge_settings(SHARED_SETTINGS, {
        "printer": {"firmware": "Klipper", "start_macro": "PRINT_START", "end_macro": "PRINT_END"},
    }),
)
