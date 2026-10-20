"""Printer and layout settings, read from config/home.toml with optional local overrides.

Load order, later wins key by key:
  1. The printer model's defaults (print_buddy/printers/<brand>/<model>.py), chosen by [printer] model
  2. config/home.toml (committed, the home setup; tests use it)
  3. $PRINT_BUDDY_CONFIG if set, otherwise config/local.toml if it exists (never committed)
  4. Environment: PRINT_BUDDY__SECTION__KEY, or a legacy name from LEGACY_ENV

The model comes from the last of home.toml, local.toml and PRINT_BUDDY__PRINTER__MODEL that sets it.
Every key must already exist in the model defaults or home.toml with the same type, so a typo fails loudly.
"""
from __future__ import annotations

import copy
import os
import re
import tomllib
from functools import lru_cache
from pathlib import Path

from . import printers

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "config" / "home.toml"
LOCAL = ROOT / "config" / "local.toml"


class SettingsError(ValueError):
    pass


# Environment names the running home services already set. They keep working unchanged.
LEGACY_ENV = {
    "MOONRAKER_URL": ("services", "moonraker_url"),
    "MOONRAKER_WS_URL": ("services", "moonraker_ws_url"),
    "SPOOLMAN_URL": ("services", "spoolman_url"),
    "OPENVIKING_URL": ("services", "openviking_url"),
    "PRINT_VISION_CHAT_URL": ("services", "vision_chat_url"),
    "PRINT_DISCORD_CHAT_ID": ("discord", "chat_id"),
    "DISCORD_UPLOAD_MAX_BYTES": ("discord", "upload_max_bytes"),
    "DISCORD_POST_PRINT_QUIET_SECONDS": ("discord", "post_print_quiet_s"),
    "DISCORD_DAILY_RESET_HOUR": ("discord", "daily_reset_hour"),
    "MOONRAKER_LISTENER_TICK_SECONDS": ("listener", "tick_s"),
    "IFS_PRESENCE_POLL_SECONDS": ("listener", "ifs_presence_poll_s"),
    "SPOOL_NAG_SECONDS": ("listener", "spool_nag_s"),
    "PRINT_VISION_MODEL": ("vision", "model"),
    "PRINT_TIMELAPSE_ARCHIVE_HOST": ("timelapse", "archive_host"),
    "PRINT_TIMELAPSE_ARCHIVE_DIR": ("timelapse", "archive_dir"),
    "PRINT_TIMELAPSE_SSH_KEY": ("timelapse", "ssh_key"),
    "PRINT_TIMELAPSE_RENDER_WAIT_SECONDS": ("timelapse", "render_wait_s"),
    "PRINT_TIMELAPSE_RENDER_POLL_SECONDS": ("timelapse", "render_poll_s"),
    "PRINT_TIMELAPSE_MAX_BYTES": ("timelapse", "max_bytes"),
    "PRINT_TIMELAPSE_LOCAL_RETENTION_DAYS": ("timelapse", "local_retention_days"),
    "PRINT_TIMELAPSE_PLAN_CLIP_RETENTION_DAYS": ("timelapse", "plan_clip_retention_days"),
    "MAINTENANCE_QUICK_HOURS": ("maintenance", "quick_hours"),
    "MAINTENANCE_FULL_HOURS": ("maintenance", "full_hours"),
    "MAINTENANCE_FULL_DAYS": ("maintenance", "full_days"),
    "HERMES_BIN": ("paths", "hermes_bin"),
    "FFMPEG_BIN": ("paths", "ffmpeg"),
    "PRINT_BUDDY_ARCHIVE": ("paths", "archive"),
    "PRINT_RECORDS_VAULT": ("paths", "records_vault"),
}
# Sections whose keys are names you choose, not a fixed set.
OPEN_SECTIONS = {"cold_pull"}


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


def _same_type(expected, value):
    if isinstance(expected, bool) or isinstance(value, bool):
        return isinstance(expected, bool) and isinstance(value, bool)
    if isinstance(expected, (int, float)):
        return isinstance(value, (int, float))
    return type(expected) is type(value)


def _unknown(source, section, key):
    hint = ""
    if (section, key) == ("printer", "family"):
        hint = ' ([printer] family was replaced by model, e.g. model = "flashforge.ad5x"; see README "Printer models")'
    return SettingsError(f"{source}: unknown setting [{section}] {key}{hint}")


def _check_keys(home, extra, source):
    """Reject keys home.toml does not define, and values of the wrong type."""
    for section, values in extra.items():
        if section not in home or not isinstance(values, dict):
            raise SettingsError(f"{source}: unknown section [{section}]")
        for key, value in values.items():
            if key not in home[section]:
                if section in OPEN_SECTIONS:
                    continue
                raise _unknown(source, section, key)
            if not _same_type(home[section][key], value):
                raise SettingsError(f"{source}: [{section}] {key} should be like {home[section][key]!r}, got {value!r}")


def _coerce(expected, raw, name):
    try:
        if isinstance(expected, bool):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(expected, int):
            return int(raw)
        if isinstance(expected, float):
            return float(raw)
    except ValueError:
        raise SettingsError(f"${name} should be a number, got {raw!r}") from None
    if isinstance(expected, str):
        return raw
    raise SettingsError(f"${name}: [list] settings cannot come from the environment")


