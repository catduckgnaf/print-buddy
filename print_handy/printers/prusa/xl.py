"""Prusa XL (5-tool) (inherits prusa VENDOR). The XL with five toolheads: 360 mm cube build volume. Print Handy slices single-tool jobs (tool 0) only; the other toolheads and the MMU-style multi-tool flow are not driven.

Sourced values: facts.py (XL); docs/PRUSA.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/prusa_xl (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import PrusaAdapter


class XLAdapter(PrusaAdapter):
    facts = facts.XL


MODEL = PrinterModel(
    key="prusa.xl",
    label="Prusa XL (5-tool)",
    adapter=XLAdapter,
    templates="prusa_xl",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.prusa.xl.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass", "stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Prusa XL (5-tool)",
            "bed_mm": list(facts.XL["bed_mm"].value),
            "max_print_height_mm": facts.XL["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            "ifs_slots": 1,
        },
    },
)
