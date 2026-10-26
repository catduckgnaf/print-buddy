"""Prusa MK4S (inherits prusa VENDOR). The MK4S is the current MK4 iteration: 250 x 210 mm bed, 220 mm height, Nextruder, single tool.

Sourced values: facts.py (MK4S); docs/PRUSA.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/prusa_mk4s (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import PrusaAdapter


class MK4SAdapter(PrusaAdapter):
    facts = facts.MK4S


MODEL = PrinterModel(
    key="prusa.mk4s",
    label="Prusa MK4S",
    adapter=MK4SAdapter,
    templates="prusa_mk4s",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.prusa.mk4s.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass", "stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Prusa MK4S",
            "bed_mm": list(facts.MK4S["bed_mm"].value),
            "max_print_height_mm": facts.MK4S["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "ifs_slots": 1,
        },
    },
)
