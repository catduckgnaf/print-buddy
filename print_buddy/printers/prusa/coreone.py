"""Prusa CORE One (inherits prusa VENDOR). The CORE One is Prusa's enclosed CoreXY: 250 x 220 mm bed, 270 mm height, single tool. The CORE One L (300 x 300) is a follow-up profile on #242 once its Orca identity is pinned.

Sourced values: facts.py (COREONE); docs/PRUSA.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/prusa_coreone (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import PrusaAdapter


class CoreOneAdapter(PrusaAdapter):
    facts = facts.COREONE


MODEL = PrinterModel(
    key="prusa.coreone",
    label="Prusa CORE One",
    adapter=CoreOneAdapter,
    templates="prusa_coreone",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.prusa.coreone.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass", "stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Prusa CORE One",
            "bed_mm": list(facts.COREONE["bed_mm"].value),
            "max_print_height_mm": facts.COREONE["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "ifs_slots": 1,
        },
    },
)
