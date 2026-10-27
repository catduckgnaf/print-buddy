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


def screen_command(slot, material, hex_code):
    from ....hermes.spool_sync import SpoolError, screen_hex
    stype = screen_type(material)
    hx = screen_hex(hex_code)
    if slot not in SLOTS:
        raise SpoolError(f"slot {slot!r} is not 1-4")
    if stype is None:
        raise SpoolError(f"the printer screen has no type for {material!r}; screen left unchanged")
    if hx is None:
        raise SpoolError(f"spool color {hex_code!r} is not a 6-digit hex; screen left unchanged")
    return f"CHANGE_ZCOLOR SLOT={slot} TYPE={stype} HEX={hx}"