def _from_env(home, environ):
    out = {}
    for name, raw in environ.items():
        if name.startswith("PRINT_BUDDY__"):
            parts = name[len("PRINT_BUDDY__"):].lower().split("__")
            if len(parts) != 2:
                raise SettingsError(f"${name} must look like PRINT_BUDDY__SECTION__KEY")
            section, key = parts
        elif name in LEGACY_ENV:
            section, key = LEGACY_ENV[name]
        else:
            continue
        if key not in home.get(section, {}):
            raise _unknown(f"${name}", section, key)
        out.setdefault(section, {})[key] = _coerce(home[section][key], raw, name)
    return out


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
    key = data["printer"].get("model")
    if key not in printers.MODELS:
        raise SettingsError(f"[printer] model must be one of {', '.join(printers.MODELS)}, got {key!r}")
    if not printers.MODELS[key].adapter.multi_slot and data["printer"]["ifs_slots"] != 1:
        raise SettingsError(f"[printer] ifs_slots must be 1 for model {key!r} (single extruder)")
    for key, default in (("start_macro", "PRINT_START"), ("end_macro", "PRINT_END")):
        macro = data["printer"].setdefault(key, default)
        if not isinstance(macro, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", macro):
            raise SettingsError(f"[printer] {key} must be a Klipper macro name, got {macro!r}")
    for key in ("single_copy_edge_mm", "multi_copy_edge_mm", "merge_edge_margin_mm", "merge_spacing_mm"):
        data["layout"][key] = _positive(data, "layout", key)
    data["layout"]["max_merged_hours"] = _positive(data, "layout", "max_merged_hours")
    for key in ("size_mm", "part_clearance_mm", "edge_mm", "merge_slack_mm"):
        data["prime_tower"][key] = _positive(data, "prime_tower", key)
    for section in ("orca", "bambu"):
        command = data.get(section, {}).get("command")
        if not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
            raise SettingsError(f"[{section}] command must be a list of strings, like [\"flatpak\", \"run\", \"com.orcaslicer.OrcaSlicer\"]")
    services = data["services"]
    for key, value in services.items():
        if key.endswith("_url") and value and not value.startswith(("ws://", "wss://") if key == "moonraker_ws_url" else ("http://", "https://")):
            raise SettingsError(f"[services] {key} must be a URL, got {value!r}")
    if services["moonraker_url"]:
        base = services["moonraker_url"].rstrip("/")
        host = base.split("://", 1)[1].split("/", 1)[0].rsplit(":", 1)[0]
        services["moonraker_ws_url"] = services["moonraker_ws_url"] or base.replace("http", "ws", 1) + "/websocket"
        services["camera_snapshot_url"] = services["camera_snapshot_url"] or f"http://{host}/webcam/?action=snapshot"
    for key, value in data["paths"].items():
        if key == "ffmpeg" and "/" not in value:
            continue  # a bare name is looked up on PATH
        path = Path(value).expanduser()
        data["paths"][key] = path if path.is_absolute() else ROOT / path
    level = data["visual_watch"]["sensitivity"]
    if isinstance(level, bool) or not isinstance(level, (int, float)) or level != int(level) or not 1 <= level <= 5:
        raise SettingsError(f"[visual_watch] sensitivity must be a whole number from 1 to 5, got {level!r}")
    data["visual_watch"]["sensitivity"] = int(level)
    for key in ("question_timeout_s", "safety_confirm_timeout_s", "upload_wait_s", "cold_pull_outcome_s"):
        data["discord"][key] = _positive(data, "discord", key, int)
    templates = data.get("orca", {}).get("templates")
    if not isinstance(templates, str) or not templates:
        raise SettingsError("[orca] templates must be a folder path")
    path = Path(templates).expanduser()
    data["orca"]["templates"] = path if path.is_absolute() else ROOT / path
    return data


def load(home=HOME, local=None, environ=None):
    """Read and validate settings. local=None means $PRINT_BUDDY_CONFIG or config/local.toml.

    environ defaults to os.environ; pass {} to ignore the environment.
    """
    home_data = _read(home)
    environ = os.environ if environ is None else environ
    if local is None:
        env = os.environ.get("PRINT_BUDDY_CONFIG")
        if env:
            local = Path(env)
            if not local.is_file():
                raise SettingsError(f"PRINT_BUDDY_CONFIG points to a missing file: {local}")
        elif LOCAL.is_file():
            local = LOCAL
    extra = _read(local) if local else {}
    key = (environ.get("PRINT_BUDDY__PRINTER__MODEL") or extra.get("printer", {}).get("model")
           or home_data.get("printer", {}).get("model"))
    if key not in printers.MODELS:
        raise SettingsError(f"[printer] model must be one of {', '.join(printers.MODELS)}, got {key!r}")
    data = _merge(printers.MODELS[key].defaults(), home_data)
    base = copy.deepcopy(data)
    if local:
        _check_keys(base, extra, local)
        data = _merge(data, extra)
    data = _merge(data, _from_env(base, environ))
    return validate(data)


@lru_cache(maxsize=1)
def current():
    """Settings for this process, read once."""
    return load()


def state_dir(data=None):
    """Where runtime state files live: <hermes_home>/state."""
    return (data or current())["paths"]["hermes_home"] / "state"


def _main(argv):
    """python3 -m print_buddy.settings get services.moonraker_url  (for shell scripts)"""
    if len(argv) != 2 or argv[0] != "get" or argv[1].count(".") != 1:
        raise SystemExit("usage: python3 -m print_buddy.settings get SECTION.KEY")
    section, key = argv[1].split(".")
    try:
        value = current()[section][key]
    except KeyError:
        raise SystemExit(f"unknown setting {argv[1]}") from None
    print(" ".join(map(str, value)) if isinstance(value, list) else value)


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
