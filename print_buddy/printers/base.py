"""Printer adapter contract.

Where printer-family specifics live, and which responsibilities sit behind PrinterAdapter:

  responsibility                 flashforge_zmod (AD5X)                  generic/sovol klipper
  -----------------------------  --------------------------------------  ----------------------------
  build volume, margins          settings [printer]/[layout]             same settings, 1 slot
  slot count / multi-slot        [printer] ifs_slots (IFS, 4)            1, single extruder
  Orca template folder           templates/orca (unchanged)              templates/orca/<family>
  Orca start G-code              START_PRINT ... MESH=<mesh> + M190/     PRINT_START BED= HOTEND=
                                 M104 preamble (orca_adapter)            (macro names from settings)
  start plan for a job           START_PRINT BED_TEMP EXTRUDER_TEMP      PRINT_START BED HOTEND
  tool -> slot mapping           multicolor_contract.normalize_mapping   T0 only; multicolor refused
  readiness check                model_job.check_filament_readiness      print_stats / heater sanity
  screen / slot sync             CHANGE_ZCOLOR (spool_sync)              none (returns None)
  native status API              stock /detail on stock_api_port         none (returns None)
  telemetry normalization        Moonraker + zmod_color                  plain Moonraker objects

Runtime decisions that follow the adapter (core/model_job, printer_state, orca_adapter, the listener):
  - multi_slot False (generic/sovol): no IFS selection or spool-slot validation, no multicolor finalization,
    no native_startup/native_idle, no mapped-native launch; slicing refuses multicolor and multi-plate sources
    with MultiColorUnsupported (a REFUSED line).
  - has_native_screen False: no display_off/LOAD_ZOFFSET/Adventurer5M offset authority, no ZMod MD5, no stock
    /detail polling, no screen-cancel firmware restart, no mesh-profile readiness (the printer owns its mesh).
  - readiness (readiness_problems), the start request (moonraker_start_commands) and the multicolor refusal
    (normalize_tool_mapping) are adapter calls on every family; flashforge_zmod delegates to the old functions.
  - JOB.json records `printer_family` when sliced; print-now refuses a job whose family differs from
    [printer] family. A job without the field is a flashforge_zmod job.

Still AD5X-only code, left in place and reached only when multi_slot / has_native_screen: ifs_slots state
(spool_lifecycle, prepared_intake, plate_merge, slice_guard IFS bounds), native_startup/native_idle/
multicolor_contract finalization, print_mapped_native, the Discord IFS prompts and the "AD5X" wording in
those paths. A second multi-slot family would start there.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MultiColorUnsupported(RuntimeError):
    """The selected printer family cannot run this multi-color job."""


@dataclass(frozen=True)
class BuildVolume:
    bed_mm: tuple[float, float]
    max_height_mm: float
    single_copy_edge_mm: float
    multi_copy_edge_mm: float


class PrinterAdapter(ABC):
    """What call sites need from a printer family. Build with a settings dict (default: process settings)."""

    family: str = ""
    label: str = ""
    multi_slot: bool = False
    # ZMod-style native screen: display_off modes, saved/screen Z offset authority, MD5 gcode, stock /detail.
    has_native_screen: bool = False

    def __init__(self, config: dict[str, Any] | None = None):
        if config is None:
            from .. import settings
            config = settings.current()
        self.config = config

    # geometry and slots
    def build_volume(self) -> BuildVolume:
        p, lay = self.config["printer"], self.config["layout"]
        return BuildVolume((float(p["bed_mm"][0]), float(p["bed_mm"][1])), float(p["max_print_height_mm"]),
                           float(lay["single_copy_edge_mm"]), float(lay["multi_copy_edge_mm"]))

    @property
    @abstractmethod
    def slot_count(self) -> int: ...

    # slicer
    @abstractmethod
    def templates_dir(self) -> Path:
        """Folder with machine.json, process.json and filament.json for Orca."""

    @abstractmethod
    def machine_start_gcode(self, template_start: str, mesh: str = "auto") -> str:
        """Orca machine_start_gcode for this family; template_start is the template's own text."""

    @abstractmethod
    def machine_end_gcode(self, template_end: str) -> str: ...

    @abstractmethod
    def start_plan(self, bed_temp: float, nozzle_temp: float, *, mesh: str = "auto") -> list[str]:
        """Resolved start G-code lines for one job (what the printer executes first)."""

    @abstractmethod
    def moonraker_start_commands(self, remote_filename: str) -> list[dict[str, Any]]:
        """Moonraker requests, in order, that start a print: [{'method', 'path', 'body'}]."""

    # color / tools
    @abstractmethod
    def normalize_tool_mapping(self, mapping: dict, state: dict) -> dict[str, int]:
        """Validate a tool index -> physical slot map. Raises MultiColorUnsupported when unsupported."""

    # readiness and sync
    @abstractmethod
    def readiness_problems(self, state: dict, status: dict, selection: dict | None = None, **kw) -> list[str]:
        """Reasons the printer is not ready to start; empty when ready."""

    def screen_command(self, slot: int, material: str, hex_code: str) -> str | None:
        """G-code that tells a native screen what is loaded, or None when the family has no screen sync."""
        return None

    def stock_api_url(self, host: str) -> str | None:
        """Vendor status endpoint, or None when the family only speaks Moonraker."""
        return None

    # telemetry
    @abstractmethod
    def moonraker_objects(self) -> list[str]:
        """Moonraker objects to query for status."""

    @abstractmethod
    def normalize_status(self, raw: dict) -> dict[str, Any]:
        """Moonraker 'status' dict -> {state, progress, filename, hotend_c, bed_c, ...}."""


def basic_status(raw: dict) -> dict[str, Any]:
    """Plain Moonraker fields shared by every family."""
    raw = raw if isinstance(raw, dict) else {}
    stats = raw.get("print_stats") or {}
    return {
        "state": stats.get("state", "unknown"),
        "filename": stats.get("filename") or "",
        "progress": (raw.get("virtual_sdcard") or {}).get("progress"),
        "hotend_c": (raw.get("extruder") or {}).get("temperature"),
        "bed_c": (raw.get("heater_bed") or {}).get("temperature"),
    }
