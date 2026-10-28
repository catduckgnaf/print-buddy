"""Bambu Lab A2L (inherits bambulab VENDOR). The A2L is the large-format A-series bed-slinger: a 330 x 320 mm
bed and 325 mm height, an open frame with an AMS Lite, and — as its OrcaSlicer machine profile declares —
a single 0.4 mm nozzle. It exists only in OrcaSlicer v2.5.0-alpha's BBL profiles, which is the release
Print Handy ships since #356. Offline slicing, fit checks and G-code validation, plus the vendor's opt-in
read-only LAN status, like the A1.

Sourced values: facts.py (A2L); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_a2l (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class A2LAdapter(BambuAdapter):
    facts = facts.A2L


MODEL = PrinterModel(
    key="bambulab.a2l",
    label="Bambu Lab A2L",
    adapter=A2LAdapter,
    templates="bambulab_a2l",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.a2l.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab A2L",
            "bed_mm": list(facts.A2L["bed_mm"].value),
            "max_print_height_mm": facts.A2L["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            "ifs_slots": 1,
        },
    },
)
