"""Bambu Lab X2D (inherits bambulab VENDOR). The dual-nozzle X-series model: a 256 x 256 mm bed and 261 mm height, a 320 C hotend, and no bed exclusion. Its two extruders are described by facts ("extruders": 2); print starts resolve AMS trays per filament slot through ams_mapping.py (#308).

Color architecture (#671): classified "single" deliberately. Two independent extruders, each fed by its own AMS, are neither the one-extruder multi_slot shape nor the multi_tool tool-changer contract (identity tool mapping, tool-shaped intake), so neither class is claimed; the slicer assigns filaments to extruders in the file itself, and print starts resolve AMS trays per filament slot (ams_mapping.py), outside the class machinery.

Sourced values: facts.py (X2D); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_x2d (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class X2DAdapter(BambuAdapter):
    facts = facts.X2D


MODEL = PrinterModel(
    key="bambulab.x2d",
    label="Bambu Lab X2D",
    adapter=X2DAdapter,
    templates="bambulab_x2d",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.x2d.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab X2D",
            "bed_mm": list(facts.X2D["bed_mm"].value),
            "max_print_height_mm": facts.X2D["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "filament_slots": 1,
        },
    },
)
