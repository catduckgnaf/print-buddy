"""Creality K1 (inherits creality VENDOR): stock Klipper + Moonraker, 220 x 220 mm bed, 250 mm height, single extruder, enclosed CoreXY.

Sourced values: facts.py (K1); docs/CREALITY.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/creality_k1 (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import CrealityAdapter


class K1Adapter(CrealityAdapter):
    facts = facts.K1


MODEL = PrinterModel(
    key="creality.k1",
    label="Creality K1",
    adapter=K1Adapter,
    templates="creality_k1",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.creality.k1.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass", "hardened_steel"),
    settings={
        "printer": {
            "name": "Creality K1",
            "bed_mm": list(facts.K1["bed_mm"].value),
            "max_print_height_mm": facts.K1["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "filament_slots": 1,
        },
    },
)
