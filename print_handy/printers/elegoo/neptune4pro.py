"""Elegoo Neptune 4 Pro (inherits elegoo VENDOR): stock Klipper + Moonraker, 230 x 230 mm bed, 265 mm height, single extruder.

Sourced values: facts.py (NEPTUNE4PRO); docs/ELEGOO.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/elegoo_neptune4pro (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import ElegooNeptuneAdapter


class Neptune4ProAdapter(ElegooNeptuneAdapter):
    facts = facts.NEPTUNE4PRO


MODEL = PrinterModel(
    key="elegoo.neptune4pro",
    label="Elegoo Neptune 4 Pro",
    adapter=Neptune4ProAdapter,
    templates="elegoo_neptune4pro",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.elegoo.neptune4pro.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Elegoo Neptune 4 Pro",
            "bed_mm": list(facts.NEPTUNE4PRO["bed_mm"].value),
            "max_print_height_mm": facts.NEPTUNE4PRO["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            "ifs_slots": 1,
        },
    },
)
