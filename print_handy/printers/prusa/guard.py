"""Offline checks that keep foreign start code and unsupported jobs away from Prusa hardware.

Pure text checks, in the bambulab/guard.py spirit but for Prusa's Marlin-family dialect: the
slicer owns the start/end sequences (from the verified generated templates), so this guard does
not match vendor blocks line by line. It refuses what must never reach a Prusa printer — Klipper
or ZMod macro start code, a file sliced for a different printer model, temperatures above the
model's published limits, and tool changes (Print Handy's Prusa support slices single-tool jobs
only, including on the 5-tool XL).
"""
from __future__ import annotations

import math
import re

# Commands that belong to other vendors' start code. Prusa output is plain G/M/T codes plus
# Prusa's own M8xx extensions; none of these words appear in it.
FOREIGN_MARKERS = ("PRINT_START", "START_PRINT", "CHANGE_ZCOLOR", "LOAD_ZOFFSET", "BED_MESH_CALIBRATE",
                   "BED_MESH_PROFILE", "SAVE_VARIABLE", "project_file")


def _config(text, key):
    match = re.search(rf"^; {re.escape(key)} = (.*)$", text, re.M)
    return match.group(1).strip().strip('"') if match else None


def _numbers(text, command):
    return [float(v) for v in re.findall(rf"^[ \t]*{command}\b[^;\n]*?\bS(-?\d+(?:\.\d+)?)", text, re.M)]


def gcode_problems(text, adapter, state=None):
    fact = adapter.fact
    name = adapter.label
    problems = []
    for marker in FOREIGN_MARKERS:
        if re.search(rf"^[ \t]*{marker}\b", text, re.M):
            problems.append(f"{marker} is another vendor's start code; it is never sent to a {name}")
    model = _config(text, "printer_model")
    if model is not None and model != fact("printer_model"):
        problems.append(f"file was sliced for {model!r}, not the {name} ({fact('printer_model')!r})")
    tools = sorted({int(n) for n in re.findall(r"^[ \t]*T(\d+)\b", text, re.M)} - {0})
    if tools:
        problems.append(f"G-code changes to tools {tools}; {name} jobs are sliced single-tool only")
    hotend_max, bed_max = fact("max_hotend_c"), fact("max_bed_c")
    for command, limit in (("M104", hotend_max), ("M109", hotend_max), ("M140", bed_max), ("M190", bed_max)):
        over = [v for v in _numbers(text, command) if v > limit]
        if over:
            problems.append(f"{command} S{max(over):g} exceeds the {name} limit of {limit} C")
    nozzle = _config(text, "nozzle_diameter")
    if nozzle is not None:
        try:
            nozzle_mm = float(nozzle)
        except ValueError:
            problems.append(f"invalid embedded nozzle_diameter {nozzle!r}")
        else:
            if not any(math.isclose(nozzle_mm, s, abs_tol=1e-3) for s in adapter.supported_nozzle_sizes):
                problems.append(f"nozzle {nozzle_mm:g} mm has no {name} template here (supported: "
                                f"{', '.join(f'{s:g}' for s in adapter.supported_nozzle_sizes)})")
    return problems
