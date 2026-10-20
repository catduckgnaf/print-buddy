"""Sovol SV06 on stock Klipper: single extruder, PRINT_START/PRINT_END macros, no vendor API.

Quirks: multi-color and multi-plate sources are refused. The bed and height below are the values the SV06
has always sliced with here (they match templates/orca/sovol_sv06/machine.json). Templates: templates/orca/sovol_sv06.
"""
from ..base import PrinterModel
from ..klipper.adapter import KlipperAdapter

MODEL = PrinterModel(
    key="sovol.sv06",
    label="Sovol SV06 (Klipper)",
    adapter=KlipperAdapter,
    templates="sovol_sv06",
    baseline="protected-settings-baseline.sovol.sv06.json",
    supported_nozzle_sizes=(0.2, 0.4, 0.6, 0.8),
    supported_nozzle_types=("brass", "hardened_steel", "ruby", "tungsten_carbide", "diamond"),
    settings={
        "printer": {
            "name": "Sovol SV06",
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
