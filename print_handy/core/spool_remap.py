"""Spoolman and a colour remap made on the printer after a .gcode.3mf start (#619).

Stage 1 says the limitation on the confirm card. A .gcode job does not get the
line, because the screen cannot remap that file. Stage 2 (read the map back)
is not in this change: no recorded fixture shows the printer reporting the
slot map the job actually used, and a missing map must not be invented.
"""
from __future__ import annotations

from . import gcode_3mf

NOTE = ("A color remap made on the printer after this .gcode.3mf starts is not "
        "written back to Spoolman. Spoolman keeps the mapping confirmed here.")


def note_for(setting, zmod_version) -> str:
    """The confirm-card sentence, or "" when this job will be plain G-code.

    ``auto`` with an unknown version stays on G-code (the delivery rule), so
    it does not get the sentence. A forced ``3mf`` setting does, and so does
    ``auto`` once the printer has reported ZMod 1.7.5 or newer.
    """
    fmt, _reason = gcode_3mf.resolve_format(setting, zmod_version)
    return NOTE if fmt == "3mf" else ""


def confirm_note(adapter, job=None) -> str:
    """The sentence for one confirm card, or "" when this card is not a 3MF send.

    A job that already recorded ``delivery_format.format == "3mf"`` is a 3MF
    send even if the version is not in hand. Anything else follows the
    printer's setting, and an unknown version does not guess.
    """
    recorded = (job or {}).get("delivery_format") if isinstance(job, dict) else None
    if isinstance(recorded, dict) and recorded.get("format") == "3mf":
        return NOTE
    model = getattr(adapter, "model", None)
    if getattr(model, "vendor_key", None) != "flashforge":
        return ""
    config = getattr(adapter, "config", None) or {}
    printer = config.get("printer") if isinstance(config, dict) else None
    setting = (printer or {}).get("zmod_delivery_format") if isinstance(printer, dict) else "gcode"
    version = None
    if isinstance(recorded, dict) and recorded.get("zmod_version"):
        parts = tuple(int(p) for p in str(recorded["zmod_version"]).split(".") if p.isdigit())
        version = parts or None
    return note_for(setting, version)
