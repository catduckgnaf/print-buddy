"""Qidi X-Max 3 (inherits qidi VENDOR): stock Klipper + Moonraker, 325 x 325 mm bed, 315 mm height, single extruder, enclosed CoreXY.

Sourced values: facts.py (XMAX3); docs/QIDI.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/qidi_xmax3 (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import QidiAdapter


class XMax3Adapter(QidiAdapter):
    facts = facts.XMAX3


MODEL = PrinterModel(
    key="qidi.xmax3",
    label="Qidi X-Max 3",
    adapter=XMax3Adapter,
    templates="qidi_xmax3",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.qidi.xmax3.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("hardened_steel", "stainless_steel"),
    settings={
        "printer": {
            "name": "Qidi X-Max 3",
            "bed_mm": list(facts.XMAX3["bed_mm"].value),
            "max_print_height_mm": facts.XMAX3["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "filament_slots": 1,
        },
    },
)
