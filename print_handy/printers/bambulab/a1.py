"""Bambu Lab A1 (inherits bambulab VENDOR). Offline slicing, fit checks and G-code validation, plus
the vendor's opt-in read-only LAN status; no upload or print control.

Quirks: the vendor start/end G-code parks the head off the bed on the wiper (X-48.2) and purge lane, so only
the toolpath is held to the 256 mm bed; the vendor blocks are matched line by line against the pinned
templates instead. The AMS Lite is not driven: single filament only. Output from either verified slicer —
OrcaSlicer, or Bambu Studio identified by its header block (#434) — passes the same guard checks. Sourced
values: facts.py; docs/BAMBU-LAB.md. Templates: generated on the operator's machine from their own
OrcaSlicer into <state>/orca-profiles/bambulab_a1 (profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import BambuAdapter


class A1Adapter(BambuAdapter):
    facts = facts.A1


MODEL = PrinterModel(
    key="bambulab.a1",
    label="Bambu Lab A1",
    adapter=A1Adapter,
    templates="bambulab_a1",
    generated_templates=True,
    vendor=VENDOR,
    color_system="multi_slot",
    # Proposed in config/protected-settings-baseline.bambulab.a1.proposed.json; not approved by this change.
    baseline="protected-settings-baseline.bambulab.a1.json",
    # Only the 0.4 mm vendor profile is templated; 0.2, 0.6 and 0.8 mm hotends exist but are refused here.
    supported_nozzle_sizes=(0.4,),
    # Stock stainless steel, or the hardened steel hotend Bambu requires for CF/GF and glow filaments.
    supported_nozzle_types=("stainless_steel", "hardened_steel"),
    settings={
        "printer": {
            "name": "Bambu Lab A1",
            "bed_mm": list(facts.A1["bed_mm"].value),
            "max_print_height_mm": facts.A1["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "stainless_steel",
            # Filament slots: the AMS unit's trays from the facts ("ams":
            # (unit, slots)); the AMS is this model's slot system (#671).
            "filament_slots": facts.A1["ams"].value[1],
        },
    },
)
