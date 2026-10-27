"""Qidi X-Smart 3 (inherits qidi VENDOR): stock Klipper + Moonraker, 175 x 180 mm printable area, 170 mm height, single extruder, enclosed CoreXY.

Sourced values: facts.py (XSMART3); docs/QIDI.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/qidi_xsmart3 (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import QidiAdapter


class XSmart3Adapter(QidiAdapter):
    facts = facts.XSMART3


MODEL = PrinterModel(
    key="qidi.xsmart3",
    label="Qidi X-Smart 3",
    adapter=XSmart3Adapter,
    templates="qidi_xsmart3",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.qidi.xsmart3.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("hardened_steel", "stainless_steel"),
    settings={
        "printer": {
            "name": "Qidi X-Smart 3",
            "bed_mm": list(facts.XSMART3["bed_mm"].value),
            "max_print_height_mm": facts.XSMART3["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
