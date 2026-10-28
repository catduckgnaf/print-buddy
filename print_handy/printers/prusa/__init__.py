"""Prusa vendor profile: PrusaLink LAN, slicer-owned start G-code, OrcaSlicer, .gcode/.bgcode.

Print Handy slices with profiles generated from the operator's own OrcaSlicer (profiles.py) and,
only when the operator configures [prusa] link_host and adds `printer` to [delivery] methods,
talks to the printer through its local PrusaLink API (client.py): status, verified upload, gated
print start, pause/resume/stop. PrusaConnect cloud is not used. Without the host configured the
vendor is offline: slicing, checks and Discord delivery only. See docs/PRUSA.md.
"""
from ..base import SHARED_SETTINGS, VendorProfile, merge_settings

VENDOR = VendorProfile(
    key="prusa",
    label="Prusa",
    connection="prusalink",
    start_code="prusa",
    slicers=("orca",),
    fallback_slicer=None,
    file_formats=(".gcode", ".bgcode"),
    # `printer` is offered but NOT a default (the Bambu precedent for an untested LAN path):
    # the Start button appears only when the operator adds "printer" to [delivery] methods.
    delivery=("printer", "discord"),
    default_delivery=("discord",),
    settings=merge_settings(SHARED_SETTINGS, {
        "printer": {
            "firmware": "Prusa Buddy (PrusaLink)",
            # Unused: the slicer owns the start/end G-code. Kept valid for settings checks.
            "start_macro": "PRINT_START",
            "end_macro": "PRINT_END",
        },
    }),
)
