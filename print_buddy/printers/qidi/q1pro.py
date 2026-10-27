"""Qidi Q1 Pro (inherits qidi VENDOR): stock Klipper + Moonraker, 245 x 245 mm bed, 240 mm height, single extruder, enclosed CoreXY.

Sourced values: facts.py (Q1PRO); docs/QIDI.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/qidi_q1pro (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import QidiAdapter


class Q1ProAdapter(QidiAdapter):
    facts = facts.Q1PRO


MODEL = PrinterModel(
    key="qidi.q1pro",
    label="Qidi Q1 Pro",
    adapter=Q1ProAdapter,
    templates="qidi_q1pro",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.qidi.q1pro.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("hardened_steel", "stainless_steel"),
    settings={
        "printer": {
            "name": "Qidi Q1 Pro",
            "bed_mm": list(facts.Q1PRO["bed_mm"].value),
            "max_print_height_mm": facts.Q1PRO["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
