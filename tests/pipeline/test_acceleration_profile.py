"""Staging-only regression for acceleration remaining under the measured X limit."""
import json
from pathlib import Path
import re


from print_buddy import settings

PROCESS_TEMPLATE = settings.current()["orca"]["templates"] / "process.json"
MEASURED_X_MAX_ACCEL = 4747
CONSERVATIVE_INITIAL_LAYER_ACCEL = 500
PERCENT_BASES = {
    "bridge_acceleration": "outer_wall_acceleration",
    "sparse_infill_acceleration": "default_acceleration",
    "internal_solid_infill_acceleration": "default_acceleration",
    "initial_layer_travel_acceleration": "travel_acceleration",
}


def resolve_acceleration(key, value, process):
    """Resolve Orca percentage accelerations against their documented base."""
    text = str(value).strip()
    if text.endswith("%"):
        percentage = float(text[:-1])
        base_key = PERCENT_BASES.get(key, "default_acceleration")
        base = process[base_key]
        if str(base).strip().endswith("%"):
            raise AssertionError(f"percentage base must be absolute: {base_key}={base}")
        return float(base) * percentage / 100
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        raise AssertionError(f"unrecognized acceleration value: {key}={value!r}")
    return float(text)


def test_every_process_acceleration_is_within_measured_x_shaper_limit():
    process = json.loads(PROCESS_TEMPLATE.read_text())
    acceleration_values = {
        key: resolve_acceleration(key, value, process)
        for key, value in process.items()
        if "acceleration" in key
    }

    assert acceleration_values, "process template has no acceleration settings"
    assert all(
        value <= MEASURED_X_MAX_ACCEL
        for value in acceleration_values.values()
    ), acceleration_values


def test_initial_layer_accelerations_remain_conservative():
    process = json.loads(PROCESS_TEMPLATE.read_text())

    assert float(process["initial_layer_acceleration"]) <= CONSERVATIVE_INITIAL_LAYER_ACCEL
    assert resolve_acceleration(
        "initial_layer_travel_acceleration",
        process["initial_layer_travel_acceleration"],
        process,
    ) <= CONSERVATIVE_INITIAL_LAYER_ACCEL


def test_percentage_acceleration_is_resolved_not_float_parsed():
    process = json.loads(PROCESS_TEMPLATE.read_text())
    assert resolve_acceleration("bridge_acceleration", process["bridge_acceleration"], process) == 1600

