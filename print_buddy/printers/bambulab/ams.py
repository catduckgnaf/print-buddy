"""Bambu Lab AMS state decoding from a status push (#307; Stage 2a of #298).

Read-only: this module only decodes the `ams` / `vt_tray` blocks a status snapshot
already carries. It sends nothing — there is no command path here — and the print-start
payload and every gate are untouched by it.

Protocol facts (docs/BAMBU-CONNECTIVITY.md; pybambu at the pinned commit cited there;
the #298 Stage 0 audit, rows 3–5):

- The `ams` block lists units (`ams.ams[]`), each with up to four trays. A tray carries
  `tray_type` (material), `tray_sub_brands` / `tray_id_name` (its label), `tray_color`
  (RRGGBBAA hex) and `remain` (percent remaining; -1 = unknown).
- Slot presence comes from `tray_exist_bits`, a hex bitmask over global tray ids
  (`ams_id*4 + slot`), NEVER from the tray `state` field — its codes are
  firmware-variant. Only when the bits are absent does presence fall back to filament
  metadata (a material type or profile id reported for the tray), the fallback pybambu
  records for firmware without a reliable presence signal. Single-tray AMS HT units
  (ids 128–135) always use the metadata fallback: no source records a bits layout
  for their trays.
- Humidity: only `humidity_raw` is a percentage. The plain `humidity` field is a 1–5
  index running the opposite direction and is never used, not even as a fallback.
- `tray_now` (inside the `ams` block) names the active tray: a global tray id,
  254 = external spool, 255 = nothing active; an AMS HT unit reports its own unit id
  (128–135, its only tray). The newer dual-nozzle `device.extruder.info[].snow`
  encoding is not decoded here — Print Buddy's Bambu models are single-nozzle, and
  per-extruder routing belongs to the mapping work (#308).
- Filament Backup (the printer's AMS auto-switch) is bit 18 of the print payload's
  `cfg` hex string — the mapping OrcaSlicer's DeviceManager records. Absent or
  malformed `cfg` (old-protocol A1-family printers send none) means unknown,
  never assumed off.
- A unit's kind comes from the get_version module list in the same snapshot
  (`ams/` = AMS, `ams_f1/` = AMS Lite, `n3f/` = AMS 2 Pro, `n3s/` = AMS HT): what the
  printer itself reports, never the configured model's name — an A1 can carry a
  regular AMS. Without version info in the snapshot the kind is None, not a guess.
"""

# get_version module-name prefix -> (kind, unit-id offset in the ams block). AMS HT
# units are addressed 128–135 in the report; their module names index from 0.
_MODULE_KINDS = (("ams_f1/", "ams_lite", 0), ("ams/", "ams", 0),
                 ("n3f/", "ams_2_pro", 0), ("n3s/", "ams_ht", 128))

_FILAMENT_BACKUP_BIT = 18  # of the print payload's `cfg` hex string

EXTERNAL_TRAY = 254  # `tray_now` value naming the external spool (vt_tray)
_NO_TRAY = 255       # `tray_now` value naming no active tray


def _as_int(value):
    """An int from an int / integral float / decimal string, else None. Bools are not ints here."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if text and (text.isdigit() or (text[0] == "-" and text[1:].isdigit())):
            return int(text)
    return None


def _remaining(value):
    """Percent remaining: the report's -1 sentinel (and anything outside 0–100) is unknown."""
    number = _as_int(value)
    return number if number is not None and 0 <= number <= 100 else None


def _colour(value):
    """RRGGBBAA (or RRGGBB) hex -> upper-case RRGGBB. Empty / all-zero / malformed -> None."""
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    if len(text) == 8:
        text = text[:6]
    if len(text) != 6 or text == "000000" or any(c not in "0123456789ABCDEF" for c in text):
        return None
    return text


