"""Bambu Lab X1 Carbon (inherits bambulab VENDOR). The X1 Carbon: X1 platform geometry with a hardened steel stock hotend for abrasive filaments. Its AMS is not driven; jobs are single-color.

Sourced values: facts.py (X1C); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_x1c (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class X1CAdapter(BambuAdapter):
    facts = facts.X1C


MODEL = PrinterModel(
    key="bambulab.x1c",
    label="Bambu Lab X1 Carbon",
    adapter=X1CAdapter,
    templates="bambulab_x1c",
    generated_templates=True,
    vendor=VENDOR,
    color_system="multi_slot",
    baseline="protected-settings-baseline.bambulab.x1c.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab X1 Carbon",
            "bed_mm": list(facts.X1C["bed_mm"].value),
            "max_print_height_mm": facts.X1C["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            # Filament slots: the AMS unit's trays from the facts ("ams":
            # (unit, slots)); the AMS is this model's slot system (#671).
            "ifs_slots": facts.X1C["ams"].value[1],
        },
    },
)
