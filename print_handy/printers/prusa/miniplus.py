"""Prusa MINI+ (inherits prusa VENDOR). The MINI+: 180 mm cube, Bowden MINI platform. It runs Orca's MINI profiles (printer_model 'Prusa MINI').

Sourced values: facts.py (MINIPLUS); docs/PRUSA.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/prusa_miniplus (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import PrusaAdapter


class MiniPlusAdapter(PrusaAdapter):
    facts = facts.MINIPLUS


MODEL = PrinterModel(
    key="prusa.miniplus",
    label="Prusa MINI+",
    adapter=MiniPlusAdapter,
    templates="prusa_miniplus",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.prusa.miniplus.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass", "stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Prusa MINI+",
            "bed_mm": list(facts.MINIPLUS["bed_mm"].value),
            "max_print_height_mm": facts.MINIPLUS["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "ifs_slots": 1,
        },
    },
)
