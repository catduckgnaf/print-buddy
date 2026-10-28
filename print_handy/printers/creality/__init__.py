"""Creality vendor profile: the Klipper-based Creality OS line (Ender-3 V3 series, K1 series) on Moonraker, generated Orca templates, .gcode.

These printers run Creality OS, a Klipper firmware, behind a Moonraker endpoint, but the
generic Klipper profile's default bed matches only some of them by accident, so each model
carries its own sourced facts and identity-pinned generated templates (profiles.py) instead
of falling back to klipper.generic. The slicer owns the start sequence: the profiles open
with the printer's START_PRINT macro — or, on the Ender-3 V3 KE, a fully inline sequence —
so the start code is the template's, verbatim (start_code "creality"). Creality's Marlin
printers (the older Ender-3/CR line) are NOT this vendor: they keep the octoprint.marlin
route, and no model here pretends to cover them.
"""
from ..base import SHARED_SETTINGS, VendorProfile, merge_settings

VENDOR = VendorProfile(
    key="creality",
    label="Creality",
    connection="moonraker",
    start_code="creality",
    slicers=("orca",),
    fallback_slicer=None,
    file_formats=(".gcode",),
    settings=merge_settings(SHARED_SETTINGS, {
        "printer": {"firmware": "Klipper", "start_macro": "START_PRINT", "end_macro": "END_PRINT"},
    }),
)
