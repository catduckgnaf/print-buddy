"""Bambu Lab printers, offline only: Orca slicing and G-code validation, no transport to the printer.

One adapter for the vendor; each printer subclasses it with its PrinterProfile (see a1.py). Deliberately imports
nothing from the ZMod/AD5X code and has no Moonraker, MQTT, FTPS or cloud client. Every live call raises
LiveUnsupported; the operator moves a verified file to the printer by hand.
"""
import json

from ..base import MultiColorUnsupported, PrinterAdapter
from . import guard


class LiveUnsupported(RuntimeError):
    """Print Buddy has no live connection to this printer: no telemetry, upload or print control."""


class BambuOfflineAdapter(PrinterAdapter):
    multi_slot = False
    transport = "offline"
    profile = None  # the printer's vendor.PrinterProfile, set by each printer's subclass

    @property
    def capabilities(self):
        return self.profile.capabilities

    @property
    def slot_count(self):
        return 1

    @property
    def motion_envelope_mm(self):
        return self.profile.value("motion_envelope_mm")

    def _unsupported(self, what):
        return LiveUnsupported(f"{self.label}: {what} is not supported; Print Buddy only slices and validates "
                               "G-code for this printer. Nothing was sent.")

    # slicer: the vendor start/end G-code is used as is; Print Buddy adds and changes nothing.
    def machine_start_gcode(self, template_start, mesh="auto"):
        if self.profile.vendor_start not in template_start:
            raise guard.ForeignStartCode(f"{self.label} start G-code is not the {self.profile.printer_model} vendor "
                                         "sequence; check [orca] templates")
        return guard.require_bambu_code(template_start, f"{self.label} start G-code")

    def machine_end_gcode(self, template_end):
        return guard.require_bambu_code(template_end, f"{self.label} end G-code")

    def start_plan(self, bed_temp, nozzle_temp, *, mesh="auto"):
        # Orca fills the vendor placeholders; these are the template lines the printer runs first.
        machine = json.loads((self.templates_dir() / "machine.json").read_text())
        return self.machine_start_gcode(machine["machine_start_gcode"]).splitlines()

    def gcode_problems(self, text, state=None):
        return guard.gcode_problems(text, self.profile, state=state, nozzle_sizes=self.supported_nozzle_sizes,
                                    nozzle_types=self.supported_nozzle_types)

    def moonraker_start_commands(self, remote_filename):
        raise self._unsupported("starting a print")

    def normalize_tool_mapping(self, mapping, state):
        tools = {str(k) for k in (mapping or {"0": 1})}
        if tools != {"0"}:
            raise MultiColorUnsupported(
                f"{self.label}: {self.profile.value('ams')[0]} multi-color is not supported yet; this job uses tools "
                f"{sorted(tools)}. Slice it single-color.")
        return {"0": 1}

    def readiness_problems(self, state, status, selection=None, **kw):
        """Offline record checks only. There is no live status to read."""
        problems = []
        state = state or {}
        bed, height = self.profile.value("bed_mm"), self.profile.value("max_print_height_mm")
        record_bed = state.get("bed_mm", bed)
        if any(float(v) > limit for v, limit in zip(record_bed, bed)):
            problems.append(f"recorded bed {record_bed[0]:g}x{record_bed[1]:g} mm exceeds the {self.label} "
                            f"{bed[0]:g}x{bed[1]:g} mm printable area")
        if float(state.get("max_print_height_mm", height)) > height:
            problems.append(f"recorded height {float(state['max_print_height_mm']):g} mm exceeds the {self.label} "
                            f"{height:g} mm limit")
        nozzle = state.get("nozzle") or {}
        if nozzle.get("diameter_mm") not in self.supported_nozzle_sizes:
            problems.append(f"recorded nozzle {nozzle.get('diameter_mm')!r} mm has no {self.label} template "
                            f"(supported: {', '.join(f'{s:g}' for s in self.supported_nozzle_sizes)})")
        from ...core.nozzle import NozzleError, normalize_nozzle_type
        try:
            kind = normalize_nozzle_type(nozzle.get("type") or "")
        except NozzleError:
            kind = nozzle.get("type")
        if kind not in self.supported_nozzle_types:
            problems.append(f"recorded nozzle type {nozzle.get('type')!r} is not an {self.label} option "
                            f"({', '.join(self.supported_nozzle_types)})")
        return problems

    def moonraker_objects(self):
        raise self._unsupported("live telemetry")

    def normalize_status(self, raw):
        return {"state": "unknown", "filename": "", "progress": None, "hotend_c": None, "bed_c": None}
