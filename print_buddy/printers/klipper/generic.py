"""Generic single extruder Klipper printer: stock Moonraker, PRINT_START/PRINT_END macros.

Quirks: multi-color and multi-plate sources are refused. Copy this file for a Klipper printer that needs
only different numbers, or override a key in config/local.toml. Templates: templates/orca/klipper_generic.
"""
from ..base import PrinterModel
from .adapter import KlipperAdapter

MODEL = PrinterModel(
    key="klipper.generic",
    label="Generic Klipper",
    adapter=KlipperAdapter,
    templates="klipper_generic",
    baseline="protected-settings-baseline.klipper.generic.json",
    settings={
        "printer": {
            "name": "Generic Klipper",
            "firmware": "Klipper",
            "start_macro": "PRINT_START",
            "end_macro": "PRINT_END",
            "bed_mm": [220.0, 220.0],
            "max_print_height_mm": 220.0,
            "nozzle_diameter_mm": 0.4,
            "ifs_slots": 1,
        },
        "layout": {
            "single_copy_edge_mm": 1.0,
            "multi_copy_edge_mm": 3.0,
            "merge_edge_margin_mm": 8.0,
            "merge_spacing_mm": 10.0,
        },
        "prime_tower": {
            "size_mm": 45.0,
            "part_clearance_mm": 8.0,
            "edge_mm": 10.0,
            "merge_slack_mm": 5.0,
        },
        "cold_pull": {"pla_trial": [220, 90], "petg": [245, 100]},
    },
)
