"""Bambu Lab H2D Pro (inherits bambulab VENDOR). The H2D's pro variant: same dual-nozzle toolhead, 350 x 320 mm bed and 325 mm height as the H2D, with its own Orca profiles and identity (#308).

Sourced values: facts.py (H2DPRO); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_h2dpro (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class H2DProAdapter(BambuAdapter):
    facts = facts.H2DPRO


MODEL = PrinterModel(
    key="bambulab.h2dpro",
    label="Bambu Lab H2D Pro",
    adapter=H2DProAdapter,
    templates="bambulab_h2dpro",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.h2dpro.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab H2D Pro",
            "bed_mm": list(facts.H2DPRO["bed_mm"].value),
            "max_print_height_mm": facts.H2DPRO["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
