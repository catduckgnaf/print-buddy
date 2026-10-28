"""Creality Ender-3 V3 KE (inherits creality VENDOR): stock Klipper + Moonraker, 220 x 220 mm bed, 245 mm height, single extruder, open-frame bed-slinger.

Sourced values: facts.py (ENDER3V3KE); docs/CREALITY.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/creality_ender3v3ke (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import CrealityAdapter


class Ender3V3KEAdapter(CrealityAdapter):
    facts = facts.ENDER3V3KE


MODEL = PrinterModel(
    key="creality.ender3v3ke",
    label="Creality Ender-3 V3 KE",
    adapter=Ender3V3KEAdapter,
    templates="creality_ender3v3ke",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.creality.ender3v3ke.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass", "hardened_steel"),
    settings={
        "printer": {
            "name": "Creality Ender-3 V3 KE",
            "bed_mm": list(facts.ENDER3V3KE["bed_mm"].value),
            "max_print_height_mm": facts.ENDER3V3KE["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "ifs_slots": 1,
        },
    },
)
