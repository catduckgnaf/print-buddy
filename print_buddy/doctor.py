"""Check that this machine can run Print Buddy: settings, templates, core, slicer, services.

    python3 -m print_buddy.doctor

Exits 1 when any check fails. Services and the slicer are skipped when local.toml does not set them.
"""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import settings

# Moonraker and Spoolman endpoints that answer without auth when the service is up.
SERVICE_PATHS = {"moonraker_url": "/printer/info", "spoolman_url": "/api/v1/health"}


def check_settings(data):
    printer = data["printer"]
    return (f"{printer['name']}, bed {printer['bed_mm'][0]:g}x{printer['bed_mm'][1]:g} mm, "
                  f"{printer['ifs_slots']} slot(s), {printer['nozzle_diameter_mm']:g} mm nozzle")


def check_family(data):
    from . import printers
    adapter = printers.get(data["printer"]["family"], data)
    kind = f"{adapter.slot_count} slots (multi-slot)" if adapter.multi_slot else "single extruder"
    return f"{adapter.family} ({adapter.label}), {kind}"


def check_templates(data):
    folder = data["orca"]["templates"]
    machine = None
    for name in ("machine", "process", "filament"):
        profile = json.loads((folder / f"{name}.json").read_text())
        machine = profile if name == "machine" else machine
    corners = [tuple(float(v) for v in c.split("x")) for c in machine["printable_area"]]
    area = [max(x for x, _ in corners) - min(x for x, _ in corners),
            max(y for _, y in corners) - min(y for _, y in corners)]
    if area != data["printer"]["bed_mm"]:
        raise RuntimeError(f"machine.json printable area {area} does not match settings bed_mm {data['printer']['bed_mm']}")
    return str(folder)


REQUIRED_HARDWARE = (("spool", "material", str), ("spool", "density", (int, float)),
                     ("temps_c", "nozzle", (int, float)), ("temps_c", "bed", (int, float)),
                     ("nozzle", "diameter_mm", (int, float)))


def check_hardware(data):
    """The printer hardware record the pipeline reads with no fallback. A fresh install has none."""
    path = settings.state_dir(data) / "printer_hardware.json"
    if not path.is_file():
        raise RuntimeError(f"{path} is missing; copy it from the working install or create it before slicing")
    record = json.loads(path.read_text())
    missing = [key for key in ("spool", "temps_c", "nozzle") if not isinstance(record.get(key), dict)]
    if missing:
        raise RuntimeError(f"{path} lacks {', '.join(missing)}")
    # The fields slicing reads directly; a section without them passes here but fails mid-slice.
    missing = [f"{section}.{key}" for section, key, kind in REQUIRED_HARDWARE
               if not isinstance(record[section].get(key), kind) or isinstance(record[section].get(key), bool)]
    if missing:
        raise RuntimeError(f"{path} lacks {', '.join(missing)}")
    nozzle = record["nozzle"].get("diameter_mm")
    if nozzle is None or float(nozzle) != data["printer"]["nozzle_diameter_mm"]:
        raise RuntimeError(f"recorded nozzle {nozzle} mm does not match settings {data['printer']['nozzle_diameter_mm']:g} mm")
    return f"{path.name}, {float(nozzle):g} mm nozzle"


def check_core(data):
    core = Path(__file__).resolve().parent / "core"
    names = sorted(p.stem for p in core.glob("*.py") if p.stem != "__init__")
    for name in names:
        importlib.import_module(f"print_buddy.core.{name}")
    return f"{len(names)} modules import"


def check_orca(data):
    command = data["orca"]["command"]
    if not shutil.which(command[0]):
        raise RuntimeError(f"{command[0]} is not on PATH")
    run = subprocess.run([*command, "--help"], capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} --help exited {run.returncode}")
    return " ".join(command)


def check_service(data, key):
    url = data.get("services", {}).get(key)
    if not url:
        return None
    with urllib.request.urlopen(url.rstrip("/") + SERVICE_PATHS[key], timeout=5) as resp:
        if resp.status != 200:
            raise RuntimeError(f"{url} answered {resp.status}")
    return url


def run(out=sys.stdout):
    failed = False

    def report(label, func, *args):
        nonlocal failed
        try:
            detail = func(*args)
        except Exception as exc:  # every failure is reported, none stops the other checks
            failed = True
            print(f"FAIL  {label}: {exc}", file=out)
            return None
        print(f"{'ok' if detail is not None else 'skip':<5} {label}" + (f": {detail}" if detail else " (not set in local.toml)"), file=out)
        return detail

    try:
        data = settings.load()
    except settings.SettingsError as exc:
        print(f"FAIL  settings: {exc}", file=out)
        return 1
    report("settings", check_settings, data)
    report("printer family", check_family, data)
    report("orca templates", check_templates, data)
    report("core", check_core, data)
    report("hardware record", check_hardware, data)
    report("orca cli", check_orca, data)
    for key in SERVICE_PATHS:
        report(key.replace("_url", ""), check_service, data, key)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
