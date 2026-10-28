"""Prusa Orca profiles, generated on the operator's machine from their own OrcaSlicer installation.

The sibling of bambulab/profiles.py for Orca's `Prusa` vendor profiles (profiles/Prusa.json,
vendor profiles 02.04.00.03 in OrcaSlicer 2.4.2 and 02.04.00.17 in v2.5.0-alpha, whose installs
serve the same profiles packed as profiles/Prusa.opc): Print Handy ships no OrcaSlicer or Prusa profile content
(AGPL-3.0). It ships only the profile names and the SHA-256 identity of the vendor profiles it has
been checked against (the printer's `orca_identity` fact). The flattening/hashing pipeline itself is
shared with the Bambu implementation (bambulab.profiles.flatten/sha256, vendor="Prusa").

Two Prusa-specific differences from the BBL tree:
  - the machine profiles store start/end G-code as a *list of lines*; templates are written with
    those fields joined into the single string every other vendor uses (recorded in UPSTREAM copies
    unchanged, so the identity check still hashes the vendor's own form);
  - multi-tool machines (XL 5T) list the stock nozzle size once per toolhead; every entry must
    equal the stock size, where the BBL check expects exactly one entry.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

from ..bambulab import profiles as _shared
from ..bambulab.facts import SETTINGS_IDS
from . import facts

KINDS = _shared.KINDS
UPSTREAM = "upstream"
VENDOR = "Prusa"
# Print Handy's only changes to the flattened Prusa profiles, by kind: the start/end G-code
# list->string join in the machine template (template_text), and the settings IDs.
JOINED_GCODE_KEYS = ("machine_start_gcode", "machine_end_gcode", "time_lapse_gcode", "change_filament_gcode")


class ProfileError(RuntimeError):
    """The printer's Orca profiles are missing, unreadable or not the ones Print Handy was checked against."""


def install_hint(adapter):
    return (f"generate them from your own OrcaSlicer installation: python3 scripts/prusa-templates.py "
            f"--printer {adapter.model.printer_key} --resources <OrcaSlicer resources folder> "
            "(see docs/PRUSA.md)")


def _dump(data):
    head = [k for k in ("type", "name", "from", "instantiation") if k in data]
    return json.dumps({**{k: data[k] for k in head}, **{k: data[k] for k in sorted(data) if k not in head}},
                      indent=2, ensure_ascii=False) + "\n"


# The identity hash is the shared pipeline's, so a Prusa identity is computed exactly the way
# the Bambu identities pinned in bambulab/facts.py are.
sha256 = _shared.sha256


def template_text(kind, upstream):
    """The Orca template for one kind: the flattened vendor profile with the G-code join + settings ID."""
    data = dict(upstream)
    if kind == "machine":
        for key in JOINED_GCODE_KEYS:
            if isinstance(data.get(key), list):
                data[key] = "\n".join(str(line) for line in data[key])
    data[SETTINGS_IDS[kind]] = [data["name"]] if kind == "filament" else data["name"]
    return _dump(data)


def identity(adapter, hashes, version=None):
    """The expected identity these flattened profiles match (and, when given, their vendor version), or None."""
    for known in adapter.fact("orca_identity"):
        if known["sha256"] == hashes and (version is None or known["vendor_version"] == version):
            return known
    return None


