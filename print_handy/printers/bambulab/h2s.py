"""Bambu Lab H2S (inherits bambulab VENDOR). The H2S is the single-nozzle H2 model: a 340 x 320 mm bed and 340 mm height, a 350 C hotend, and no bed exclusion. (The dual-nozzle H2D is registered separately, #308; H2C has no profile in the pinned OrcaSlicer.) Its AMS 2 Pro / AMS HT are not driven; jobs are single-color.

Sourced values: facts.py (H2S); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_h2s (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class H2SAdapter(BambuAdapter):
    facts = facts.H2S


MODEL = PrinterModel(
    key="bambulab.h2s",
    label="Bambu Lab H2S",
    adapter=H2SAdapter,
    templates="bambulab_h2s",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.h2s.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab H2S",
            "bed_mm": list(facts.H2S["bed_mm"].value),
            "max_print_height_mm": facts.H2S["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
