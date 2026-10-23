"""Bambu Lab A1, phase 1: offline slicing, fit checks and G-code validation. No live connection.

Quirks: the vendor start/end G-code (OrcaSlicer v2.4.2 BBL profile) parks the head off the bed on the wiper
(X-48.2) and purge lane, so only the Orca toolpath is held to the 256 mm bed. The AMS Lite is not driven:
single filament only. Live telemetry, upload and print control are refused. P1S is a later, separate model.
Values and sources: capabilities.py and docs/BAMBU-A1.md. Templates: templates/orca/bambulab_a1.
"""
from ..base import PrinterModel
from .adapter import BambuOfflineAdapter
from .capabilities import A1

MODEL = PrinterModel(
    key="bambulab.a1",
    label="Bambu Lab A1",
    adapter=BambuOfflineAdapter,
    templates="bambulab_a1",
    baseline="protected-settings-baseline.bambulab.a1.json",
    # Only the 0.4 mm vendor profile is templated; 0.2, 0.6 and 0.8 mm hotends exist but are refused here.
    supported_nozzle_sizes=(0.4,),
    # Stock stainless steel, or the hardened steel hotend Bambu requires for CF/GF and glow filaments.
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab A1",
            "firmware": "Bambu Lab (offline handoff only)",
            # Unused: the vendor start/end G-code comes from the Orca template. Kept valid for settings checks.
            "start_macro": "PRINT_START",
            "end_macro": "PRINT_END",
            "bed_mm": list(A1["bed_mm"].value),
            "max_print_height_mm": A1["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            "ifs_slots": 1,
        },
        "layout": {
            "single_copy_edge_mm": 1.0,
            "multi_copy_edge_mm": 3.0,
            "merge_edge_margin_mm": 8.0,
            "merge_spacing_mm": 10.0,
        },
        "prime_tower": {
            "size_mm": 35.0,
            "part_clearance_mm": 8.0,
            "edge_mm": 10.0,
            "merge_slack_mm": 5.0,
        },
        "cold_pull": {"pla_trial": [220, 90], "petg": [245, 100]},
    },
)
