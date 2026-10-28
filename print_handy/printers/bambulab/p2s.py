"""Bambu Lab P2S (inherits bambulab VENDOR). The P2S succeeds the P1S: a 256 mm bed with the full 256 mm Orca height and no bed exclusion. It pairs with an AMS 2 Pro, which Print Handy does not drive beyond a single path; jobs are single-color.

Sourced values: facts.py (P2S); docs/BAMBU-LAB.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/bambulab_p2s (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class P2SAdapter(BambuAdapter):
    facts = facts.P2S


MODEL = PrinterModel(
    key="bambulab.p2s",
    label="Bambu Lab P2S",
    adapter=P2SAdapter,
    templates="bambulab_p2s",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.bambulab.p2s.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab P2S",
            "bed_mm": list(facts.P2S["bed_mm"].value),
            "max_print_height_mm": facts.P2S["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
