"""Prusa XL (5-tool) (inherits prusa VENDOR). The XL with five toolheads: 360 mm cube build
volume. The XL is a multi_tool model (#670): slicer tool i prints with toolhead i (T0-T4),
the mapping is identity-only, and a job's tool changes are the sliced file's own T lines —
PrusaLink starts a file and takes no tool parameter, so the file drives the changer exactly
as it does on the Creator pair. Readiness and status stay printer-level: the published
PrusaLink API exposes no per-toolhead telemetry (evidence on #670).

Sourced values: facts.py (XL); docs/PRUSA.md. Templates: generated on the operator's
machine from their own OrcaSlicer into <state>/orca-profiles/prusa_xl (profiles.py); none are shipped.
"""
from ..base import MultiColorUnsupported, PrinterModel
from . import VENDOR, facts
from .adapter import PrusaAdapter


class XLAdapter(PrusaAdapter):
    """The XL: five toolheads behind the shared PrusaLink contract.

    Filament positions on this machine are its toolheads (the Creator pair's
    contract): slot_count is the tool count, so position limits, the tool-shaped
    color intake (#346) and per-toolhead Spoolman positions reach the XL through
    the adapter contract in core without any Prusa-specific core code.
    """

    facts = facts.XL

    @property
    def slot_count(self):
        return self.tool_count

    def normalize_tool_mapping(self, mapping, state):
        """Identity only: slicer tool i prints with toolhead i + 1 (T0 -> toolhead 1).

        Follows the Creator pair's contract: anything else — a remap, a tool the
        machine does not have, a non-numeric entry — is refused with the reason
        named, never silently adjusted. An empty mapping is the single-tool job
        {0: 1}.
        """
        out = {}
        for tool, head in (mapping or {}).items():
            try:
                t, h = int(tool), int(head)
            except (TypeError, ValueError):
                raise MultiColorUnsupported(
                    f"{self.label} tool mapping {tool!r} -> {head!r} is not a tool number") from None
            if not 0 <= t < self.tool_count:
                raise MultiColorUnsupported(
                    f"{self.label} has {self.tool_count} toolheads (T0-T{self.tool_count - 1}); "
                    f"this job uses tool T{t}. Slice it for this printer, or use a printer "
                    "with more toolheads.")
            if h != t + 1:
                raise MultiColorUnsupported(
                    f"{self.label} tool T{t} always prints with toolhead {t + 1}; "
                    f"a mapping to position {h} cannot be represented.")
            out[str(t)] = h
        return out or {"0": 1}


MODEL = PrinterModel(
    key="prusa.xl",
    label="Prusa XL (5-tool)",
    adapter=XLAdapter,
    templates="prusa_xl",
    generated_templates=True,
    vendor=VENDOR,
    baseline="protected-settings-baseline.prusa.xl.json",
    supported_nozzle_sizes=(0.4,),
    supported_nozzle_types=("brass", "stainless_steel", "hardened_steel"),
    color_system="multi_tool",
    settings={
        "printer": {
            "name": "Prusa XL (5-tool)",
            "bed_mm": list(facts.XL["bed_mm"].value),
            "max_print_height_mm": facts.XL["max_print_height_mm"].value,
            "nozzle_diameter_mm": 0.4,
            "nozzle_type": "brass",
            # Five independent toolheads (tools, not slots): filament_slots stays 1 so no
            # IFS behavior in core switches on; tool_count names the heads (#670).
            "filament_slots": 1,
            "tool_count": 5,
        },
    },
)
