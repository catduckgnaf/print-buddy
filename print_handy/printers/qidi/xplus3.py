"""Qidi X-Plus 3 (inherits qidi VENDOR): stock Klipper + Moonraker, 280 x 280 mm bed, 270 mm height, single extruder, enclosed CoreXY.

Sourced values: facts.py (XPLUS3); docs/QIDI.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/qidi_xplus3 (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import QidiAdapter


class XPlus3Adapter(QidiAdapter):
    facts = facts.XPLUS3


MODEL = PrinterModel(
    key="qidi.xplus3",
    label="Qidi X-Plus 3",
    adapter=XPlus3Adapter,
    templates="qidi_xplus3",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.qidi.xplus3.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("hardened_steel", "stainless_steel"),
    settings={
        "printer": {
            "name": "Qidi X-Plus 3",
            "bed_mm": list(facts.XPLUS3["bed_mm"].value),
            "max_print_height_mm": facts.XPLUS3["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "filament_slots": 1,
        },
    },
)
