"""Flashforge AD5X on ZMod Klipper: 4 slot IFS, native screen, stock firmware /detail.

Quirks: START_PRINT/END_PRINT come from the Orca template (the macro keys below are unused), the printer
screen owns the Z offset and mesh, and the physical sheet is 235 mm while Orca and the steppers allow 220.
ZMod-only code lives in printers/flashforge/zmod. Templates: templates/orca/flashforge_ad5x.
"""
from ..base import PrinterModel
from .adapter import ZmodAdapter

MODEL = PrinterModel(
    key="flashforge.ad5x",
    label="Flashforge AD5X (ZMod)",
    adapter=ZmodAdapter,
    templates="flashforge_ad5x",
    supported_nozzle_sizes=(0.25, 0.4, 0.6, 0.8),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Flashforge AD5X",
            "firmware": "ZMod Klipper",
            # The AD5X start/end live in its Orca template; these names only document them.
            "start_macro": "START_PRINT",
            "end_macro": "END_PRINT",
            # Usable print area, matching printable_area in the template machine.json.
            "bed_mm": [220.0, 220.0],
            "max_print_height_mm": 220.0,
            # Orca templates are tuned for this nozzle. Slicing refuses any other size.
            "nozzle_diameter_mm": 0.4,
            # Filament slots in the IFS.
            "ifs_slots": 4,
        },
        "layout": {
            # Distance from the bed edge for a lone copy and for multi copy plates.
            "single_copy_edge_mm": 1.0,
            "multi_copy_edge_mm": 3.0,
            # Gaps when several source plates are merged onto one bed.
            "merge_edge_margin_mm": 8.0,
            "merge_spacing_mm": 10.0,
        },
        "prime_tower": {
            "size_mm": 45.0,
            # Clearance between the tower and any part.
            "part_clearance_mm": 8.0,
            # Closest the tower may sit to the bed edge.
            "edge_mm": 10.0,
            # Extra room reserved for the tower when merging plates.
            "merge_slack_mm": 5.0,
        },
        # Profile name = [hot C, cold C]
        "cold_pull": {"pla_trial": [220, 90], "petg": [245, 100]},
    },
)
