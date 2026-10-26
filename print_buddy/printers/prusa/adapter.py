"""Prusa printers: Orca slicing and G-code validation, plus opt-in PrusaLink LAN.

VENDOR (prusa/__init__.py) is the authority for connection ("prusalink"), start code, slicers and
delivery. The LAN path (client.py) exists only when the operator configures [prusa] link_host and
supplies the PrusaLink API key through an environment variable; without that configuration the
adapter behaves as an offline adapter. Each printer subclasses this adapter with its facts
(see mk4s.py). Deliberately imports nothing from the ZMod/AD5X, Moonraker or Bambu code.
"""
import os

from ..base import MultiColorUnsupported, PrinterAdapter
from . import guard, profiles
from .client import PrusaLinkClient, PrusaLinkError


class LiveUnsupported(RuntimeError):
    """A Moonraker-shaped live call reached a Prusa printer; Prusa uses PrusaLink instead."""


# PrusaLink printer states -> Print Buddy's normalized state vocabulary.
_PRINTER_STATES = {
    "IDLE": "standby", "READY": "standby", "PRINTING": "printing", "BUSY": "printing",
    "PAUSED": "paused", "FINISHED": "complete", "STOPPED": "error", "ERROR": "error",
    "ATTENTION": "error",
}
_BUSY_STATES = {"PRINTING", "BUSY", "PAUSED"}


