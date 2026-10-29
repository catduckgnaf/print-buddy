"""Filament color codes: derive them, resolve them, never leave a slot without one.

A spool's color code (six-digit RGB hex) only drives the slicer preview
color, the 3MF filament color labels and the printer screen swatch; it
never changes a toolpath. Before this module a spool created from a color
*name* ("matte white", "rose red blue green") could be saved with no hex at
all, and slicing then died on ``filament color must be an explicit
six-digit RGB value`` with an unexplained ``PB_SLICING_UNKNOWN``.

This is the one place that knows how to get a color code:

* :func:`derive` reads a color name (and its finish words) against a
  named-color table — "matte white" is white, "rose red blue green" is a
  multi-color spool whose representative swatch is its first color;
* :func:`resolve` applies the fallback order every reader uses: the slot
  record's own hex, then Spoolman's ``color_hex``, then the hex the printer
  reports for the slot (ZMod ``zmod_color``), then the name, and only then
  :data:`NEUTRAL_DEFAULT` — which callers must say out loud;
* :func:`fill_missing_slot_hexes` backfills hardware-record slots that have
  no valid hex. It never overwrites a valid hex the operator or Spoolman
  supplied; a hex this module derived itself (``hex_source`` ``name`` or
  ``default``) may be upgraded when a better source answers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

#: Neutral mid-gray used only when no color can be determined. Every
#: record that carries it also carries ``hex_source: "default"`` so chat
#: can say so.
NEUTRAL_DEFAULT = "9E9E9E"

#: Where a slot's color code came from, best first.
SOURCES = ("slot", "spoolman", "printer", "name", "default")

#: Sources this module guessed itself; a better source may replace them.
DERIVED_SOURCES = frozenset({"name", "default"})

# Two-word colors are matched before single words, so "rose red" is one
# color rather than "rose" + "red". Values are representative swatches,
# not manufacturer-exact: they only color previews and labels.
_COMPOUND = {
    "rose red": "C2185B", "rose gold": "B76E79", "sky blue": "64B5F6", "baby blue": "90CAF9",
    "light blue": "81D4FA", "dark blue": "0D47A1", "navy blue": "1A237E", "royal blue": "2E4BC6",
    "ice blue": "B3E5FC", "light green": "8BC34A", "dark green": "1B5E20", "forest green": "2E7D32",
    "army green": "4B5320", "olive green": "6B8E23", "grass green": "4CAF50", "mint green": "98D8C8",
    "light grey": "BDBDBD", "light gray": "BDBDBD", "dark grey": "424242", "dark gray": "424242",
    "space grey": "5F6368", "space gray": "5F6368", "jet black": "0A0A0A", "bone white": "EDE6D6",
    "ivory white": "FFFFF0", "cool white": "F5F7FA", "warm white": "FAF3E3", "hot pink": "FF4081",
    "light pink": "F8BBD0", "dark red": "8B0000", "fire red": "E53935", "bright red": "E53935",
    "lemon yellow": "FFF44F", "sunflower yellow": "FFC107", "dark purple": "4A148C",
    "light purple": "CE93D8", "olive drab": "6B8E23", "sand brown": "C2B280",
}

_SINGLE = {
    "black": "161616", "white": "FFFFFF", "grey": "8E8E8E", "gray": "8E8E8E", "silver": "C0C0C0",
    "red": "D32F2F", "crimson": "B71C1C", "scarlet": "E53935", "burgundy": "800020", "maroon": "800000",
    "rose": "E91E63", "pink": "F48FB1", "magenta": "D81B60", "fuchsia": "D81B60",
    "orange": "F57C00", "coral": "FF7F50", "peach": "FFCBA4", "yellow": "FBC02D", "gold": "D4AF37",
    "golden": "D4AF37", "bronze": "CD7F32", "copper": "B87333", "brass": "B5A642",
    "green": "388E3C", "lime": "9CCC65", "olive": "808000", "mint": "98D8C8", "teal": "00897B",
    "turquoise": "40E0D0", "cyan": "00BCD4", "aqua": "00BCD4", "blue": "1E88E5", "navy": "1A237E",
    "cobalt": "0047AB", "purple": "7B1FA2", "violet": "8E24AA", "lavender": "B39DDB", "lilac": "C8A2C8",
    "indigo": "3F51B5", "brown": "6D4C41", "chocolate": "5D4037", "coffee": "6F4E37", "tan": "D2B48C",
    "beige": "E8D8B8", "cream": "FFFDD0", "ivory": "FFFFF0", "khaki": "C3B091", "sand": "C2B280",
    "natural": "F3E9D2", "clear": "F2F2F2", "transparent": "F2F2F2", "translucent": "F2F2F2",
    "wood": "A47551", "charcoal": "36454F", "graphite": "41424C", "slate": "708090", "titanium": "878681",
    "skin": "F1C27D",
}

#: Multi-color words that name a whole palette.
_PALETTES = {
    "rainbow": ("D32F2F", "F57C00", "FBC02D", "388E3C", "1E88E5", "7B1FA2"),
}

#: Finish and material words: they describe the spool, not its color. The
#: British "colour" and "multicolour" stay listed because operators type them.
_IGNORED = frozenset({
    "matte", "matt", "silk", "glossy", "gloss", "satin", "metallic", "shiny", "sparkle", "glitter",
    "marble", "galaxy", "pearl", "neon", "pastel", "dual", "tri", "triple", "multi", "multicolor",
    "multicolour", "color", "colour", "coextrusion", "gradient", "pla", "petg", "abs", "asa", "tpu",
    "pa", "pc", "nylon", "plus", "pro", "hs", "hyper", "high", "speed", "basic", "and", "with", "the",
})


@dataclass(frozen=True)
class Guess:
    """A color read from a name: one representative swatch, plus the rest
    when the name lists several colors (a multi-color / silk blend)."""
    hex: str
    multi_hexes: tuple[str, ...] = field(default_factory=tuple)
    words: tuple[str, ...] = field(default_factory=tuple)

    @property
    def multi(self) -> bool:
        return len(self.multi_hexes) > 1


def normalize_hex(value: Any) -> str | None:
    """``RRGGBB`` upper-case for a single six-digit hex (``#`` optional), else None.

    A comma list (Spoolman ``multi_color_hexes``) is not one color and
    returns None; use :func:`first_hex` to take its representative.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#").upper()
    return text if re.fullmatch(r"[0-9A-F]{6}", text) else None


def first_hex(value: Any) -> str | None:
    """The first valid hex of a single value or a comma-separated list."""
    if not isinstance(value, str):
        return None
    for part in value.split(","):
        hx = normalize_hex(part)
        if hx:
            return hx
    return None


def derive(name: Any, material: Any = None) -> Guess | None:
    """Read a color name. None when no color word is recognized.

    The material is stripped first ("Pink PLA" + PLA -> pink). Finish words
    (matte, silk, glossy, ...) are ignored. Two-word colors win over their
    parts, and several colors in one name make a multi-color guess whose
    representative is the first color named.
    """
    text = str(name or "").casefold()
    if material:
        text = re.sub(rf"(?<![a-z]){re.escape(str(material).casefold())}(?![a-z])", " ", text)
    words = [w for w in re.split(r"[^a-z]+", text) if w and w not in _IGNORED]
    found: list[tuple[str, str]] = []
    i = 0
    while i < len(words):
        pair = " ".join(words[i:i + 2])
        if len(words) - i >= 2 and pair in _COMPOUND:
            found.append((pair, _COMPOUND[pair]))
            i += 2
            continue
        word = words[i]
        if word in _PALETTES:
            found.extend((word, hx) for hx in _PALETTES[word])
        elif word in _SINGLE:
            found.append((word, _SINGLE[word]))
        i += 1
    if not found:
        return None
    hexes: list[str] = []
    for _, hx in found:
        if hx not in hexes:
            hexes.append(hx)
    return Guess(hex=hexes[0], multi_hexes=tuple(hexes) if len(hexes) > 1 else (),
                 words=tuple(word for word, _ in found))


def derive_hex(name: Any, material: Any = None) -> str | None:
    guess = derive(name, material)
    return guess.hex if guess else None


def resolve(record: Mapping[str, Any] | None = None, *, spoolman_hex: Any = None,
            printer_hex: Any = None, name: Any = None, material: Any = None) -> tuple[str, str]:
    """The color code for one slot and where it came from. Never fails.

    Order: the record's own hex, Spoolman's ``color_hex`` (or the first of
    its ``multi_color_hexes``), the printer's reported slot hex, the color
    name, then :data:`NEUTRAL_DEFAULT` with source ``"default"``.
    """
    record = record or {}
    own = normalize_hex(record.get("hex"))
    if own:
        return own, "slot"
    spoolman = first_hex(spoolman_hex) if isinstance(spoolman_hex, str) else None
    if spoolman:
        return spoolman, "spoolman"
    printer = normalize_hex(printer_hex)
    if printer:
        return printer, "printer"
    material = material if material is not None else record.get("material")
    for candidate in (name, record.get("color"), record.get("name")):
        guess = derive(candidate, material)
        if guess:
            return guess.hex, "name"
    return NEUTRAL_DEFAULT, "default"


def printer_slot_hexes(zmod_color: Any) -> dict[str, str]:
    """``{slot: hex}`` from a Moonraker ``zmod_color`` status (1-based ``ID``/``HEX``)."""
    slots = (zmod_color or {}).get("slots") if isinstance(zmod_color, dict) else None
    out: dict[str, str] = {}
    for item in slots or []:
        if not isinstance(item, dict):
            continue
        hx = normalize_hex(item.get("HEX"))
        if hx and str(item.get("ID", "")).isdigit():
            out[str(item["ID"])] = hx
    return out


def fill_missing_slot_hexes(state: dict[str, Any], *,
                            spoolman_hexes: Mapping[Any, Any] | None = None,
                            printer_hexes: Mapping[Any, Any] | None = None) -> list[dict[str, Any]]:
    """Give every loaded IFS slot record a color code. Mutates ``state``.

    Only records with no valid hex are filled, plus records whose hex this
    module derived itself (``hex_source`` ``name``/``default``) when a better
    source (Spoolman or the printer) now answers. A valid hex the operator,
    Spoolman or the printer supplied is never overwritten. ``spoolman_hexes``
    is keyed by Spoolman spool id, ``printer_hexes`` by slot number.

    A record bound through ``/spool`` whose color was unverified only
    because it had no hex (spool identity known, loading confirmed) becomes
    color-verified with the filled code, and ``hex_source`` names where the
    code came from so nothing pretends to be more than it is.

    Returns one change per filled slot: slot, hex, source, previous hex.
    """
    changes: list[dict[str, Any]] = []
    slots = state.get("ifs_slots") if isinstance(state, dict) else None
    if not isinstance(slots, dict):
        return changes
    spoolman_hexes = spoolman_hexes or {}
    printer_hexes = printer_hexes or {}
    for key, record in slots.items():
        if not isinstance(record, dict) or not (record.get("spoolman_id") or record.get("color")
                                                or record.get("name")):
            continue
        own = normalize_hex(record.get("hex"))
        if own and _bound_by_operator(record) and not record.get("physical_color_verified"):
            # A slot bound through /spool or the IFS insertion prompt: the
            # operator picked this spool for this slot by name, which is the
            # confirmation. It was left unverified only for its color code
            # (none, or multi-color), and it has one now.
            record["physical_color_verified"] = True
            changes.append({"slot": str(key), "hex": own, "source": record.get("hex_source") or "slot",
                            "previous": own, "verified": True})
        derived_before = own is not None and record.get("hex_source") in DERIVED_SOURCES
        if own and not derived_before:
            continue
        sid = record.get("spoolman_id")
        spoolman_hex = spoolman_hexes.get(sid) if sid is not None else None
        if spoolman_hex is None and sid is not None:
            spoolman_hex = spoolman_hexes.get(str(sid))
        printer_hex = printer_hexes.get(str(key))
        if printer_hex is None:
            printer_hex = printer_hexes.get(key)
        probe = {k: v for k, v in record.items() if k != "hex"}
        hx, source = resolve(probe, spoolman_hex=spoolman_hex, printer_hex=printer_hex)
        if derived_before:
            # Upgrade our own guess only to a better, authoritative source.
            if source not in ("spoolman", "printer") or hx == own:
                continue
        previous = record.get("hex")
        unverified_for_lack_of_hex = not own and _bound_by_operator(record)             and not record.get("physical_color_verified")
        record["hex"] = hx
        record["hex_source"] = source
        if unverified_for_lack_of_hex:
            record["physical_color_verified"] = True
        changes.append({"slot": str(key), "hex": hx, "source": source, "previous": previous})
    return changes


def _bound_by_operator(record: Mapping[str, Any]) -> bool:
    """A slot record the operator bound to a spool (its loading confirmed).

    spool_sync's binding (``/spool``, the IFS insertion prompt, the new-spool
    walkthrough) records ``physical_loading_verified`` and the Spoolman id;
    it only ever left color unverified for want of a single color code.
    """
    return (record.get("physical_loading_verified") is True and record.get("spoolman_id") is not None
            and record.get("quantity_status") == "spoolman")


def slot_label(slot: Any, record: Mapping[str, Any] | None) -> str:
    """'Slot 2 (Rose red blue green Silk PLA)' — the record's own words."""
    record = record or {}
    name = str(record.get("name") or "").strip()
    if not name:
        name = " ".join(x for x in (str(record.get("color") or "").strip(),
                                    str(record.get("material") or "").strip()) if x)
    name = name[:1].upper() + name[1:] if name else ""
    return f"Slot {slot} ({name})" if name else f"Slot {slot}"


def slot_hex(slot: Any, value: Any) -> str:
    """``#RRGGBB`` for one slot row (a record dict or a bare hex). Never raises.

    The last line of defense at the slicer boundary: a row that reaches it
    without a valid hex gets one from its name, else the neutral default,
    and a WARNING line says which. It only colors previews and labels.
    """
    record = value if isinstance(value, Mapping) else {"hex": value}
    hx, source = resolve(record)
    if source == "default":
        print(f"WARNING: {slot_label(slot, record)} has no color code and none could be worked out; "
              f"using neutral #{hx} for the preview only", flush=True)
    elif source == "name":
        print(f"WARNING: {slot_label(slot, record)} has no color code recorded; "
              f"using #{hx} worked out from its name", flush=True)
    return "#" + hx


def chat_notes(state: Mapping[str, Any] | None, slots: Iterable[Any] | None = None) -> list[str]:
    """Plain lines for chat about color codes that are guesses.

    Only a neutral default is worth interrupting for: a name-derived code
    is an honest reading of what the operator typed. ``slots`` limits the
    notes to the slots a job uses.
    """
    records = (state or {}).get("ifs_slots") or {}
    wanted = {str(s) for s in slots} if slots is not None else None
    notes = []
    for key in sorted(records, key=lambda k: str(k)):
        record = records.get(key)
        if not isinstance(record, dict) or (wanted is not None and str(key) not in wanted):
            continue
        if record.get("hex_source") == "default":
            notes.append(f"{slot_label(key, record)} has no color I could work out, so its preview "
                         f"uses neutral gray (#{NEUTRAL_DEFAULT}). The print itself is unaffected; "
                         "set the color with `/spool` to fix the preview.")
    return notes


#: Swatches offered as buttons when a typed color name cannot be read.
SWATCHES = (
    ("Black", "161616"), ("White", "FFFFFF"), ("Gray", "8E8E8E"), ("Silver", "C0C0C0"),
    ("Red", "D32F2F"), ("Orange", "F57C00"), ("Yellow", "FBC02D"), ("Green", "388E3C"),
    ("Blue", "1E88E5"), ("Purple", "7B1FA2"), ("Pink", "F48FB1"), ("Brown", "6D4C41"),
    ("Gold", "D4AF37"), ("Natural / clear", "F3E9D2"),
)
