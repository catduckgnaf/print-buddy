"""Sovol SV06 on stock Klipper: single extruder, PRINT_START/PRINT_END macros, no vendor API.

Quirks: multi-color and multi-plate sources are refused. The bed and height below are the SV06's real
build volume, 220 x 220 x 250 mm, matching templates/orca/sovol_sv06/machine.json and the sovol_marlin.sv06
entry. Templates: templates/orca/sovol_sv06.
"""
from ..base import PrinterModel
from . import VENDOR
from ..klipper.adapter import KlipperAdapter

MODEL = PrinterModel(
    key="sovol.sv06",
    label="Sovol SV06 (Klipper)",
    adapter=KlipperAdapter,
    templates="sovol_sv06",
    baseline="protected-settings-baseline.sovol.sv06.json",
    supported_nozzle_sizes=(0.2, 0.4, 0.6, 0.8),
    supported_nozzle_types=("brass", "hardened_steel", "ruby", "tungsten_carbide", "diamond"),
    vendor=VENDOR,
    # Printer-specific defaults; firmware, macros, margins, prime tower and cold pull come from VENDOR.
    settings={
        "printer": {
            "name": "Sovol SV06",
            "bed_mm": [220.0, 220.0],
            "max_print_height_mm": 250.0,
            "nozzle_diameter_mm": 0.4,
            "filament_slots": 1,
        },
    },
)
