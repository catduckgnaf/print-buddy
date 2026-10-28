"""Bambu Lab X1 (inherits bambulab VENDOR). The original X1: the X1 platform geometry (256 mm bed, 250 mm Orca height, front-left exclusion) with its own machine profile and a stainless stock hotend. Its AMS is not driven; jobs are single-color.

Sourced values: facts.py (X1); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_x1 (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class X1Adapter(BambuAdapter):
    facts = facts.X1


MODEL = PrinterModel(
    key="bambulab.x1",
    label="Bambu Lab X1",
    adapter=X1Adapter,
    templates="bambulab_x1",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.x1.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab X1",
            "bed_mm": list(facts.X1["bed_mm"].value),
            "max_print_height_mm": facts.X1["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            "ifs_slots": 1,
        },
    },
)
