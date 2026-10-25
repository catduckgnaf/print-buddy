"""Stock Flashforge vendor profile: LAN HTTP, slicer-owned start G-code, one tool.

This is a separate vendor from flashforge (ZMod over Moonraker) because a vendor has one
connection and one start-code family. Stock Adventurer firmware takes the slicer's plain
G-code over its own HTTP API and does not speak Moonraker. The AD5X IFS has four bays;
print start reads occupancy from /detail and is not verified on a live printer.
See flashforge_stock/client.py.
"""
from ..base import SHARED_SETTINGS, VendorProfile, merge_settings

VENDOR = VendorProfile(
    key="flashforge_stock",
    label="Flashforge stock",
    connection="flashforge_stock",
    start_code="flashforge_stock",
    settings=merge_settings(SHARED_SETTINGS, {
        "printer": {
            "firmware": "Flashforge stock",
            # Unused: the slicer owns start and end. The names stay valid for the settings check.
            "start_macro": "PRINT_START",
            "end_macro": "PRINT_END",
        },
    }),
)
