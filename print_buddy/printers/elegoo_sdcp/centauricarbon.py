"""Elegoo Centauri Carbon (inherits elegoo_sdcp VENDOR): enclosed CoreXY on SDCP, 256 mm cube.

Sourced values: facts.py (CENTAURI_CARBON); docs/ELEGOO.md. Templates: generated on the
operator's machine from their own OrcaSlicer into <state>/orca-profiles/elegoo_centauri_carbon
(profiles.py); none are shipped.
"""
from ..base import PrinterModel
from . import VENDOR, facts
from .adapter import ElegooSdcpAdapter


class CentauriCarbonAdapter(ElegooSdcpAdapter):
    facts = facts.CENTAURI_CARBON


MODEL = PrinterModel(
    key="elegoo_sdcp.centauricarbon",
    label="Elegoo Centauri Carbon",
    adapter=CentauriCarbonAdapter,
    templates="elegoo_centauri_carbon",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.elegoo_sdcp.centauricarbon.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("hardened_steel", "stainless_steel"),
    settings={
        "printer": {
            "name": "Elegoo Centauri Carbon",
            "bed_mm": list(facts.CENTAURI_CARBON["bed_mm"].value),
            "max_print_height_mm": facts.CENTAURI_CARBON["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "hardened_steel",
            "ifs_slots": 1,
        },
    },
)
