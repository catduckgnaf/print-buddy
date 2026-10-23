"""Offline checks that keep Klipper/ZMod start code and unsupported jobs away from Bambu hardware.

Pure text checks: no printer, slicer or network. Used when templates are assembled, after slicing, and again
before the operator is handed a file.
"""
from __future__ import annotations

import math
import re

from .capabilities import A1

# Klipper extended commands (START_PRINT, PRINT_END, BED_MESH_PROFILE, SET_PRINT_STATS_INFO, CHANGE_ZCOLOR,
# SAVE_VARIABLE, LOAD_ZOFFSET, ...) are UPPER_SNAKE words. Bambu G-code lines start with G, M or T codes.
KLIPPER_COMMAND = re.compile(r"^[ \t]*([A-Z][A-Z0-9]*_[A-Z0-9_]+)\b", re.M)
# ZMod/AD5X markers that are not commands: START_PRINT's MESH= argument, zmod_color data, the ZMod MD5 line.
ZMOD_MARKER = re.compile(r"\bMESH=|zmod|^; MD5:", re.M | re.I)
VENDOR_START = ";===== machine: A1 "
START_END_TAG = "; MACHINE_START_GCODE_END"
END_START_TAG = "; MACHINE_END_GCODE_START"


class ForeignStartCode(RuntimeError):
    """G-code meant for a Klipper/ZMod printer was about to reach a Bambu Lab printer."""


def foreign_commands(text):
    """Klipper/ZMod commands and markers in text, in order, without repeats."""
    found = [m.group(1) for m in KLIPPER_COMMAND.finditer(text or "")]
    found += [m.group(0).strip() for m in ZMOD_MARKER.finditer(text or "")]
    return list(dict.fromkeys(found))


def require_bambu_code(text, what):
    """Raise ForeignStartCode when text holds any Klipper/ZMod command; return text unchanged."""
    bad = foreign_commands(text)
    if bad:
        raise ForeignStartCode(f"{what} contains Klipper/ZMod code ({', '.join(bad[:5])}); "
                               "it is never sent to a Bambu Lab printer")
    return text


def _config(text, key):
    match = re.search(rf"^; {re.escape(key)} = (.*)$", text, re.M)
    return match.group(1).strip() if match else None


def _numbers(text, command):
    return [float(v) for v in re.findall(rf"^[ \t]*{command}\b[^;\n]*?\bS(-?\d+(?:\.\d+)?)", text, re.M)]


def a1_gcode_problems(text, *, state=None, nozzle_sizes=(0.4,), nozzle_types=("stainless_steel", "hardened_steel")):
    """Reasons this sliced G-code must not be handed to an A1; empty when it passes.

    state, when given, is the printer hardware record: its nozzle, spool material and temperatures must match.
    """
    from ...core import slice_guard
    from ...core.nozzle import NozzleError, effective_nozzle_temperature, is_abrasive_material, normalize_nozzle_type
    from ...core.printer_state import material_family, same_material

    text = text or ""
    problems = []
    bad = foreign_commands(text)
    if bad:
        problems.append(f"G-code contains Klipper/ZMod code ({', '.join(bad[:5])}); never sent to a Bambu Lab printer")
    model = _config(text, "printer_model")
    if model != "Bambu Lab A1":
        problems.append(f"G-code was sliced for printer_model {model!r}, not 'Bambu Lab A1'")
    if VENDOR_START not in text:
        problems.append("G-code does not start with the Bambu Lab A1 vendor start sequence")
    if START_END_TAG not in text or END_START_TAG not in text:
        problems.append("G-code has no OrcaSlicer machine start/end markers; toolpath bounds cannot be checked")
    else:
        body = text.split(START_END_TAG, 1)[1].split(END_START_TAG, 1)[0]
        tools = sorted({int(n) for n in re.findall(r"^[ \t]*T(\d+)\b", body, re.M)} - {0})
        if tools:
            problems.append(f"G-code changes to tools {tools}; AMS Lite multi-color is not supported")
        bed, height = A1["bed_mm"].value, A1["max_print_height_mm"].value
        problems += slice_guard.body_motion_problems(body, bed, A1["motion_envelope_mm"].value, height)
    for command, limit in (("M104", A1["max_hotend_c"].value), ("M109", A1["max_hotend_c"].value),
                           ("M140", A1["max_bed_c"].value), ("M190", A1["max_bed_c"].value)):
        over = [v for v in _numbers(text, command) if v > limit]
        if over:
            problems.append(f"{command} S{max(over):g} exceeds the A1 limit of {limit} C")
    nozzle = _config(text, "nozzle_diameter")
    try:
        nozzle_mm = float(nozzle)
    except (TypeError, ValueError):
        problems.append(f"invalid embedded nozzle_diameter {nozzle!r}")
        nozzle_mm = None
    if nozzle_mm is not None and not any(math.isclose(nozzle_mm, s, abs_tol=1e-3) for s in nozzle_sizes):
        problems.append(f"nozzle {nozzle_mm:g} mm has no A1 template here (supported: "
                        f"{', '.join(f'{s:g}' for s in nozzle_sizes)})")
    try:
        nozzle_type = normalize_nozzle_type(_config(text, "nozzle_type") or "")
    except NozzleError:
        problems.append(f"invalid embedded nozzle_type {_config(text, 'nozzle_type')!r}")
        nozzle_type = None
    if nozzle_type is not None and nozzle_type not in nozzle_types:
        problems.append(f"nozzle type {nozzle_type} is not an A1 hotend option ({', '.join(nozzle_types)})")
    material = _config(text, "filament_type")
    if not material or ";" in material:
        problems.append(f"G-code must name exactly one filament_type, got {material!r}")
    else:
        family = material_family(material)
        if family.split("-", 1)[0] in A1["not_recommended_materials"].value:
            problems.append(f"{material} is not recommended by Bambu Lab for the open-frame A1; refused")
        if is_abrasive_material(material) and nozzle_type != "hardened_steel":
            problems.append(f"{material} is abrasive; the A1 needs a hardened steel nozzle for it")
    if state:
        if nozzle_mm is not None and abs(nozzle_mm - float(state["nozzle"]["diameter_mm"])) > 1e-3:
            problems.append(f"G-code nozzle {nozzle_mm:g} != recorded {state['nozzle']['diameter_mm']}")
        if material and not same_material(material, state["spool"]["material"]):
            problems.append(f"G-code filament_type {material!r} != loaded {state['spool']['material']!r}")
        hotend = effective_nozzle_temperature(nozzle_type or "stainless_steel", float(state["temps_c"]["nozzle"]))
        bed_c = float(state["temps_c"]["bed"])
        if not any(math.isclose(v, bed_c, abs_tol=1e-3) for v in _numbers(text, "M140") + _numbers(text, "M190")):
            problems.append(f"no M140/M190 sets the recorded bed temperature {bed_c:g} C")
        if not any(math.isclose(v, hotend, abs_tol=1e-3) for v in _numbers(text, "M104") + _numbers(text, "M109")):
            problems.append(f"no M104/M109 sets the effective nozzle temperature {hotend:g} C")
    return problems
