"""Elegoo SDCP vendor profile: Centauri line on the closed-firmware SDCP v3.0 LAN protocol.

Separate from the `elegoo` vendor because nothing is shared at runtime: these printers run no
Klipper/Moonraker, speak an unauthenticated WebSocket protocol (SDCP, client.py), and accept
only .gcode/.bgcode files on their local storage. Print Buddy slices with profiles generated
from the operator's own OrcaSlicer (profiles.py, shared with the elegoo vendor) and, only when
the operator configures [elegoo_sdcp] host and adds `printer` to [delivery] methods, talks to
the printer: status, verified upload, gated print start, pause/resume/stop. Without the host
configured the vendor is offline: slicing, checks and Discord delivery only. See docs/ELEGOO.md.
"""
from ..base import SHARED_SETTINGS, VendorProfile, merge_settings

VENDOR = VendorProfile(
    key="elegoo_sdcp",
    label="Elegoo (SDCP)",
    connection="elegoo_sdcp",
    start_code="elegoo_sdcp",
    slicers=("orca",),
    fallback_slicer=None,
    file_formats=(".gcode", ".bgcode"),
    # `printer` is offered but NOT a default (the Bambu/Prusa precedent for an untested LAN path).
    delivery=("printer", "discord"),
    default_delivery=("discord",),
    settings=merge_settings(SHARED_SETTINGS, {
        "printer": {
            "firmware": "Elegoo SDCP",
            # Unused: the slicer owns the start/end G-code. Kept valid for settings checks.
            "start_macro": "PRINT_START",
            "end_macro": "PRINT_END",
        },
    }),
)
