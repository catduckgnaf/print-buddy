"""Creality K1C (inherits creality VENDOR): stock Klipper + Moonraker, 220 x 220 mm bed, 250 mm height, single extruder, enclosed CoreXY.

Sourced values: facts.py (K1C); docs/CREALITY.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/creality_k1c (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import CrealityAdapter


class K1CAdapter(CrealityAdapter):
    facts = facts.K1C


MODEL = PrinterModel(
    key="creality.k1c",
    label="Creality K1C",
    adapter=K1CAdapter,
    templates="creality_k1c",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.creality.k1c.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass", "hardened_steel"),
    settings={
        "printer": {
            "name": "Creality K1C",
            "bed_mm": list(facts.K1C["bed_mm"].value),
            "max_print_height_mm": facts.K1C["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "ifs_slots": 1,
        },
    },
)
