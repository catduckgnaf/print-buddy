"""Printer model and adapter contract.

Layout: one package per brand under print_buddy/printers/, one module per printer model inside it.

    flashforge/ad5x.py    MODEL for "flashforge.ad5x"; adapter.py (ZMod adapter); zmod/ (AD5X-only code)
    sovol/sv06.py         MODEL for "sovol.sv06" on the stock Klipper adapter
    klipper/generic.py    MODEL for "klipper.generic"; adapter.py (the stock Klipper adapter)

A model module defines MODEL = PrinterModel(...): the printer's settings (bed, height, nozzle, slots,
margins, prime tower, start/end macros, cold pull), the adapter class, and the Orca template folder under
templates/orca. printers/__init__ finds every module with a MODEL, so adding a printer is one file plus
templates. Brand code that is not a model lives in helper modules without a MODEL or in a subpackage.

Settings merge, later wins key by key: model defaults, config/home.toml, config/local.toml, environment.
config/home.toml picks the model with [printer] model = "flashforge.ad5x".

Where printer specifics live, and which responsibilities sit behind PrinterAdapter:

  responsibility                 flashforge.ad5x (ZMod)                  klipper.generic / sovol.sv06
  -----------------------------  --------------------------------------  ----------------------------
  build volume, margins          model settings                          same keys, 1 slot
  slot count / multi-slot        [printer] ifs_slots (IFS, 4)            1, single extruder
  Orca template folder           templates/orca/flashforge_ad5x          templates/orca/<model folder>
  Orca start G-code              START_PRINT ... MESH=<mesh> + M190/     PRINT_START BED= HOTEND=
                                 M104 preamble (adapter)                 (macro names from settings)
  start plan for a job           START_PRINT BED_TEMP EXTRUDER_TEMP      PRINT_START BED HOTEND
  tool -> slot mapping           zmod.multicolor_contract                T0 only; multicolor refused
  readiness check                model_job.check_filament_readiness      print_stats / heater sanity
  screen / slot sync             zmod.screen (CHANGE_ZCOLOR)             none (returns None)
  native status API              zmod.stock (/detail)                    none (returns None)
  telemetry normalization        Moonraker + zmod_color                  plain Moonraker objects

Core reaches ZMod code only through adapter.native (the printers.flashforge.zmod package): finalize,
embedded_mapping, normalize_mapping, describe_mapping, validate_materials, the stock /detail readers,
native_startup and native_idle. A printer without them raises MultiColorUnsupported from `native`.

Runtime decisions that follow the adapter (core/model_job, printer_state, orca_adapter, the listener):
  - multi_slot False (generic/sovol): no IFS selection or spool-slot validation, no multicolor finalization,
    no native_startup/native_idle, no mapped-native launch; slicing refuses multicolor and multi-plate sources
    with MultiColorUnsupported (a REFUSED line).
  - has_native_screen False: no display_off/LOAD_ZOFFSET/Adventurer5M offset authority, no ZMod MD5, no stock
    /detail polling, no screen-cancel firmware restart, no mesh-profile readiness (the printer owns its mesh).
  - readiness (readiness_problems), the start request (moonraker_start_commands) and the multicolor refusal
    (normalize_tool_mapping) are adapter calls on every model; flashforge.ad5x delegates to the old functions.
  - JOB.json records `printer_model` when sliced; print-now refuses a job whose model differs from
    [printer] model. A job without the field is a flashforge.ad5x job.

Still AD5X-coupled code in shared modules, reached only when multi_slot / has_native_screen. It is mixed
with printer-neutral logic (Spoolman, Discord, plate handling), so it stays until a second multi-slot model
exists to show the seam:
  - core/model_job: IFS selection and filament readiness, mapped-native launch (print_mapped_native), the
    zmod_color / display_off telemetry read, thin delegators to zmod.stock
  - core/prepared_intake, core/plate_merge, core/color_geometry, core/source_colors: ifs_slots bounds, the
    four-slot mapping and prime tower placement for IFS multicolor plates
  - core/orca_adapter: the START_PRINT/MESH start G-code goes through the adapter; IFS_SLOTS guard bounds
    and the tool-mapped prime tower retry remain
  - core/spool_lifecycle, core/clear_job: IFS slot reconciliation, native idle cancel handling
  - hermes/spool_sync (Spoolman binding), moonraker_event_listener (IFS presence poll, runout pause),
    print_control (native /detail cancel), print_next and the Discord IFS prompts: "AD5X" wording
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MultiColorUnsupported(RuntimeError):
    """The selected printer model cannot run this multi-color job."""


@dataclass(frozen=True)
class BuildVolume:
    bed_mm: tuple[float, float]
    max_height_mm: float
    single_copy_edge_mm: float
    multi_copy_edge_mm: float


@dataclass(frozen=True)
class PrinterModel:
    """One printer: its defaults, its adapter and its Orca template folder."""

    key: str  # "brand.model", the [printer] model value
    label: str
    adapter: type  # PrinterAdapter subclass
    templates: str  # folder under print_buddy/templates/orca
    # Defaults for [printer], [layout], [prime_tower] and [cold_pull]; config files and the environment override them.
    settings: dict
    # Protected-settings baseline file under config/; None uses the shared protected-settings-baseline.json.
    baseline: str | None = None

    def defaults(self) -> dict[str, Any]:
        """Settings this model contributes, including its Orca template folder."""
        out = copy.deepcopy(self.settings)
        out.setdefault("printer", {})["model"] = self.key
        out.setdefault("orca", {})["templates"] = f"print_buddy/templates/orca/{self.templates}"
        return out


class PrinterAdapter(ABC):
    """What call sites need from a printer model. Build with a settings dict (default: process settings)."""

    multi_slot: bool = False
    # ZMod-style native screen: display_off modes, saved/screen Z offset authority, MD5 gcode, stock /detail.
    has_native_screen: bool = False

    def __init__(self, config: dict[str, Any] | None = None, model: PrinterModel | None = None):
        if config is None:
            from .. import settings
            config = settings.current()
        if model is None:
            from . import model as _model
            model = _model(config["printer"]["model"])
        self.config = config
        self.model = model

    @property
    def key(self) -> str:
        return self.model.key

    @property
    def label(self) -> str:
        return self.model.label

    @property
    def baseline_path(self) -> Path | None:
        """This model's protected-settings baseline, or None for the shared file."""
        if self.model.baseline is None:
            return None
        from .. import settings
        return settings.ROOT / "config" / self.model.baseline

    @property
    def native(self):
        """ZMod/native helpers (printers.flashforge.zmod); stock Klipper has none."""
        raise MultiColorUnsupported(f"{self.label} has no ZMod/native support")

    # geometry and slots
    def build_volume(self) -> BuildVolume:
        p, lay = self.config["printer"], self.config["layout"]
        return BuildVolume((float(p["bed_mm"][0]), float(p["bed_mm"][1])), float(p["max_print_height_mm"]),
                           float(lay["single_copy_edge_mm"]), float(lay["multi_copy_edge_mm"]))

    @property
    @abstractmethod
    def slot_count(self) -> int: ...

    # slicer
    def templates_dir(self) -> Path:
        """Folder with machine.json, process.json and filament.json for Orca (an [orca] templates override applies)."""
        from .. import settings
        if self.config["printer"].get("model") == self.key:
            return Path(self.config["orca"]["templates"])
        return settings.ROOT / "print_buddy" / "templates" / "orca" / self.model.templates

    @abstractmethod
    def machine_start_gcode(self, template_start: str, mesh: str = "auto") -> str:
        """Orca machine_start_gcode for this printer; template_start is the template's own text."""

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
        """G-code that tells a native screen what is loaded, or None when the printer has no screen sync."""
        return None

    def stock_api_url(self, host: str) -> str | None:
        """Vendor status endpoint, or None when the printer only speaks Moonraker."""
        return None

    # telemetry
    @abstractmethod
    def moonraker_objects(self) -> list[str]:
        """Moonraker objects to query for status."""

    @abstractmethod
    def normalize_status(self, raw: dict) -> dict[str, Any]:
        """Moonraker 'status' dict -> {state, progress, filename, hotend_c, bed_c, ...}."""


def basic_status(raw: dict) -> dict[str, Any]:
    """Plain Moonraker fields shared by every model."""
    raw = raw if isinstance(raw, dict) else {}
    stats = raw.get("print_stats") or {}
    return {
        "state": stats.get("state", "unknown"),
        "filename": stats.get("filename") or "",
        "progress": (raw.get("virtual_sdcard") or {}).get("progress"),
        "hotend_c": (raw.get("extruder") or {}).get("temperature"),
        "bed_c": (raw.get("heater_bed") or {}).get("temperature"),
    }
