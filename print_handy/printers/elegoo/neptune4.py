"""Elegoo Neptune 4 (inherits elegoo VENDOR): stock Klipper + Moonraker, 230 x 230 mm bed, 265 mm height, single extruder.

Sourced values: facts.py (NEPTUNE4); docs/ELEGOO.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/elegoo_neptune4 (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import ElegooNeptuneAdapter


class Neptune4Adapter(ElegooNeptuneAdapter):
    facts = facts.NEPTUNE4


MODEL = PrinterModel(
    key="elegoo.neptune4",
    label="Elegoo Neptune 4",
    adapter=Neptune4Adapter,
    templates="elegoo_neptune4",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.elegoo.neptune4.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Elegoo Neptune 4",
            "bed_mm": list(facts.NEPTUNE4["bed_mm"].value),
            "max_print_height_mm": facts.NEPTUNE4["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            "filament_slots": 1,
        },
    },
)
