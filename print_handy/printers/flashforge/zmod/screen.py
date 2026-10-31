"""ZMod screen sync: the CHANGE_ZCOLOR command that tells the AD5X screen what is loaded in a slot."""
import re

SLOTS = (1, 2, 3, 4)
SCREEN_TYPES = ("PLA", "ABS", "PETG", "TPU", "PLA-CF", "PETG-CF", "SILK")


def screen_type(material):
    """Spoolman material -> one of the seven types the AD5X screen accepts.

    PLA+ / PLA Pro / PLA Matte -> PLA. Unknown materials (ASA, PC, ...) return
    None so the screen material is left alone rather than lied to.
    """
    m = re.sub(r"[\s_]+", "", str(material or "").upper())
    if m in SCREEN_TYPES:
        return m
    if "SILK" in m:
        return "SILK"
    cf = "CF" in m
    for base in ("PETG", "PLA", "ABS", "TPU"):
        if m.startswith(base):
            if cf and base in ("PLA", "PETG"):
                return f"{base}-CF"
            return base
    return None


def label_matches(label, material):
    """True when a slot's screen label agrees with the Spoolman material loaded there.

    The screen has seven types, so CHANGE_ZCOLOR writes "SILK" for Silk PLA and the
    printer reports it back that way. A label matches when it is the same family
    (PLA == PLA+) or is exactly the screen type Print Handy would write for the
    material (SILK for Silk PLA). It never widens the family check otherwise.
    """
    from ....core.printer_state import same_material
    if same_material(label, material):
        return True
    native = re.sub(r"[\s_]+", "", str(label or "").upper())
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
