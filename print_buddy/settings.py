"""Printer and layout settings, read from config/home.toml with optional local overrides.

Load order, later wins key by key:
  1. config/home.toml (committed, the home setup; tests use it)
  2. $PRINT_BUDDY_CONFIG if set, otherwise config/local.toml if it exists (never committed)
"""
from __future__ import annotations

import copy
import os
import tomllib
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "config" / "home.toml"
LOCAL = ROOT / "config" / "local.toml"


class SettingsError(ValueError):
    pass


def _merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _read(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path}: {exc}") from None


def _positive(data, section, key, kind=float):
    try:
        value = data[section][key]
    except KeyError:
        raise SettingsError(f"missing setting [{section}] {key}") from None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise SettingsError(f"[{section}] {key} must be a positive number, got {value!r}")
    if kind is int and value != int(value):
        raise SettingsError(f"[{section}] {key} must be a whole number, got {value!r}")
    return kind(value)


def validate(data):
    """Normalize types and fail loudly on a typo instead of slicing with a bad bed."""
    bed = data.get("printer", {}).get("bed_mm")
    if (not isinstance(bed, list) or len(bed) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in bed)):
        raise SettingsError(f"[printer] bed_mm must be two positive numbers, got {bed!r}")
    data["printer"]["bed_mm"] = [float(v) for v in bed]
    for key in ("max_print_height_mm", "nozzle_diameter_mm"):
        data["printer"][key] = _positive(data, "printer", key)
    data["printer"]["ifs_slots"] = _positive(data, "printer", "ifs_slots", int)
    for key in ("single_copy_edge_mm", "multi_copy_edge_mm", "merge_edge_margin_mm", "merge_spacing_mm"):
        data["layout"][key] = _positive(data, "layout", key)
    data["layout"]["max_merged_hours"] = _positive(data, "layout", "max_merged_hours")
    for key in ("size_mm", "part_clearance_mm", "edge_mm", "merge_slack_mm"):
        data["prime_tower"][key] = _positive(data, "prime_tower", key)
    command = data["orca"].get("command")
    if command is not None and (not isinstance(command, list) or not command
                                or not all(isinstance(v, str) and v for v in command)):
        raise SettingsError("[orca] command must be a list of strings, like [\"flatpak\", \"run\", \"io.github.softfever.OrcaSlicer\"]")
    for key, value in data.get("services", {}).items():
        if value is not None and not (isinstance(value, str) and value.startswith(("http://", "https://"))):
            raise SettingsError(f"[services] {key} must be an http(s) URL, got {value!r}")
    templates = data.get("orca", {}).get("templates")
    if not isinstance(templates, str) or not templates:
        raise SettingsError("[orca] templates must be a folder path")
    path = Path(templates).expanduser()
    data["orca"]["templates"] = path if path.is_absolute() else ROOT / path
    return data


def load(home=HOME, local=None):
    """Read and validate settings. local=None means $PRINT_BUDDY_CONFIG or config/local.toml."""
    data = _read(home)
    if local is None:
        env = os.environ.get("PRINT_BUDDY_CONFIG")
        if env:
            local = Path(env)
            if not local.is_file():
                raise SettingsError(f"PRINT_BUDDY_CONFIG points to a missing file: {local}")
        elif LOCAL.is_file():
            local = LOCAL
    if local:
        data = _merge(data, _read(local))
    return validate(data)


@lru_cache(maxsize=1)
def current():
    """Settings for this process, read once."""
    return load()
