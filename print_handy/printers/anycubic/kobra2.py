"""Anycubic Kobra 2 (inherits anycubic VENDOR): stock Klipper + Moonraker, 220 x 220 mm bed, 250 mm height, single extruder, open-frame bed-slinger.

Sourced values: facts.py (KOBRA2); docs/ANYCUBIC.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/anycubic_kobra2 (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import AnycubicAdapter


class Kobra2Adapter(AnycubicAdapter):
    facts = facts.KOBRA2


MODEL = PrinterModel(
    key="anycubic.kobra2",
    label="Anycubic Kobra 2",
    adapter=Kobra2Adapter,
    templates="anycubic_kobra2",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.anycubic.kobra2.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass",),
    settings={
        "printer": {
            "name": "Anycubic Kobra 2",
            "bed_mm": list(facts.KOBRA2["bed_mm"].value),
            "max_print_height_mm": facts.KOBRA2["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "ifs_slots": 1,
        },
    },
)
