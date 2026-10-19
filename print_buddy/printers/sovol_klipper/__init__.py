"""Sovol SV06 profile on top of generic_klipper: its own Orca templates (bed, height, names)."""
from ..generic_klipper import GenericKlipperAdapter


class SovolKlipperAdapter(GenericKlipperAdapter):
    family = "sovol_klipper"
    label = "Sovol SV06 (Klipper)"
