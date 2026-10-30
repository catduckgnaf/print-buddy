"""Anycubic Kobra 2 Pro (inherits anycubic VENDOR): stock Klipper + Moonraker, 220 x 220 mm bed, 250 mm height, single extruder, open-frame bed-slinger.

Sourced values: facts.py (KOBRA2PRO); docs/ANYCUBIC.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/anycubic_kobra2pro (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import AnycubicAdapter


class Kobra2ProAdapter(AnycubicAdapter):
    facts = facts.KOBRA2PRO


MODEL = PrinterModel(
    key="anycubic.kobra2pro",
    label="Anycubic Kobra 2 Pro",
    adapter=Kobra2ProAdapter,
    templates="anycubic_kobra2pro",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.anycubic.kobra2pro.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass",),
    settings={
        "printer": {
            "name": "Anycubic Kobra 2 Pro",
            "bed_mm": list(facts.KOBRA2PRO["bed_mm"].value),
            "max_print_height_mm": facts.KOBRA2PRO["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "filament_slots": 1,
        },
    },
)