def _text(value):
    """A stripped non-empty string, else None."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _metadata_present(tray):
    """Filament metadata says a spool is loaded: a material type or a profile id is reported."""
    return bool(_text(tray.get("tray_type")) and _text(tray.get("tray_type")) != "Empty"
                or _text(tray.get("tray_info_idx")))


def _tray_fields(tray):
    """The fields every tray-shaped report (AMS tray or vt_tray) shares."""
    return {"material": _text(tray.get("tray_type")),
            "name": _text(tray.get("tray_sub_brands")) or _text(tray.get("tray_id_name")) or "",
            "color": _colour(tray.get("tray_color")),
            "remaining_pct": _remaining(tray.get("remain"))}


def _exist_bits(block):
    """`tray_exist_bits` as an int, or None when the report carries no usable bitmask."""
    raw = block.get("tray_exist_bits")
    if isinstance(raw, str) and raw.strip():
        try:
            return int(raw.strip(), 16)
        except ValueError:
            return None
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def _unit_kinds(info):
    """Unit id -> kind, from the get_version module list in the same snapshot (see module docstring)."""
    kinds = {}
    modules = info.get("module") if isinstance(info, dict) else None
    for module in modules or []:
        if not isinstance(module, dict) or not isinstance(module.get("name"), str):
            continue
        for prefix, kind, offset in _MODULE_KINDS:
            if module["name"].startswith(prefix):
                index = _as_int(module["name"][len(prefix):])
                if index is not None and index >= 0:
                    kinds[offset + index] = kind
                break
    return kinds


def _humidity_pct(unit):
    """The unit's humidity percentage: `humidity_raw` only, in range, else None.

    The plain `humidity` field is a 1–5 index (opposite direction) and is deliberately
    never read here — not even when the raw percentage is missing.
    """
    raw = _as_int(unit.get("humidity_raw"))
    return raw if raw is not None and 1 <= raw <= 100 else None


def _temp_c(unit):
    """The unit's reported temperature in °C, sanity-bounded the way pybambu bounds it."""
    value = unit.get("temp")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100:
        return float(value)
    return None


def _filament_backup(print_payload):
    """Filament Backup (AMS auto-switch) from bit 18 of the payload's `cfg` hex string.

    True / False when the printer reports the bit; None when `cfg` is absent or
    malformed — old-protocol A1-family printers send no `cfg`, and unknown must
    never be read as off.
    """
    cfg = print_payload.get("cfg")
    if not isinstance(cfg, str) or not cfg.strip():
        return None
    try:
        value = int(cfg.strip(), 16)
    except ValueError:
        return None
    return bool(value & (1 << _FILAMENT_BACKUP_BIT))


def _active_target(block):
    """What `tray_now` names: ("tray", global id) / ("unit", HT unit id) / ("external",) / None.

    None covers nothing-active (255), a missing value, and values outside the recorded
    encodings — in every such case no tray is marked active.
    """
    now = _as_int((block or {}).get("tray_now"))
    if now is None or now == _NO_TRAY:
        return None
    if now == EXTERNAL_TRAY:
        return ("external",)
    if 128 <= now <= 135:
        return ("unit", now)
    if 0 <= now <= 63:
        return ("tray", now)
    return None


def decode_ams(print_payload, info=None):
    """Decode a print payload's AMS state to the normalised shape, or None when the
    payload carries neither an `ams` block nor a `vt_tray` (the printer reported no
    AMS state at all — distinct from reporting empty trays).

    Shape: {"units": [{"id", "kind", "humidity_pct", "temp_c",
                       "trays": [{"slot", "present", "material", "name", "color",
                                  "remaining_pct", "active"}]}],
            "external": {tray fields + "present", "active"} | None,
            "active_tray": the global tray id `tray_now` named (254 = external spool),
                           or None when it named nothing decodable,
            "filament_backup": True / False / None (unknown)}
    """
    if not isinstance(print_payload, dict):
        return None
    block = print_payload.get("ams")
    block = block if isinstance(block, dict) else None
    vt_tray = print_payload.get("vt_tray")
    vt_tray = vt_tray if isinstance(vt_tray, dict) else None
    if block is None and vt_tray is None:
        return None
    block = block or {}
    kinds = _unit_kinds(info)
    exist_bits = _exist_bits(block)
    target = _active_target(block)

    units = []
    for entry in block.get("ams") or []:
        if not isinstance(entry, dict):
            continue
        unit_id = _as_int(entry.get("id"))
        if unit_id is None or unit_id < 0:
            continue
        single_tray_ht = 128 <= unit_id <= 135
        trays = []
        for tray in entry.get("tray") or []:
            if not isinstance(tray, dict):
                continue
            slot = _as_int(tray.get("id"))
            if slot is None or slot < 0:
                continue
            if single_tray_ht:
                present = _metadata_present(tray)  # no recorded bits layout for HT trays
                active = target == ("unit", unit_id)
            else:
                global_id = unit_id * 4 + slot
                present = (bool((exist_bits >> global_id) & 1) if exist_bits is not None
                           else _metadata_present(tray))
                active = target == ("tray", global_id)
            trays.append({"slot": slot, "present": present, **_tray_fields(tray), "active": active})
        units.append({"id": unit_id, "kind": kinds.get(unit_id),
                      "humidity_pct": _humidity_pct(entry), "temp_c": _temp_c(entry),
                      "trays": trays})

    external = None
    if vt_tray is not None:
        external = {"present": _metadata_present(vt_tray), **_tray_fields(vt_tray),
                    "active": target == ("external",)}

    if target is None:
        active_tray = None
    elif target[0] == "external":
        active_tray = EXTERNAL_TRAY
    else:
        active_tray = target[1]
    return {"units": units, "external": external, "active_tray": active_tray,
            "filament_backup": _filament_backup(print_payload)}
