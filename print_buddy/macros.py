"""Live printer macro discovery from Moonraker (issue #291, stage 1).

Moonraker's ``GET /printer/objects/list`` returns one ``gcode_macro <NAME>``
object per macro defined in the printer's own Klipper config, so the printer —
not Print Buddy's registry — is the authority on which macros exist. This
module fetches that list through an injected transport, extracts the macro
names and classifies each one against the descriptive registry in
``firmware/commands.toml`` (loaded through print_buddy.knowledge):

- **known** — the name matches a registry macro entry: show its description
  and safety note.
- **printer-defined** — the printer defines it but the registry does not:
  listed by name only; no description is invented for it.
- **internal** — the name starts with ``_`` (the Klipper helper convention):
  separated from the operator list, never presented as an operator macro.

Stage 1 is read-only. The only request this module can make is the GET of
the objects list; there is no code path here that sends a macro or any other
command to a printer. Running a discovered macro is stage 2 and needs its
own confirmation design on issue #291.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

OBJECTS_LIST_PATH = "/printer/objects/list"
MACRO_PREFIX = "gcode_macro "

COULD_NOT_READ_TEXT = ("Could not read the printer's macros from Moonraker. "
                       "Nothing was sent to the printer.")
READ_ONLY_NOTE = ("Read-only: this list came from the printer itself. Print Buddy sent nothing but "
                  "the objects-list request, and running a macro from the bot is not available yet.")


class MacroError(RuntimeError):
    """The printer's macros could not be read. Nothing was sent when this is raised."""


@dataclass(frozen=True)
class MacroListing:
    """The discovered macros, classified. `known` pairs each name with its registry entry."""

    known: tuple = ()              # tuple[tuple[str, FirmwareEntry], ...]
    printer_defined: tuple = ()    # tuple[str, ...]
    internal: tuple = ()           # tuple[str, ...]

    @property
    def names(self):
        return tuple(name for name, _entry in self.known) + self.printer_defined + self.internal


def parse_macro_names(payload) -> list:
    """Macro names from a Moonraker objects-list response, in the printer's order.

    Accepts the shape Moonraker actually returns (``{"result": {"objects":
    [...]}}``), a bare ``{"result": [...]}`` and a plain list, so recorded
    responses replay unchanged. Anything else is malformed and raises
    MacroError rather than guessing.
    """
    objects = payload
    if isinstance(payload, dict):
        if "result" not in payload:
            raise MacroError("Moonraker's objects-list response had no result")
        objects = payload["result"]
        if isinstance(objects, dict):
            objects = objects.get("objects")
    if not isinstance(objects, list):
        raise MacroError("Moonraker's objects-list response was not a list of objects")
    names: list[str] = []
    for item in objects:
        if not isinstance(item, str):
            raise MacroError("Moonraker's objects-list response held a non-string object")
        if item.startswith(MACRO_PREFIX):
            name = item[len(MACRO_PREFIX):].strip()
            if name and name not in names:
                names.append(name)
    return names


def _registry_index(registry):
    """Case-insensitive name -> entry index over the registry's macro entries only.

    A macro entry is reachable by its registry name and by the macro name its
    command line starts with; a name written as several words (the IFS feed
    entry lists two macro names) indexes each word.
    """
    index = {}
    for entry in registry.firmware_entries:
        if entry.kind != "macro":
            continue
        keys = [token for token in re.split(r"[^A-Za-z0-9_]+", entry.name) if token]
        if entry.command:
            keys.append(entry.command.split()[0])
        for key in keys:
            index.setdefault(key.casefold(), entry)
    return index


def classify(names, registry=None) -> MacroListing:
    """Split discovered names into known / printer-defined / internal."""
    if registry is None:
        from . import knowledge
        registry = knowledge.default_registry()
    index = _registry_index(registry)
    known, printer_defined, internal = [], [], []
    for name in names:
        if name.startswith("_"):
            internal.append(name)
        elif name.casefold() in index:
            known.append((name, index[name.casefold()]))
        else:
            printer_defined.append(name)
    return MacroListing(tuple(known), tuple(printer_defined), tuple(internal))


def discover(transport, registry=None) -> MacroListing:
    """Fetch and classify the printer's macros through `transport`.

    `transport` is the spool_sync.moonraker client shape: a callable taking
    (method, path) and returning the parsed JSON body. The only call made is
    one GET of the objects list. Any transport failure or malformed response
    raises MacroError; nothing is sent in that case (or any other).
    """
    try:
        payload = transport("GET", OBJECTS_LIST_PATH)
    except MacroError:
        raise
    except Exception as exc:
        raise MacroError(f"the objects-list request failed: {exc}") from exc
    return classify(parse_macro_names(payload), registry=registry)


def not_moonraker_text(connection) -> str:
    """The plain answer for a printer with no Moonraker macro namespace."""
    where = f" (it uses the {connection} connection)" if connection else ""
    return ("Macros are a Moonraker/Klipper feature: the printer defines them in its own config "
            f"and Moonraker lists them. This printer has no Moonraker macro namespace{where}, so "
            "there is no macro list to read. Nothing was sent to the printer.")


def listing_text(listing: MacroListing) -> str:
    """The chat-ready Stage 1 answer for one discovered listing."""
    if not listing.names:
        return ("The printer reported no macros in its Moonraker objects list.\n" + READ_ONLY_NOTE)
    lines = ["**Macros on your printer** (read live from Moonraker):"]
    if listing.known:
        lines.append("\nKnown to Print Buddy:")
        for name, entry in listing.known:
            lines.append(f"- **{name}** — {entry.description}")
            lines.append(f"  Safety: {entry.safety}")
    if listing.printer_defined:
        lines.append("\nDefined by your printer's config (Print Buddy has no description for these):")
        lines += [f"- {name}" for name in listing.printer_defined]
    if listing.internal:
        lines.append("\nInternal helper macros (part of the printer's own config machinery, "
                     "not operator macros):")
        lines += [f"- {name}" for name in listing.internal]
    lines.append("\n" + READ_ONLY_NOTE)
    return "\n".join(lines)
