"""Elegoo Neptune 4 Max (inherits elegoo VENDOR): stock Klipper + Moonraker, 426 x 426 mm bed, 480 mm height, single extruder.

Sourced values: facts.py (NEPTUNE4MAX); docs/ELEGOO.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/elegoo_neptune4max (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import ElegooNeptuneAdapter


class Neptune4MaxAdapter(ElegooNeptuneAdapter):
    facts = facts.NEPTUNE4MAX


MODEL = PrinterModel(
    key="elegoo.neptune4max",
    label="Elegoo Neptune 4 Max",
    adapter=Neptune4MaxAdapter,
    templates="elegoo_neptune4max",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.elegoo.neptune4max.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Elegoo Neptune 4 Max",
            "bed_mm": list(facts.NEPTUNE4MAX["bed_mm"].value),
            "max_print_height_mm": facts.NEPTUNE4MAX["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            "ifs_slots": 1,
        },
    },
)
