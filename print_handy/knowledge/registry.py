"""Load, validate and search the root-level registries (issue #169).

The data lives at the repository root so both the bot and a person browsing the
repo can find it without knowing the package layout:

    knowledge/symptoms.toml         what users report, and the flow that works it
    knowledge/troubleshooting.toml  the guided flows (see flows.py)
    firmware/commands.toml          commands, macros and errors per firmware family
    printers/registry.toml          one entry per registered printer model

This module is read-only. It opens no socket, imports no printer adapter and can
never turn a lookup into a printer action; a lookup returns registry text, and
physical actions stay behind the existing guarded print-control flows.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .flows import Flow, Node, Option

ROOT = Path(__file__).resolve().parents[2]
FIRMWARES = ("zmod", "klipper", "marlin")
ENTRY_KINDS = ("command", "macro", "error")
FLOW_KINDS = ("question", "advice")


class RegistryError(ValueError):
    """A registry file is missing, malformed, or breaks the schema rules."""


@dataclass(frozen=True)
class FirmwareEntry:
    id: str
    name: str
    aliases: tuple[str, ...]
    firmware: str
    kind: str
    printers: tuple[str, ...]
    command: str
    description: str
    safety: str
    notes: str = ""


@dataclass(frozen=True)
class Symptom:
    id: str
    title: str
    aliases: tuple[str, ...]
    flow: str
    firmware_entries: tuple[str, ...]
    summary: str
    first_checks: tuple[str, ...]


@dataclass(frozen=True)
class PrinterEntry:
    key: str
    label: str
    vendor: str
    firmware: str
    firmware_family: str
    connection: str
    kinematics: str
    bed_mm: tuple[float, float]
    max_height_mm: float
    filament_slots: int
    profile: str
    notes: str = ""
    # Independent toolheads (a tool changer) when the model has them; 0 means the
    # model's filament positions are its filament_slots (or a single extruder).
    tools: int = 0


@dataclass(frozen=True)
class Match:
    """One lookup hit. kind is firmware, symptom, flow or printer."""

    kind: str
    score: int
    item: object


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).strip()


def _score(query, targets):
    """Best match score of a normalized query against an item's names/aliases/ids. 0 is no match."""
    q = _norm(query)
    if not q:
        return 0
    qtokens = set(q.split())
    best = 0
    for target in targets:
        t = _norm(target)
        if not t:
            continue
        if q == t:
            return 100
        ttokens = set(t.split())
        if q in t or t in q:
            best = max(best, 85 if len(t) >= 3 else best)
        shared = qtokens & ttokens
        if shared:
            if qtokens <= ttokens:
                best = max(best, 75)
            best = max(best, round(60 * len(shared) / max(len(qtokens), len(ttokens))))
    return best


