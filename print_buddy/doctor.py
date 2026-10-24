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

from . import settings, state_files

# Moonraker and Spoolman endpoints that answer without auth when the service is up.
SERVICE_PATHS = {"moonraker_url": "/printer/info", "spoolman_url": "/api/v1/health"}


def check_settings(data):
    printer = data["printer"]
    return (f"{printer['name']}, bed {printer['bed_mm'][0]:g}x{printer['bed_mm'][1]:g} mm, "
                  f"{printer['ifs_slots']} slot(s), {printer['nozzle_diameter_mm']:g} mm nozzle")


def check_model(data):
    from . import printers
    adapter = printers.get(data["printer"]["model"], data)
    kind = f"{adapter.slot_count} slots (multi-slot)" if adapter.multi_slot else "single extruder"
    return f"{adapter.key} ({adapter.label}), {kind}"


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


def check_strays(data):
    """Print Buddy state files outside the profile state folder. Returns a warning, or None."""
    strays = state_files.find_strays(data)
    if not strays:
        return None
    return (f"{len(strays)} outside {settings.state_dir(data)}: {state_files.describe(strays)} "
            "(python3 -m print_buddy.state_files --remove, or scripts/home-update.sh)")


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


def check_bot(data):
    """Which runtime talks to Discord, and for the standalone bot, where and for whom."""
    mode = data["bot"]["mode"]
    if mode != "standalone":
        return f"{mode} (the Hermes gateway runs the print-feedback plugin)"
    from .bot.runtime import allowed_users
    chat = data["discord"]["chat_id"]
    users = allowed_users(data)
    if not chat:
        raise RuntimeError("standalone, but discord.chat_id is empty")
    if not users:
        raise RuntimeError("standalone, but no allowed users: set discord.allowed_user_ids")
    return f"standalone, print channel {chat}, {len(users)} allowed user(s)"


def _bot_token(data):
    from .hermes import _config
    name = data["discord"]["token_env"]
    return _config.profile_env_value(name), name


def check_discord_login(data):
    """Standalone only: log in over REST with the bot token. Skipped in Hermes mode."""
    if data["bot"]["mode"] != "standalone":
        return None
    token, name = _bot_token(data)
    if not token:
        raise RuntimeError(f"${name} is empty; the standalone bot needs its Discord bot token there")
    from .bot import rest
    me = rest.whoami(token)
    return f"{me.get('username')} ({me.get('id')})"


def check_shared_token(data, hermes_root=None):
    """A warning when a Hermes profile holds the standalone bot's token: both would answer everything."""
    if data["bot"]["mode"] != "standalone":
        return None
    token, _name = _bot_token(data)
    if not token:
        return None
    root = Path(hermes_root) if hermes_root is not None else Path.home() / ".hermes"
    for env in [root / ".env", *sorted(root.glob("profiles/*/.env"))]:
        try:
            lines = env.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            if line.startswith("DISCORD_BOT_TOKEN=") and line.split("=", 1)[1].strip().strip("'\"") == token:
                return (f"the Hermes profile {env} holds this bot token. Stop that Hermes gateway: "
                        "one token runs one mode, or every message is answered twice")
    return None


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
    report("printer model", check_model, data)
    report("orca templates", check_templates, data)
    report("core", check_core, data)
    report("hardware record", check_hardware, data)
    report("orca cli", check_orca, data)
    for key in SERVICE_PATHS:
        report(key.replace("_url", ""), check_service, data, key)
    report("bot mode", check_bot, data)
    if data["bot"]["mode"] == "standalone":
        report("discord login", check_discord_login, data)
        try:
            shared = check_shared_token(data)
        except Exception as exc:
            shared = f"could not compare tokens: {exc}"
        print(f"WARN  bot token: {shared}" if shared else "ok    bot token: not shared with a Hermes profile", file=out)
    try:
        warning = check_strays(data)
    except Exception as exc:  # a scan problem is a warning, never a failed check
        warning = f"could not scan: {exc}"
    print(f"WARN  stray state files: {warning}" if warning else "ok    stray state files: none", file=out)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
