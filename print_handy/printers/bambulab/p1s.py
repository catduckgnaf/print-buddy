"""Bambu Lab P1S (bambulab.p1s): shared Bambu vendor architecture and P1S-specific profile facts.

The P1S uses a 256 x 256 mm bed but 250 mm printable height and an 18 x 28 mm front-left bed exclusion. It is
enclosed and supports a 4-slot AMS, but Print Handy does not drive the AMS. Its Orca profile moves park in a
P1S-specific envelope; vendor G-code is checked against templates generated from the operator's OrcaSlicer.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class P1SAdapter(BambuAdapter):
    facts = facts.P1S


MODEL = PrinterModel(
    key="bambulab.p1s",
    label="Bambu Lab P1S",
    adapter=P1SAdapter,
    templates="bambulab_p1s",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.p1s.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab P1S",
            "bed_mm": list(facts.P1S["bed_mm"].value),
            "max_print_height_mm": facts.P1S["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            "filament_slots": 1,
        },
    },
)
