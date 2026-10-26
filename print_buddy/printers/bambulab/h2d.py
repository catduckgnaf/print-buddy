"""Bambu Lab H2D (inherits bambulab VENDOR). The H2D is the dual-nozzle flagship: a 350 x 320 mm bed (305 mm wide for a single tool, 350 mm across both) and 325 mm height, a 350 C hotend, and no bed exclusion. Its two extruders are described by facts ("extruders": 2); print starts resolve AMS trays per filament slot through ams_mapping.py (#308). One recorded state loadout, like every Bambu model here.

Sourced values: facts.py (H2D); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_h2d (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class H2DAdapter(BambuAdapter):
    facts = facts.H2D


MODEL = PrinterModel(
    key="bambulab.h2d",
    label="Bambu Lab H2D",
    adapter=H2DAdapter,
    templates="bambulab_h2d",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.h2d.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab H2D",
            "bed_mm": list(facts.H2D["bed_mm"].value),
            "max_print_height_mm": facts.H2D["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
