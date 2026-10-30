"""Creality K1 Max (inherits creality VENDOR): stock Klipper + Moonraker, 300 x 300 mm bed, 300 mm height, single extruder, enclosed CoreXY.

Sourced values: facts.py (K1MAX); docs/CREALITY.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/creality_k1max (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import CrealityAdapter


class K1MaxAdapter(CrealityAdapter):
    facts = facts.K1MAX


MODEL = PrinterModel(
    key="creality.k1max",
    label="Creality K1 Max",
    adapter=K1MaxAdapter,
    templates="creality_k1max",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.creality.k1max.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass", "hardened_steel"),
    settings={
        "printer": {
            "name": "Creality K1 Max",
            "bed_mm": list(facts.K1MAX["bed_mm"].value),
            "max_print_height_mm": facts.K1MAX["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "filament_slots": 1,
        },
    },
)
