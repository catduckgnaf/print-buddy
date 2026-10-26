"""Bambu Lab X1E (inherits bambulab VENDOR). The X1E is the enterprise X1 variant (Ethernet, actively heated chamber): same printable geometry and X1C process/filament profiles, its own machine profile and identity. Chamber heating is not driven; its AMS is not driven; jobs are single-color.

Sourced values: facts.py (X1E); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_x1e (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class X1EAdapter(BambuAdapter):
    facts = facts.X1E


MODEL = PrinterModel(
    key="bambulab.x1e",
    label="Bambu Lab X1E",
    adapter=X1EAdapter,
    templates="bambulab_x1e",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.x1e.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab X1E",
            "bed_mm": list(facts.X1E["bed_mm"].value),
            "max_print_height_mm": facts.X1E["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
