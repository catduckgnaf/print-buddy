"""Bambu Lab A1 printer profile (inherits vendor.BAMBU_LAB) and its MODEL. Phase 1: offline only.

Quirks: the vendor start/end G-code parks the head off the bed on the wiper (X-48.2) and purge lane, so only
the Orca toolpath is held to the 256 mm bed. The AMS Lite is not driven: single filament only. Live telemetry,
upload and print control are refused. Sources: vendor.py and docs/BAMBU-LAB.md. Templates: templates/orca/bambulab_a1.
"""
from ..base import PrinterModel
from .adapter import BambuOfflineAdapter
from .vendor import BAMBU_LAB, Fact, PrinterProfile

PROFILE = PrinterProfile(
    key="a1",
    vendor=BAMBU_LAB,
    printer_model="Bambu Lab A1",
    vendor_start=";===== machine: A1 ",
    orca_profiles={"machine": "Bambu Lab A1 0.4 nozzle", "process": "0.20mm Standard @BBL A1",
                   "filament": "Generic PLA @BBL A1"},
    templates="bambulab_a1",
    facts={
        # Geometry: printable_area 0x0..256x256 and printable_height 256 (ORCA); Bambu also publishes 256 x 256 x 256 mm.
        "bed_mm": Fact((256.0, 256.0), "ORCA", True),
        "max_print_height_mm": Fact(256.0, "ORCA", True),
        # The A1 profile overrides the X1 family's corner exclusion with an empty list: no printable-area exclusion.
        "bed_exclude_area": Fact((), "ORCA", True),
        # Where the firmware's head-wrap (nozzle clump) check runs. Orca only marks it; it is not an exclusion.
        "head_wrap_detect_zone_mm": Fact(((226, 224), (256, 224), (256, 256), (226, 256)), "ORCA", True),
        # Extremes of the absolute XY moves in the vendor start/end/change/timelapse G-code (wiper at X-48.2,
        # cutter at X267, purge lane at Y-0.5 and Y262.5). Toolpath extrusion must still stay on the 256 mm bed.
        "motion_envelope_mm": Fact((-48.2, -0.5, 267.0, 262.5), "DERIVED", False),
        "gcode_flavor": Fact("marlin", "ORCA", True),
        # Stock 0.4 mm stainless steel; 0.2, 0.6 and 0.8 mm hotends exist. Only 0.4 has a template here.
        "stock_nozzle": Fact((0.4, "stainless_steel"), "ORCA", True),
        "nozzle_sizes_mm": Fact((0.2, 0.4, 0.6, 0.8), "BAMBU", False),
        "max_hotend_c": Fact(300, "BAMBU", False),
        "max_bed_c": Fact(100, "BAMBU", False),
        # Bambu lists PLA, PETG, TPU and PVA as ideal; ABS, ASA, PC, PA, PET and CF/GF fills as not recommended
        # (open frame). CF/GF and glow fills need a hardened steel nozzle.
        "ideal_materials": Fact(("PLA", "PETG", "TPU", "PVA"), "BAMBU", False),
        "not_recommended_materials": Fact(("ABS", "ASA", "PC", "PA", "PET"), "BAMBU", False),
        # AMS Lite: four spool holders feeding one hotend (A1 Combo). Not driven by Print Buddy yet.
        "ams": Fact(("AMS Lite", 4), "BAMBU", False),
    },
)


class A1Adapter(BambuOfflineAdapter):
    profile = PROFILE


MODEL = PrinterModel(
    key="bambulab.a1",
    label="Bambu Lab A1",
    adapter=A1Adapter,
    templates=PROFILE.templates,
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
            "bed_mm": list(PROFILE.value("bed_mm")),
            "max_print_height_mm": PROFILE.value("max_print_height_mm"),
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
