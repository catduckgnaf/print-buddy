"""Bambu Lab H2C (inherits bambulab VENDOR). The H2C is a dual-nozzle H-series model: a 330 x 320 mm bed and
325 mm height, a 350 C hotend, and no bed exclusion. It exists only in OrcaSlicer v2.5.0-alpha's BBL
profiles, which is the release Print Handy ships since #356. Its two extruders are described by facts
("extruders": 2); print starts resolve AMS trays per filament slot through ams_mapping.py, like the
H2D (#308). One recorded state loadout, like every Bambu model here.

Sourced values: facts.py (H2C); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_h2c (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class H2CAdapter(BambuAdapter):
    facts = facts.H2C


MODEL = PrinterModel(
    key="bambulab.h2c",
    label="Bambu Lab H2C",
    adapter=H2CAdapter,
    templates="bambulab_h2c",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.h2c.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab H2C",
            "bed_mm": list(facts.H2C["bed_mm"].value),
            "max_print_height_mm": facts.H2C["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
