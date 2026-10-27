"""Creality Ender-3 V3 Plus (inherits creality VENDOR): stock Klipper + Moonraker, 300 x 300 mm bed, 330 mm height, single extruder, open-frame bed-slinger.

Sourced values: facts.py (ENDER3V3PLUS); docs/CREALITY.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/creality_ender3v3plus (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import CrealityAdapter


class Ender3V3PlusAdapter(CrealityAdapter):
    facts = facts.ENDER3V3PLUS


MODEL = PrinterModel(
    key="creality.ender3v3plus",
    label="Creality Ender-3 V3 Plus",
    adapter=Ender3V3PlusAdapter,
    templates="creality_ender3v3plus",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.creality.ender3v3plus.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("hardened_steel", "brass"),
    settings={
        "printer": {
            "name": "Creality Ender-3 V3 Plus",
            "bed_mm": list(facts.ENDER3V3PLUS["bed_mm"].value),
            "max_print_height_mm": facts.ENDER3V3PLUS["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
