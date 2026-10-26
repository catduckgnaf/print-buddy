"""Bambu Lab A1 mini (inherits bambulab VENDOR). The A1 mini is the A1's smaller sibling: a 180 mm bed, no printable-area exclusion, and an AMS Lite that Print Buddy does not drive. It shares the vendor LAN path (MQTT/FTPS/project_file) and generated-template flow with every other Bambu Lab model.

Sourced values: facts.py (A1MINI); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_a1mini (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class A1MiniAdapter(BambuAdapter):
    facts = facts.A1MINI


MODEL = PrinterModel(
    key="bambulab.a1mini",
    label="Bambu Lab A1 mini",
    adapter=A1MiniAdapter,
    templates="bambulab_a1mini",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.a1mini.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab A1 mini",
            "bed_mm": list(facts.A1MINI["bed_mm"].value),
            "max_print_height_mm": facts.A1MINI["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            "ifs_slots": 1,
        },
    },
)
