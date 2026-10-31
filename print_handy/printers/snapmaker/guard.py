"""Offline checks that keep foreign start code and over-limit temperatures off a U1.

The U1's own start sequence is not known here, so the guard only refuses
markers that belong to other ecosystems and temperatures above the published
limits. It does not claim the remaining file is a valid U1 start.
"""
from __future__ import annotations

import re

from .. import job_checks

FOREIGN_MARKERS = ("START_PRINT", "CHANGE_ZCOLOR", "LOAD_ZOFFSET", "BED_MESH_CALIBRATE",
                   "BED_MESH_PROFILE", "SAVE_VARIABLE", "project_file")


def _numbers(text, command):
    return [float(v) for v in re.findall(rf"^[ \t]*{command}\b[^;\n]*?\bS(-?\d+(?:\.\d+)?)", text, re.M)]


def gcode_problems(text, adapter, state=None):
    fact = adapter.fact
    name = adapter.label
    problems = []
    for marker in FOREIGN_MARKERS:
        if re.search(rf"^[ \t]*{marker}\b", text, re.M):
            problems.append(f"{marker} is another printer ecosystem's start code; it is never sent to a {name}")
    hotend_max, bed_max = fact("max_hotend_c"), fact("max_bed_c")
    for command, limit in (("M104", hotend_max), ("M109", hotend_max), ("M140", bed_max), ("M190", bed_max)):
        over = [v for v in _numbers(text, command) if v > limit]
        if over:
            problems.append(f"{command} S{max(over):g} exceeds the {name} limit of {limit} C")
    # The loaded material, installed nozzle and heater targets (job_checks, shared with the other guards).
    problems += job_checks.recorded_job_problems(text, adapter, state)
    return problems