class PrusaAdapter(PrinterAdapter):
    multi_slot = False
    transport = "prusalink"
    facts: dict = {}  # the printer's sourced facts (facts.py), set by each printer's subclass
    verified_slicers = ("orca",)

    def fact(self, name):
        return self.facts[name].value

    @property
    def slot_count(self):
        return 1  # filament paths Print Buddy drives; the XL's other toolheads are not driven

    @property
    def motion_envelope_mm(self):
        return self.fact("motion_envelope_mm")

    def _unsupported(self, what):
        return LiveUnsupported(f"{self.label}: {what} is not supported over Moonraker; Prusa printers "
                               "use PrusaLink (status, upload and print start are separate calls). "
                               "Nothing was sent.")

    # -- LAN configuration ---------------------------------------------------
    def _link(self):
        return (self.config.get("prusa") or {})

    def link_configured(self) -> bool:
        """True when [prusa] link_host is set (the API key is a secret, checked by client())."""
        return bool(str(self._link().get("link_host") or "").strip())

    def api_key(self) -> str:
        """The PrusaLink API key from the environment variable [prusa] api_key_env names. Never from config."""
        name = str(self._link().get("api_key_env") or "PRUSA_LINK_API_KEY")
        return os.environ.get(name, "")

    def client(self, **overrides):
        """A PrusaLink client for the configured printer. Raises PrusaLinkError when unconfigured."""
        if not self.link_configured():
            raise PrusaLinkError(f"{self.label}: PrusaLink is not configured; set [prusa] link_host and "
                                 "supply the API key via the environment")
        return PrusaLinkClient(str(self._link()["link_host"]).strip(), self.api_key(), **overrides)

    def upload(self, local_path, remote_name=None):
        """Upload a sliced file (PUT, size-verified by the client). Starts nothing by itself."""
        return self.client().upload(local_path, remote_name)

    def start_print(self, remote_name):
        """Start an uploaded, verified file. Gates live in the print path."""
        return self.client().start_print(remote_name)

    def control(self, action):
        """Pause, resume or stop the current print over PrusaLink."""
        return self.client().control(action)

    # -- slicer ---------------------------------------------------------------
    def pinned_templates_folder(self):
        """Where this model's profiles are generated: <state>/orca-profiles/<templates>, never the repository."""
        from ... import settings
        return settings.generated_templates_dir(self.model, self.config)

    def pinned_templates(self):
        """The verified generated templates (profiles.require); an [orca] templates override is never the reference."""
        return profiles.require(self)

    def machine_start_gcode(self, template_start, mesh="auto"):
        return template_start  # the slicer owns the entire start sequence

    def machine_end_gcode(self, template_end):
        return template_end  # the slicer owns the entire end sequence

    def start_plan(self, bed_temp, nozzle_temp, *, mesh="auto"):
        # The vendor start sequence from the verified generated templates, as sliced.
        import json
        try:
            machine = json.loads((self.pinned_templates() / "machine.json").read_text())
        except Exception:
            return []
        return str(machine.get("machine_start_gcode") or "").splitlines()

    def moonraker_start_commands(self, remote_filename):
        raise self._unsupported("starting a print")

    def moonraker_objects(self):
        raise self._unsupported("Moonraker telemetry (this printer reports over PrusaLink)")

    def gcode_problems(self, text, state=None):
        return guard.gcode_problems(text, self, state=state)

    # -- color / tools -----------------------------------------------------------
    def normalize_tool_mapping(self, mapping, state):
        tools = {str(k) for k in (mapping or {"0": 1})}
        if tools != {"0"}:
            raise MultiColorUnsupported(
                f"{self.label}: multi-tool jobs are not supported; this job uses tools "
                f"{sorted(tools)}. Slice it single-tool (tool 0).")
        return {"0": 1}

    # -- readiness / status ---------------------------------------------------------
    def readiness_problems(self, state, status, selection=None, **kw):
        """Hardware-record checks, plus live checks when `status` is a PrusaLink snapshot.

        With no snapshot this is the offline behaviour: the recorded bed/height/nozzle must fit
        the model. With a snapshot, a busy printer is not ready and an error/attention state is
        reported.
        """
        problems = []
        state = state or {}
        bed, height = self.fact("bed_mm"), self.fact("max_print_height_mm")
        record_bed = state.get("bed_mm", bed)
        if any(float(v) > limit for v, limit in zip(record_bed, bed)):
            problems.append(f"recorded bed {record_bed[0]:g}x{record_bed[1]:g} mm exceeds the {self.label} "
                            f"{bed[0]:g}x{bed[1]:g} mm printable area")
        if float(state.get("max_print_height_mm", height)) > height:
            problems.append(f"recorded height {float(state['max_print_height_mm']):g} mm exceeds the "
                            f"{self.label} {height:g} mm limit")
        nozzle = state.get("nozzle") or {}
        if nozzle.get("diameter_mm") not in self.supported_nozzle_sizes:
            problems.append(f"recorded nozzle {nozzle.get('diameter_mm')!r} mm has no {self.label} template "
                            f"(supported: {', '.join(f'{s:g}' for s in self.supported_nozzle_sizes)})")
        printer = _printer_payload(status)
        if printer is not None:
            raw_state = str(printer.get("state") or "").upper()
            if raw_state in _BUSY_STATES:
                problems.append(f"printer is busy ({raw_state.lower()})")
            elif raw_state in ("ERROR", "ATTENTION"):
                problems.append(f"printer reports state {raw_state.lower()}")
        return problems

    def normalize_status(self, raw):
        """A PrusaLink snapshot (client.snapshot()) or bare status dict -> the common status shape."""
        status = raw.get("status") if isinstance(raw, dict) and isinstance(raw.get("status"), dict) else raw
        if not isinstance(status, dict):
            return {"state": "unknown", "filename": "", "progress": None, "hotend_c": None, "bed_c": None}
        printer = status.get("printer") or {}
        job = status.get("job") or {}
        job_detail = raw.get("job") if isinstance(raw, dict) else None
        if isinstance(job_detail, dict) and job_detail:
            job = {**job, **job_detail}
        file_info = job.get("file") or {}
        progress = job.get("progress")
        if isinstance(progress, (int, float)) and not isinstance(progress, bool):
            progress = progress / 100 if progress > 1 else progress
        else:
            progress = None
        remaining = job.get("time_remaining")
        return {
            "state": _PRINTER_STATES.get(str(printer.get("state") or "").upper(), "unknown"),
            "filename": file_info.get("display_name") or file_info.get("name") or "",
            "progress": progress,
            "hotend_c": _number(printer.get("temp_nozzle")),
            "bed_c": _number(printer.get("temp_bed")),
            "hotend_target_c": _number(printer.get("target_nozzle")),
            "bed_target_c": _number(printer.get("target_bed")),
            "remaining_min": (remaining // 60 if isinstance(remaining, (int, float))
                              and not isinstance(remaining, bool) else None),
            "job_id": job.get("id"),
        }


def _printer_payload(raw):
    """The `printer` dict inside a snapshot/status payload, or None when raw is not one."""
    if not isinstance(raw, dict):
        return None
    status = raw.get("status") if isinstance(raw.get("status"), dict) else raw
    if isinstance(status, dict) and isinstance(status.get("printer"), dict):
        return status["printer"]
    return None


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
