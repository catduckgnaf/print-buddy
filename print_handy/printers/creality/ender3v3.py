"""Creality Ender-3 V3 (inherits creality VENDOR): stock Klipper + Moonraker, 220 x 220 mm bed, 250 mm height, single extruder, open-frame bed-slinger.

Sourced values: facts.py (ENDER3V3); docs/CREALITY.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/creality_ender3v3 (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import CrealityAdapter


class Ender3V3Adapter(CrealityAdapter):
    facts = facts.ENDER3V3


MODEL = PrinterModel(
    key="creality.ender3v3",
    label="Creality Ender-3 V3",
    adapter=Ender3V3Adapter,
    templates="creality_ender3v3",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.creality.ender3v3.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("hardened_steel", "brass"),
    settings={
        "printer": {
            "name": "Creality Ender-3 V3",
            "bed_mm": list(facts.ENDER3V3["bed_mm"].value),
            "max_print_height_mm": facts.ENDER3V3["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
