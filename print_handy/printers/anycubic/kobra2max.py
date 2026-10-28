"""Anycubic Kobra 2 Max (inherits anycubic VENDOR): stock Klipper + Moonraker, 420 x 420 mm bed, 500 mm height, single extruder, open-frame bed-slinger.

Sourced values: facts.py (KOBRA2MAX); docs/ANYCUBIC.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/anycubic_kobra2max (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import AnycubicAdapter


class Kobra2MaxAdapter(AnycubicAdapter):
    facts = facts.KOBRA2MAX


MODEL = PrinterModel(
    key="anycubic.kobra2max",
    label="Anycubic Kobra 2 Max",
    adapter=Kobra2MaxAdapter,
    templates="anycubic_kobra2max",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.anycubic.kobra2max.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass",),
    settings={
        "printer": {
            "name": "Anycubic Kobra 2 Max",
            "bed_mm": list(facts.KOBRA2MAX["bed_mm"].value),
            "max_print_height_mm": facts.KOBRA2MAX["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "ifs_slots": 1,
        },
    },
)
