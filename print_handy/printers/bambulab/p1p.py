"""Bambu Lab P1P (inherits bambulab VENDOR). The P1P is the open-frame member of the P1/X1 platform: same 256 mm bed, 250 mm Orca height and front-left exclusion as the P1S, shipped without enclosure panels. Its AMS is not driven; jobs are single-color.

Sourced values: facts.py (P1P); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_p1p (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class P1PAdapter(BambuAdapter):
    facts = facts.P1P


MODEL = PrinterModel(
    key="bambulab.p1p",
    label="Bambu Lab P1P",
    adapter=P1PAdapter,
    templates="bambulab_p1p",
    generated_templates=True,
    vendor=VENDOR,
    color_system="multi_slot",
    baseline="protected-settings-baseline.bambulab.p1p.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab P1P",
            "bed_mm": list(facts.P1P["bed_mm"].value),
            "max_print_height_mm": facts.P1P["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            # Filament slots: the AMS unit's trays from the facts ("ams":
            # (unit, slots)); the AMS is this model's slot system (#671).
            "ifs_slots": facts.P1P["ams"].value[1],
        },
    },
)
