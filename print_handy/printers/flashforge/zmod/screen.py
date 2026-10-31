"""ZMod screen sync: the CHANGE_ZCOLOR command that tells the AD5X screen what is loaded in a slot."""
import re

SLOTS = (1, 2, 3, 4)
SCREEN_TYPES = ("PLA", "ABS", "PETG", "TPU", "PLA-CF", "PETG-CF", "SILK")


def screen_type(material):
    """Spoolman material -> one of the seven types the AD5X screen accepts, or None.

    Derived from the material's family and variants, never from its spelling: PLA+ / PLA Pro /
    PLA Matte / Matte PLA / Wood PLA -> PLA, Silk PLA (bare "Silk" too) -> SILK, Silk PLA-CF ->
    PLA-CF, PET-G -> PETG. The screen's SILK is silk PLA only, so Silk PETG is PETG. Anything the
    screen has no type for (ASA, PC, PA, ABS-CF, ...) returns None, so the screen material is
    left alone rather than lied to.
    """
    from ....core.printer_state import material_family, material_variants
    family = material_family(material)
    if family == "PLA":
        return "SILK" if "SILK PLA" in material_variants(material) else "PLA"
    if family in SCREEN_TYPES and family != "SILK":
        return family
    return None


def label_matches(label, material):
    """True when a slot's screen label agrees with the Spoolman material loaded there.

    The screen has seven types, so CHANGE_ZCOLOR writes "SILK" for Silk PLA and the
    printer reports it back that way. A label matches when it is the same family
    (PLA == PLA+) or is exactly the screen type Print Handy would write for the
    material (SILK for Silk PLA). The SILK label is the exception to the family rule:
    material_family reads a bare "Silk" as PLA, but a slot the screen marks SILK holds
    silk PLA, never a plain PLA spool. It never widens the family check otherwise.
    """
    from ....core.printer_state import same_material
    native = re.sub(r"[\s_]+", "", str(label or "").upper())
    if native == "SILK":
        return screen_type(material) == "SILK"
    if same_material(label, material):
        return True
    return native in SCREEN_TYPES and native == screen_type(material)


def screen_command(slot, material, hex_code):
    from ....hermes.spool_sync import SpoolError, screen_hex
    stype = screen_type(material)
    hx = screen_hex(hex_code)
    if slot not in SLOTS:
        raise SpoolError(f"slot {slot!r} is not 1-4")
    if stype is None:
        raise SpoolError(f"the printer screen has no type for {material!r}; screen left unchanged")
    if hx is None:
        raise SpoolError(f"spool color {hex_code!r} is not a hex color; screen left unchanged")
    return f"CHANGE_ZCOLOR SLOT={slot} TYPE={stype} HEX={hx}"