def describe_problems(adapter, upstream):
    """Profile values that disagree with the printer's facts: a profile for another printer is refused."""
    machine, out = upstream["machine"], []
    if machine.get("printer_model") != adapter.fact("printer_model"):
        out.append(f"machine profile is for {machine.get('printer_model')!r}, not {adapter.fact('printer_model')!r}")
    (w, d), height = adapter.fact("bed_mm"), adapter.fact("max_print_height_mm")
    if machine.get("printable_area") != ["0x0", f"{w:g}x0", f"{w:g}x{d:g}", f"0x{d:g}"]:
        out.append(f"machine printable_area {machine.get('printable_area')} is not 0..{w:g} x 0..{d:g} mm")
    try:
        height_ok = math.isclose(float(machine.get("printable_height")), float(height), abs_tol=1e-6)
    except (TypeError, ValueError):
        height_ok = False
    if not height_ok:
        out.append(f"machine printable_height {machine.get('printable_height')} is not {height:g} mm")
    exclusion = adapter.facts["bed_exclude_area"].value if "bed_exclude_area" in adapter.facts else ()
    expected_exclusion = [f"{x:g}x{y:g}" for x, y in exclusion]
    found = machine.get("bed_exclude_area")
    # The XL profile writes ["0x0"] (a lone origin point) for no exclusion; treat it as empty.
    if found in (None, [], [""], ["0x0"]):
        found = []
    if list(found) != expected_exclusion:
        out.append(f"machine bed_exclude_area {machine.get('bed_exclude_area')} is not "
                   f"{expected_exclusion or 'empty'}")
    nozzle = machine.get("nozzle_diameter")
    sizes = [str(v) for v in (nozzle if isinstance(nozzle, list) else [nozzle])]
    if not sizes or any(s != f"{adapter.fact('stock_nozzle')[0]:g}" for s in sizes):
        out.append(f"machine nozzle_diameter {nozzle} is not {adapter.fact('stock_nozzle')[0]:g} mm per toolhead")
    return out


def install(adapter, resources, folder=None):
    """Generate the printer's Orca templates from an installed OrcaSlicer; return the identity it matched.

    Nothing is written unless the flattened vendor profiles match an expected identity and the
    printer's facts (the Bambu install contract).
    """
    folder = Path(folder or adapter.pinned_templates_folder())
    upstream, version = _shared.flatten(resources, adapter.fact("orca_profiles"), vendor=VENDOR)
    hashes = {kind: sha256(upstream[kind]) for kind in KINDS}
    known = identity(adapter, hashes, version)
    if known is None:
        raise ProfileError(f"the {VENDOR} profiles in {resources} (vendor version {version}) are not a version "
                           f"Print Handy has checked for the {adapter.label}: sha256 {hashes}. Nothing was written")
    problems = describe_problems(adapter, upstream)
    if problems:
        raise ProfileError("; ".join(problems) + ". Nothing was written")
    folder.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{folder.name}-", dir=folder.parent))
    try:
        (work / UPSTREAM).mkdir()
        for kind in KINDS:
            (work / UPSTREAM / f"{kind}.json").write_text(_dump(upstream[kind]))
            (work / f"{kind}.json").write_text(template_text(kind, upstream[kind]))
        (work / "SOURCE.json").write_text(json.dumps(
            {"resources": str(Path(resources).expanduser().resolve()), "vendor_version": version,
             "identity": known.get("label"), "sha256": hashes}, indent=2) + "\n")
        old = folder.with_name(f".{folder.name}-old")
        if folder.exists():
            shutil.rmtree(old, ignore_errors=True)
            os.replace(folder, old)
        os.replace(work, folder)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return known


def problems(adapter, folder=None):
    """Why the generated templates in folder must not be used; empty when they are the checked profiles."""
    folder = Path(folder or adapter.pinned_templates_folder())
    if not all((folder / UPSTREAM / f"{kind}.json").is_file() for kind in KINDS):
        return [f"{adapter.label} Orca profiles are not installed in {folder}; {install_hint(adapter)}"]
    try:
        upstream = {kind: json.loads((folder / UPSTREAM / f"{kind}.json").read_text()) for kind in KINDS}
        templates = {kind: (folder / f"{kind}.json").read_text() for kind in KINDS}
    except (OSError, ValueError) as exc:
        return [f"{adapter.label} Orca profiles in {folder} are unreadable ({exc}); {install_hint(adapter)}"]
    hashes = {kind: sha256(upstream[kind]) for kind in KINDS}
    if identity(adapter, hashes) is None:
        return [f"{adapter.label} Orca profiles in {folder} are not a version Print Handy has checked "
                f"(sha256 {hashes}); {install_hint(adapter)}"]
    out = [f"{folder / (kind + '.json')} is not the generated template (edited?); {install_hint(adapter)}"
           for kind in KINDS if templates[kind] != template_text(kind, upstream[kind])]
    return out + describe_problems(adapter, upstream)


def require(adapter, folder=None):
    """The verified template folder, or ProfileError."""
    found = problems(adapter, folder)
    if found:
        raise ProfileError("; ".join(found))
    return Path(folder or adapter.pinned_templates_folder())
