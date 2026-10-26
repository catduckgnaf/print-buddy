"""Elegoo Neptune 4 Plus (inherits elegoo VENDOR): stock Klipper + Moonraker, 325 x 325 mm bed, 385 mm height, single extruder.

Sourced values: facts.py (NEPTUNE4PLUS); docs/ELEGOO.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/elegoo_neptune4plus (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import ElegooNeptuneAdapter


class Neptune4PlusAdapter(ElegooNeptuneAdapter):
    facts = facts.NEPTUNE4PLUS


MODEL = PrinterModel(
    key="elegoo.neptune4plus",
    label="Elegoo Neptune 4 Plus",
    adapter=Neptune4PlusAdapter,
    templates="elegoo_neptune4plus",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.elegoo.neptune4plus.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Elegoo Neptune 4 Plus",
            "bed_mm": list(facts.NEPTUNE4PLUS["bed_mm"].value),
            "max_print_height_mm": facts.NEPTUNE4PLUS["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            "ifs_slots": 1,
        },
    },
)
