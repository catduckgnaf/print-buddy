"""Elegoo vendor profile: Neptune 4 family on stock Klipper/Moonraker, generated Orca templates, .gcode.

The Neptune printers are ordinary Klipper machines, but the generic Klipper profile's default
bed matches none of them, so each model carries its own sourced facts and identity-pinned
generated templates (profiles.py) instead of falling back to klipper.generic. Their Orca
start code is a self-contained inline sequence (start_code "elegoo_inline"), not a PRINT_START
macro call. The Centauri line is a different vendor (elegoo_sdcp): closed firmware, no Klipper.
"""
from ..base import SHARED_SETTINGS, VendorProfile, merge_settings

VENDOR = VendorProfile(
    key="elegoo",
    label="Elegoo",
    connection="moonraker",
    start_code="elegoo_inline",
    slicers=("orca",),
    fallback_slicer=None,
    file_formats=(".gcode",),
    settings=merge_settings(SHARED_SETTINGS, {
        "printer": {"firmware": "Klipper", "start_macro": "PRINT_START", "end_macro": "PRINT_END"},
    }),
)
