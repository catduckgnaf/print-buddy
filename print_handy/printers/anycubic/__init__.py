"""Anycubic vendor profile: the Klipper-based Kobra 2 family on Moonraker, generated Orca templates, .gcode.

These printers run Anycubic's closed, Klipper-derived firmware, which exposes no stock
Moonraker endpoint, so this vendor covers installs where Moonraker is exposed — community
firmware such as Rinkhals (mainline Klipper + Moonraker) — and nothing here claims the
stock firmware can be driven. Each model carries its own sourced facts and identity-pinned
generated templates (profiles.py) instead of falling back to klipper.generic, whose
default bed matches none of them. The slicer owns the start sequence: the profiles run a
fully inline sequence with no start macro, so the start code is the template's, verbatim
(start_code "anycubic"). Anycubic's Marlin printers (the Mega/Vyper-era machines and the
first Kobra line) are NOT this vendor: they keep the octoprint route, and no model here
pretends to cover them. The Kobra 3 / S1 generation is not covered either: its profiles
open with Anycubic's proprietary G9111 start command for the closed Kobra OS firmware,
which no Moonraker host runs.
"""
from ..base import SHARED_SETTINGS, VendorProfile, merge_settings

VENDOR = VendorProfile(
    key="anycubic",
    label="Anycubic",
    connection="moonraker",
    start_code="anycubic",
    slicers=("orca",),
    fallback_slicer=None,
    file_formats=(".gcode",),
    settings=merge_settings(SHARED_SETTINGS, {
        # These profiles call no start macro (the sequences are fully inline); the names
        # stay valid for the settings check and are not sent.
        "printer": {"firmware": "Klipper", "start_macro": "PRINT_START", "end_macro": "PRINT_END"},
    }),
)