def _load(path):
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        raise RegistryError(f"registry file missing: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise RegistryError(f"registry file {path.name} does not parse: {exc}") from None


def _strings(value):
    return tuple(str(v).strip() for v in (value or ()) if str(v).strip())


@dataclass
class Registry:
    firmware_entries: tuple[FirmwareEntry, ...] = ()
    symptoms: tuple[Symptom, ...] = ()
    flows: tuple[Flow, ...] = ()
    printers: tuple[PrinterEntry, ...] = ()
    _by_id: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self._by_id = {}
        for entry in self.firmware_entries:
            self._by_id[entry.id] = ("firmware", entry)
        for symptom in self.symptoms:
            self._by_id[symptom.id] = ("symptom", symptom)
        for flow in self.flows:
            self._by_id[flow.id] = ("flow", flow)
        for printer in self.printers:
            self._by_id[printer.key] = ("printer", printer)

    # ------------------------------------------------------------------ lookups

    def flow(self, flow_id):
        hit = self._by_id.get(str(flow_id or "").strip())
        return hit[1] if hit and hit[0] == "flow" else None

    def lookup(self, query, *, firmware=None, printer=None, limit=5):
        """Ranked matches across all registries.

        `firmware` restricts firmware entries to one family; `printer` keeps only
        firmware entries known to apply to that printer model (plus "*" entries).
        Symptoms, flows and printers are never filtered out: a symptom report
        should find its flow whatever the machine is.
        """
        firmware = _norm(firmware).replace(" ", "") or None
        if firmware and firmware not in FIRMWARES:
            raise RegistryError(f"firmware must be one of {', '.join(FIRMWARES)}, got {firmware!r}")
        printer = str(printer or "").strip() or None
        scored: list[Match] = []
        for entry in self.firmware_entries:
            if firmware and entry.firmware != firmware:
                continue
            if printer and "*" not in entry.printers and printer not in entry.printers:
                continue
            score = _score(query, (entry.name, entry.id, *entry.aliases))
            if score:
                scored.append(Match("firmware", score, entry))
        for symptom in self.symptoms:
            score = _score(query, (symptom.title, symptom.id, *symptom.aliases))
            if score:
                scored.append(Match("symptom", score, symptom))
        for flow in self.flows:
            score = _score(query, (flow.title, flow.id, *flow.aliases))
            if score:
                scored.append(Match("flow", score, flow))
        for entry in self.printers:
            score = _score(query, (entry.label, entry.key, entry.key.split(".", 1)[-1], entry.vendor))
            if score:
                scored.append(Match("printer", score, entry))
        order = {"firmware": 0, "symptom": 1, "flow": 2, "printer": 3}
        scored = [m for m in scored if m.score >= 30]
        scored.sort(key=lambda m: (-m.score, order[m.kind], getattr(m.item, "id", getattr(m.item, "key", ""))))
        return scored[:limit]


def load_registry(root=ROOT) -> Registry:
    """Load and validate every registry. Raises RegistryError listing every problem found."""
    root = Path(root)
    problems: list[str] = []

    firmware_doc = _load(root / "firmware" / "commands.toml")
    symptoms_doc = _load(root / "knowledge" / "symptoms.toml")
    flows_doc = _load(root / "knowledge" / "troubleshooting.toml")
    printers_doc = _load(root / "printers" / "registry.toml")

    entries: list[FirmwareEntry] = []
    seen_ids: set[str] = set()
    for raw in firmware_doc.get("entry", []):
        entry = FirmwareEntry(
            id=str(raw.get("id", "")).strip(), name=str(raw.get("name", "")).strip(),
            aliases=_strings(raw.get("aliases")), firmware=str(raw.get("firmware", "")).strip(),
            kind=str(raw.get("kind", "")).strip(), printers=_strings(raw.get("printers")),
            command=str(raw.get("command", "")).strip(), description=str(raw.get("description", "")).strip(),
            safety=str(raw.get("safety", "")).strip(), notes=str(raw.get("notes", "")).strip())
        where = f"firmware entry {entry.id or '?'}"
        if not entry.id or entry.id in seen_ids:
            problems.append(f"{where}: id missing or duplicated")
        seen_ids.add(entry.id)
        if entry.firmware not in FIRMWARES:
            problems.append(f"{where}: firmware must be one of {FIRMWARES}")
        if entry.kind not in ENTRY_KINDS:
            problems.append(f"{where}: kind must be one of {ENTRY_KINDS}")
        if not entry.id.startswith(entry.firmware + "."):
            problems.append(f"{where}: id must start with '{entry.firmware}.'")
        if not entry.name or not entry.description or not entry.safety or not entry.printers:
            problems.append(f"{where}: name, description, safety and printers are required")
        if entry.kind != "error" and not entry.command:
            problems.append(f"{where}: a {entry.kind} entry needs its command line")
        entries.append(entry)
    entry_ids = {e.id for e in entries}

    flows: list[Flow] = []
    for raw in flows_doc.get("flow", []):
        nodes: dict[str, Node] = {}
        for nraw in raw.get("node", []):
            options = tuple(Option(label=str(o.get("label", "")).strip(), next=str(o.get("next", "")).strip())
                            for o in nraw.get("option", []))
            node = Node(id=str(nraw.get("id", "")).strip(), kind=str(nraw.get("kind", "")).strip(),
                        prompt=str(nraw.get("prompt", "")).strip(), options=options,
                        next=(str(nraw["next"]).strip() if nraw.get("next") else None))
            if node.id in nodes:
                problems.append(f"flow {raw.get('id')}: node id {node.id!r} duplicated")
            nodes[node.id] = node
        flow = Flow(id=str(raw.get("id", "")).strip(), title=str(raw.get("title", "")).strip(),
                    aliases=_strings(raw.get("aliases")), safety=_strings(raw.get("safety")),
                    start=str(raw.get("start", "")).strip(), nodes=nodes)
        where = f"flow {flow.id or '?'}"
        if not flow.title or not flow.safety:
            problems.append(f"{where}: title and at least one safety warning are required")
        if flow.start not in nodes:
            problems.append(f"{where}: start node {flow.start!r} does not exist")
        for node in nodes.values():
            if node.kind not in FLOW_KINDS:
                problems.append(f"{where} node {node.id}: kind must be one of {FLOW_KINDS}")
            if not node.prompt:
                problems.append(f"{where} node {node.id}: prompt is required")
            if node.kind == "question":
                if len(node.options) < 2:
                    problems.append(f"{where} node {node.id}: a question needs at least two options")
                for option in node.options:
                    if not option.label or option.next not in nodes:
                        problems.append(f"{where} node {node.id}: option {option.label!r} points at unknown node {option.next!r}")
            if node.next is not None and node.next not in nodes:
                problems.append(f"{where} node {node.id}: next points at unknown node {node.next!r}")
            if node.kind == "advice" and node.options:
                problems.append(f"{where} node {node.id}: advice nodes do not take options")
        flows.append(flow)
    flow_ids = {f.id for f in flows}
    if len(flow_ids) != len(flows):
        problems.append("flow ids must be unique")

    symptoms: list[Symptom] = []
    for raw in symptoms_doc.get("symptom", []):
        symptom = Symptom(
            id=str(raw.get("id", "")).strip(), title=str(raw.get("title", "")).strip(),
            aliases=_strings(raw.get("aliases")), flow=str(raw.get("flow", "")).strip(),
            firmware_entries=_strings(raw.get("firmware_entries")),
            summary=str(raw.get("summary", "")).strip(), first_checks=_strings(raw.get("first_checks")))
        where = f"symptom {symptom.id or '?'}"
        if not symptom.id or not symptom.title or not symptom.summary:
            problems.append(f"{where}: id, title and summary are required")
        if symptom.flow and symptom.flow not in flow_ids:
            problems.append(f"{where}: flow {symptom.flow!r} does not exist")
        for entry_id in symptom.firmware_entries:
            if entry_id not in entry_ids:
                problems.append(f"{where}: firmware entry {entry_id!r} does not exist")
        symptoms.append(symptom)

    printers: list[PrinterEntry] = []
    for raw in printers_doc.get("printer", []):
        bed = raw.get("bed_mm") or (0, 0)
        printer = PrinterEntry(
            key=str(raw.get("key", "")).strip(), label=str(raw.get("label", "")).strip(),
            vendor=str(raw.get("vendor", "")).strip(), firmware=str(raw.get("firmware", "")).strip(),
            firmware_family=str(raw.get("firmware_family", "")).strip(),
            connection=str(raw.get("connection", "")).strip(),
            kinematics=str(raw.get("kinematics", "")).strip(),
            bed_mm=(float(bed[0]), float(bed[1])), max_height_mm=float(raw.get("max_height_mm") or 0),
            filament_slots=int(raw.get("filament_slots") or 0), tools=int(raw.get("tools") or 0),
            profile=str(raw.get("profile", "")).strip(), notes=str(raw.get("notes", "")).strip())
        where = f"printer {printer.key or '?'}"
        if printer.firmware_family not in (*FIRMWARES, "none"):
            problems.append(f"{where}: firmware_family must be one of {FIRMWARES} or 'none'")
        if not printer.key or not printer.profile:
            problems.append(f"{where}: key and profile are required")
        if printer.key in {p.key for p in printers}:
            problems.append(f"{where}: key duplicated")
        printers.append(printer)
    printer_keys = {p.key for p in printers}
    for entry in entries:
        for key in entry.printers:
            if key != "*" and key not in printer_keys:
                problems.append(f"firmware entry {entry.id}: printer {key!r} is not in printers/registry.toml")

    if problems:
        raise RegistryError("invalid registries:\n- " + "\n- ".join(problems))
    return Registry(tuple(entries), tuple(symptoms), tuple(flows), tuple(printers))
