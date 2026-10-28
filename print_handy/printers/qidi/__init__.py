"""Qidi vendor profile: the Klipper-based Qidi line (Q1 Pro, X-Plus 3, X-Plus 4, X-Max 3, X-Smart 3) on Moonraker, generated Orca templates, .gcode.

Qidi's current printers run a Klipper firmware behind Moonraker, but the generic Klipper
profile's default bed matches none of them, so each model carries its own sourced facts and
identity-pinned generated templates (profiles.py) instead of falling back to
klipper.generic. The slicer owns the start sequence: every Qidi Orca profile opens with the
printer's PRINT_START macro (the Q1 Pro passes BED/HOTEND/CHAMBER) and continues with an
inline sequence from the template, so the start code is the template's, verbatim
(start_code "qidi"). The older X-Max / X-Plus / X-CF Pro generation is not registered.
"""
from ..base import SHARED_SETTINGS, VendorProfile, merge_settings

VENDOR = VendorProfile(
    key="qidi",
    label="Qidi",
    connection="moonraker",
    start_code="qidi",
    slicers=("orca",),
    fallback_slicer=None,
    file_formats=(".gcode",),
    settings=merge_settings(SHARED_SETTINGS, {
        "printer": {"firmware": "Klipper", "start_macro": "PRINT_START", "end_macro": "PRINT_END"},
    }),
)
