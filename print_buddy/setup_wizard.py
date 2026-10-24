"""Interactive setup for the Print Buddy light install (Raspberry Pi or Debian/Ubuntu, no Docker).

    python3 -m print_buddy.setup_wizard [--answers FILE] [--dry-run] [--yes]

Asks brand then model (or Other / generic), connection, nozzle, filament, slicer, Spoolman, camera and
timelapse, missing printer software, Discord and whether you run Hermes Agent. Shows a summary, then writes
config/local.yaml (existing keys always win; you see a diff first) and the secrets to the data folder's .env
(mode 600). Secrets are never printed.

Menus come from the printer registry, so a new printer model shows up here without editing this file.
Every question can be answered ahead of time with --answers (YAML or KEY=value) for an unattended install.
"""
from __future__ import annotations

import argparse
import difflib
import io
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/catduckgnaf/print-buddy"
FLATPAK = {"orca": "com.orcaslicer.OrcaSlicer", "bambu_studio": "com.bambulab.BambuStudio"}
SLICER_LABEL = {"orca": "OrcaSlicer", "bambu_studio": "Bambu Studio"}
MATERIALS = ("PLA", "PETG", "ABS", "ASA", "TPU", "PA", "PC")
OTHER = "other"
# Bot permissions the code uses (docs/STANDALONE.md "Discord setup"). Values are Discord permission bits.
DISCORD_PERMISSIONS = {
    "View Channels": 1 << 10,
    "Send Messages": 1 << 11,
    "Embed Links": 1 << 14,
    "Attach Files": 1 << 15,
    "Read Message History": 1 << 16,
    "Send Messages in Threads": 1 << 38,
}
KIAUH = ["bash", "-c", "git clone https://github.com/dw-0/kiauh.git ~/kiauh && ~/kiauh/kiauh.sh"]
OCTOPRINT = ["bash", "-c", "python3 -m venv ~/OctoPrint/venv && ~/OctoPrint/venv/bin/pip install OctoPrint"]
SPOOLMAN = ["bash", "-c", "mkdir -p ~/Spoolman && cd ~/Spoolman && "
            "curl -fsSL -o spoolman.zip https://github.com/Donkie/Spoolman/releases/latest/download/spoolman.zip && "
            "unzip -oq spoolman.zip && rm spoolman.zip && bash scripts/install.sh"]


def discord_permissions():
    return dict(DISCORD_PERMISSIONS)


def discord_invite_url(client_id):
    perms = sum(DISCORD_PERMISSIONS.values())
    return (f"https://discord.com/oauth2/authorize?client_id={client_id or '<APPLICATION_ID>'}"
            f"&scope=bot+applications.commands&permissions={perms}")


DISCORD_STEPS = """\
Discord bot setup (full guide: docs/DISCORD-BOT-SETUP.md)
  1. https://discord.com/developers/applications > New Application > Bot > Reset Token. Copy the token.
  2. Bot > Privileged Gateway Intents: turn on MESSAGE CONTENT. Nothing else is needed.
  3. Copy the Application ID from General Information; the invite link is printed next.
  4. Discord User Settings > Advanced > Developer Mode on. Right-click the print channel > Copy Channel ID,
     right-click yourself > Copy User ID."""


def parse_answers(path):
    """Read an answers file: a flat YAML mapping (key: value) or KEY=value lines."""
    if not path:
        return {}
    values = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        sep = "=" if "=" in line and (":" not in line or line.index("=") < line.index(":")) else ":"
        if sep not in line:
            continue
        key, value = line.split(sep, 1)
        values[key.strip().lower()] = value.strip().strip("\"'")
    return values


class Wizard:
    """Question helper: answers file, then PB_<KEY> environment, then the terminal."""

    def __init__(self, answers=None, input_stream=None, output=None, yes=False, environ=None):
        self.answers = dict(answers or {})
        self.input = input_stream if input_stream is not None else io.StringIO("")
        self.output = output or sys.stdout
        self.yes = yes
        self.environ = os.environ if environ is None else environ
        self.choices = {}

    def say(self, text=""):
        print(text, file=self.output, flush=True)

    def _preset(self, key):
        if key in self.answers:
            return str(self.answers[key])
        return self.environ.get("PB_" + key.upper())

    def _read(self):
        line = self.input.readline()
        return line.rstrip("\r\n").strip()

    def ask(self, key, prompt, default="", validate=None):
        preset = self._preset(key)
        while True:
            if preset is not None:
                value = preset
                self.say(f"{prompt}: {value}")
            elif self.yes:
                value = default
                self.say(f"{prompt}: {value}")
            else:
                print(f"{prompt}" + (f" [{default}]" if default else "") + ": ", end="", file=self.output, flush=True)
                value = self._read() or default
            error = validate(value) if validate else None
            if not error:
                self.choices[key] = value
                return value
            if preset is not None or self.yes:
                raise SystemExit(f"setup: {key}: {error}")
            self.say(f"  {error}")

    def confirm(self, key, prompt, default=True):
        hint = "Y/n" if default else "y/N"
        value = self.ask(key, f"{prompt} [{hint}]", "yes" if default else "no")
        return value.strip().lower() in ("y", "yes", "true", "1")

    def secret(self, key, prompt):
        preset = self._preset(key)
        if preset is not None:
            value = preset
        elif self.yes:
            value = ""
        else:
            print(f"{prompt} (hidden, Enter to skip): ", end="", file=self.output, flush=True)
            if hasattr(self.input, "fileno") and _isatty(self.input):
                import getpass
                value = getpass.getpass("", stream=self.output)
            else:
                value = self._read()
        self.say(f"{prompt}: {'(set)' if value else '(not set)'}")
        return value.strip()

    def menu(self, key, prompt, options, default, labels=None):
        """options are internal values; the user picks by number or by value."""
        labels = labels or options
        preset = self._preset(key)
        self.say(prompt)
        for i, label in enumerate(labels, 1):
            mark = "  (default)" if options[i - 1] == default else ""
            self.say(f"  {i}. {label}{mark}")
        while True:
            if preset is not None:
                raw = preset
            elif self.yes:
                raw = default
            else:
                print(f"Number [{options.index(default) + 1}]: ", end="", file=self.output, flush=True)
                raw = self._read() or default
            value = _pick(raw, options)
            if value is not None:
                self.choices[key] = value
                if preset is not None or self.yes:
                    self.say(f"  -> {labels[options.index(value)]}")
                return value
            if preset is not None or self.yes:
                raise SystemExit(f"setup: {key}: {raw!r} is not one of {', '.join(options)}")
            self.say(f"  Pick 1 to {len(options)}.")


def _isatty(stream):
    try:
        return os.isatty(stream.fileno())
    except (OSError, ValueError, io.UnsupportedOperation):
        return False


def _pick(raw, options):
    raw = str(raw).strip()
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    lowered = {o.lower(): o for o in options}
    return lowered.get(raw.lower())


def _url(value):
    if value and not re.match(r"^https?://[^\s/]+", value):
        return "must start with http:// or https://"
    return None


def _ids(value):
    if value and not all(p.isdigit() for p in re.split(r"[,\s]+", value.strip()) if p):
        return "Discord IDs are numbers (Developer Mode > Copy ID); separate several with commas"
    return None


def _positive(value):
    try:
        if float(value) > 0:
            return None
    except ValueError:
        pass
    return "must be a positive number"


def profile_name_error(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", value or ""):
        return "lowercase letters, digits, - or _, starting with a letter or digit"
    return None


def registry():
    from . import printers
    return printers.VENDORS, printers.MODELS


def choose_printer(w):
    """Brand, then model (or Other / generic). Returns (model key, printer overrides, display name)."""
    vendors, models = registry()
    brands = list(vendors) + [OTHER]
    brand = w.menu("brand", "Printer brand:", brands, brands[0],
                   [vendors[k].label for k in vendors] + ["Other / generic"])
    generic = brand == OTHER
    if not generic:
        keys = [k for k in models if k.startswith(brand + ".")]
        options = keys + [OTHER]
        labels = [getattr(models[k], "label", "") or models[k].key.split(".", 1)[1].upper() for k in keys]
        labels.append(f"Other / generic {vendors[brand].label}")
        picked = w.menu("model", f"{vendors[brand].label} model:", options, keys[0] if keys else OTHER, labels)
        generic = picked == OTHER
        if not generic:
            model = models[picked]
            label = labels[keys.index(picked)]
            vendor_label = vendors[brand].label
            return picked, {}, label if label.lower().startswith(vendor_label.lower()) else f"{vendor_label} {label}"
    # Other / generic: pick the firmware family, then describe the machine.
    families = [("klipper", "klipper.generic"), ("octoprint", "octoprint.marlin"), ("bambulab", "bambulab.a1")]
    families = [(f, m) for f, m in families if m in models]
    family = w.menu("firmware", "Printer firmware:", [f for f, _ in families], families[0][0],
                    ["Klipper (Moonraker)", "Marlin with OctoPrint", "Bambu Lab (offline: slice and check only)"][:len(families)])
    key = dict(families)[family]
    name = w.ask("printer_name", "Printer name (for messages)",
                 vendors[brand].label + " printer" if brand != OTHER else "My printer")
    defaults = models[key].defaults()["printer"]
    x = float(w.ask("bed_x", "Bed size X (mm)", f"{defaults['bed_mm'][0]:g}", _positive))
    y = float(w.ask("bed_y", "Bed size Y (mm)", f"{defaults['bed_mm'][1]:g}", _positive))
    z = float(w.ask("bed_z", "Max print height (mm)", f"{defaults['max_print_height_mm']:g}", _positive))
    return key, {"bed_mm": [x, y], "max_print_height_mm": z, "name": name}, name


def build_plan(w, *, hermes_found=False, existing_profiles=()):
    """Ask every question. Returns a plan dict; nothing is written or run here."""
    vendors, models = registry()
    key, printer, display = choose_printer(w)
    model = models[key]
    vendor = model.vendor
    printer = {"model": key, **printer}
    services, notes, actions = {}, [], []

    # Connection
    connection = vendor.connection
    if connection == "offline":
        notes.append(f"{vendor.label}: no live printer connection. Print Buddy slices, checks G-code and "
                     "packages the file; you start the print yourself.")
    has_software = True
    if connection == "moonraker":
        has_software = w.confirm("has_printer_software", "Is Klipper with Moonraker already running on the printer?")
        services["moonraker_url"] = w.ask("moonraker_url", "Moonraker URL", "http://printer.local:7125", _url)
        if not has_software:
            actions.append(("Install Klipper, Moonraker and Mainsail with KIAUH (official, menu-driven)", KIAUH))
    elif connection == "octoprint":
        has_software = w.confirm("has_printer_software", "Is OctoPrint already running?")
        services["octoprint_url"] = w.ask("octoprint_url", "OctoPrint URL", "http://octopi.local", _url)
        if not has_software:
            actions.append(("Install OctoPrint into ~/OctoPrint/venv (official pip install)", OCTOPRINT))
    octoprint_key = w.secret("octoprint_api_key", "OctoPrint API key") if connection == "octoprint" else ""

    # Nozzle and filament
    sizes = [f"{s:g}" for s in model.supported_nozzle_sizes]
    size = w.menu("nozzle_diameter_mm", "Nozzle size (mm):", sizes, "0.4" if "0.4" in sizes else sizes[0])
    printer["nozzle_diameter_mm"] = float(size)
    types = list(model.supported_nozzle_types)
    printer["nozzle_type"] = w.menu("nozzle_type", "Nozzle material:", types, types[0],
                                    [t.replace("_", " ") for t in types])
    material = w.menu("material", "Main filament:", list(MATERIALS), "PLA")

    # Slicer: Bambu Lab uses Bambu Studio, everything else OrcaSlicer.
    slicers = list(vendor.slicers)
    slicer = slicers[0]
    if len(slicers) > 1:
        slicer = w.menu("slicer", "Slicer:", slicers, slicers[0], [SLICER_LABEL[s] for s in slicers])
    printer["slicer"] = slicer
    install_slicer = w.confirm("install_slicer", f"Install {SLICER_LABEL[slicer]} from Flathub if missing?")
    flatpaks = [FLATPAK[slicer]] if install_slicer else []

    # Spoolman
    spool = w.menu("spoolman", "Spoolman (filament inventory):", ["skip", "existing", "install"], "skip",
                   ["Skip", "I already run Spoolman", "Install Spoolman on this machine (official installer)"])
    if spool == "existing":
        services["spoolman_url"] = w.ask("spoolman_url", "Spoolman URL", "http://spoolman.local:7912", _url)
    elif spool == "install":
        services["spoolman_url"] = "http://localhost:7912"
        actions.append(("Install Spoolman into ~/Spoolman (official release and scripts/install.sh)", SPOOLMAN))

    # Camera and timelapse
    if w.confirm("camera", "Do you have a printer camera?", default=False):
        default_cam = ""
        if services.get("moonraker_url"):
            host = services["moonraker_url"].split("://", 1)[1].split("/", 1)[0].rsplit(":", 1)[0]
            default_cam = f"http://{host}/webcam/?action=snapshot"
        cam = w.ask("camera_snapshot_url", "Camera snapshot URL", default_cam, _url)
        if cam:
            services["camera_snapshot_url"] = cam
        if connection == "moonraker" and w.confirm("timelapse", "Post timelapse videos after prints?", default=False):
            notes.append("Timelapse needs moonraker-timelapse on the printer (KIAUH > Install > Timelapse). "
                         "Print Buddy posts the finished video; archiving is optional (timelapse.* settings).")

    # Discord
    w.say()
    if not w.confirm("have_bot", "Do you already have a Discord bot token?", default=False):
        w.say(DISCORD_STEPS)
    client_id = w.ask("discord_app_id", "Discord Application ID (for the invite link, optional)", "", _ids)
    w.say(f"Invite link: {discord_invite_url(client_id)}")
    chat_id = w.ask("discord_chat_id", "Print channel ID", "", _ids)
    users = w.ask("discord_user_ids", "Discord user IDs allowed to print (comma separated)", "", _ids)
    bot_name = w.ask("bot_name", "Bot name", "Print Buddy")
    token = w.secret("discord_bot_token", "Discord bot token")

    # Hermes or standalone
    w.say()
    w.say("Print Buddy runs either as its own Discord bot (standalone) or as a Hermes Agent profile.")
    hermes = w.confirm("hermes", "Do you use Hermes Agent?" + (" (found on this machine)" if hermes_found else ""),
                       default=hermes_found)
    profile = ""
    if hermes:
        profile = w.ask("profile", "Hermes profile name", "3dprinting", profile_name_error)
    timezone = detect_timezone()
    discord = {"chat_id": chat_id, "allowed_user_ids": users, "bot_name": bot_name, "timezone": timezone}
    data_home = f"~/.hermes/profiles/{profile}" if hermes else "~/.local/share/print-buddy"
    config = {
        "printer": printer,
        "services": services,
        "discord": {k: v for k, v in discord.items() if v},
        "bot": {"mode": "hermes" if hermes else "standalone"},
        "paths": {"hermes_home": data_home},
    }
    return {
        "config": config, "display": display, "material": material, "slicer": slicer, "flatpaks": flatpaks,
        "actions": actions, "notes": notes, "hermes": hermes, "profile": profile,
        "profile_exists": profile in existing_profiles, "data_home": data_home, "timezone": timezone,
        "secrets": {"DISCORD_BOT_TOKEN": token, "OCTOPRINT_API_KEY": octoprint_key},
        "hermes_env": {"DISCORD_ALLOWED_USERS": users.replace(" ", ""), "DISCORD_HOME_CHANNEL": chat_id},
        "spoolman": spool,
    }


def detect_timezone():
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        if out:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return Path("/etc/timezone").read_text().strip() or "UTC"
    except OSError:
        return "UTC"


def build_hermes_commands(profile, display, repo, python, *, channel_id="", bot_name="Print Buddy",
                          timezone="UTC", display_name="3D Printing", profile_exists=False):
    """Commands that set up a Hermes profile for Print Buddy. Never clones another profile."""
    commands = []
    if not profile_exists:
        commands.append(["hermes", "profile", "create", profile, "--description",
                         f"Print Buddy 3D printer specialist: slicing, printing, and printer status for {display}"])
    env = {"DISCORD_CHANNEL_ID": channel_id, "BOT_NAME": bot_name, "TIMEZONE": timezone,
           "DISPLAY_NAME": display_name}
    commands.append(["env", *(f"{k}={v}" for k, v in env.items() if v), f"{repo}/scripts/install-hermes.sh",
                     "--hermes-home", str(Path.home() / ".hermes" / "profiles" / profile), "--python", str(python)])
    return commands


def show(cmd):
    return " ".join(shlex.quote(c) for c in cmd)


def hermes_profiles(env=None, which=shutil.which):
    """Profile names from `hermes profile list` (the name in parentheses, else the first column)."""
    path = (env or os.environ).get("PATH")
    exe = which("hermes", path=path)
    if not exe:
        return set()
    try:
        out = subprocess.run([exe, "profile", "list"], capture_output=True, text=True, timeout=30, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    names = set(re.findall(r"\(([a-z0-9][a-z0-9_-]*)\)", out))
    return names


def summary(plan):
    c = plan["config"]
    p = c["printer"]
    lines = [
        "Summary",
        f"  Printer:     {plan['display']} ({p['model']}), nozzle {p['nozzle_diameter_mm']:g} mm "
        f"{p['nozzle_type'].replace('_', ' ')}, main filament {plan['material']}",
        f"  Slicer:      {SLICER_LABEL[plan['slicer']]}" + (" (install from Flathub)" if plan["flatpaks"] else ""),
        f"  Services:    " + (", ".join(f"{k}={v}" for k, v in c["services"].items()) or "none"),
        f"  Discord:     channel {c['discord'].get('chat_id') or '(not set)'}, "
        f"users {c['discord'].get('allowed_user_ids') or '(not set)'}, "
        f"token {'set' if plan['secrets']['DISCORD_BOT_TOKEN'] else 'not set'}",
        f"  Runs as:     " + (f"Hermes profile '{plan['profile']}'" + (" (exists, reused)" if plan["profile_exists"] else "")
                             if plan["hermes"] else "standalone bot (systemd user services)"),
        f"  Data folder: {plan['data_home']} (state, logs, .env with secrets)",
    ]
    for label, cmd in plan["actions"]:
        lines.append(f"  Install:     {label}")
    lines += [f"  Note:        {n}" for n in plan["notes"]]
    return "\n".join(lines)


def _dump(data):
    import yaml
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=None)


def _merge_missing(existing, proposed):
    out = dict(existing)
    for key, value in proposed.items():
        if key not in out:
            out[key] = value
        elif isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge_missing(out[key], value)
    return out


def merge_config(target, new, w, dry_run=False):
    """Write config/local.yaml. Existing keys always win; an existing file changes only after a yes."""
    target = Path(target)
    header = "# Written by the Print Buddy setup wizard. Edit freely; re-running the wizard keeps your values.\n"
    if not target.exists():
        text = header + _dump(new)
        if dry_run:
            w.say(f"would write {target}:\n{text}")
            return True
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, text, 0o644)
        w.say(f"wrote {target}")
        return True
    import yaml
    old_text = target.read_text(encoding="utf-8")
    merged = _merge_missing(yaml.safe_load(old_text) or {}, new)
    new_text = _dump(merged)
    if (yaml.safe_load(old_text) or {}) == merged:
        w.say(f"{target} already has every setting; left unchanged.")
        return True
    w.say("".join(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                                       str(target), "with new settings")))
    if dry_run:
        return True
    if not w.confirm("merge_config", f"Add the missing settings to {target.name}? (comments are not kept)", default=False):
        w.say(f"{target} left unchanged.")
        return False
    _atomic_write(target, header + new_text, 0o644)
    return True


def _atomic_write(path, text, mode):
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def update_env(folder, values):
    """Add KEY=value lines that are missing or empty. Existing values are kept. Mode 600."""
    folder = Path(folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    env = folder / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else ["# Print Buddy secrets"]
    present = {l.split("=", 1)[0]: i for i, l in enumerate(lines) if "=" in l and not l.startswith("#")}
    changed = []
    for key, value in values.items():
        if not value:
            continue
        if key in present:
            if lines[present[key]].split("=", 1)[1].strip():
                continue
            lines[present[key]] = f"{key}={value}"
        else:
            lines.append(f"{key}={value}")
        changed.append(key)
    if changed or not env.exists():
        _atomic_write(env, "\n".join(lines) + "\n", 0o600)
    else:
        env.chmod(0o600)
    return changed


def apply(plan, w, *, repo=REPO, python=None, dry_run=False, runner=subprocess.run, local=None):
    """Write config and secrets, then run the installs the user agreed to."""
    python = python or sys.executable
    local = Path(local) if local else repo / "config" / "local.yaml"
    if not merge_config(local, plan["config"], w, dry_run):
        w.say("Continuing with your existing config/local.yaml.")

    def run(label, cmd, ask=True, key=None):
        w.say(f"\n{label}:\n  $ {show(cmd)}")
        if dry_run:
            return True
        if ask and not w.confirm(key or "run", "Run this now?"):
            w.say("  Skipped. You can run it later.")
            return False
        result = runner(cmd)
        if getattr(result, "returncode", 0) != 0:
            w.say(f"  Failed with exit code {result.returncode}. Fix the cause and re-run the wizard.")
            return False
        return True

    for app in plan["flatpaks"]:
        run(f"Install {app} from Flathub (skipped automatically if already installed)",
            ["bash", "-c", f"flatpak info {app} >/dev/null 2>&1 || flatpak install --user -y --noninteractive flathub {app}"],
            ask=False)
    for label, cmd in plan["actions"]:
        run(label, cmd, key="run_" + label.split()[1].lower())

    secrets = {k: v for k, v in plan["secrets"].items() if v}
    if plan["hermes"]:
        name = plan["profile"]
        cmds = build_hermes_commands(name, plan["display"], repo, python,
                                     channel_id=plan["config"]["discord"].get("chat_id", ""),
                                     bot_name=plan["config"]["discord"].get("bot_name", "Print Buddy"),
                                     timezone=plan["timezone"], profile_exists=plan["profile_exists"])
        if plan["profile_exists"]:
            w.say(f"\nHermes profile '{name}' already exists; it is reused, not recreated.")
        w.say("The standalone bot services are not installed in Hermes mode: two bots on one token collide.")
        ok = True
        for cmd in cmds:
            ok = ok and run("Hermes setup", cmd, key="run_hermes")
        home = Path.home() / ".hermes" / "profiles" / name
        if ok and not dry_run:
            changed = update_env(home, {**secrets, **{k: v for k, v in plan["hermes_env"].items() if v}})
            w.say(f"Saved {', '.join(changed) or 'nothing new'} to {home}/.env (values not shown).")
        w.say(f"\nNext:\n  1. hermes -p {name} setup        # pick the model and API key for this profile"
              f"\n  2. hermes gateway restart        # or: hermes -p {name} gateway install --if-missing --start-now"
              f"\n  3. In Discord, @mention the bot in the print channel: \"status\"")
    else:
        run("Install the standalone bot services (enables nothing yet)",
            [str(repo / "scripts" / "install-standalone.sh"), "--python", str(python)], ask=False)
        if not dry_run:
            changed = update_env(plan["data_home"], secrets)
            w.say(f"Saved {', '.join(changed) or 'nothing new'} to {plan['data_home']}/.env (values not shown).")
        user = os.environ.get("USER") or "$USER"
        run("Keep the bot running after you log out", ["loginctl", "enable-linger", user], key="run_linger")
        run("Start the bot now", ["systemctl", "--user", "enable", "--now",
                                  "print-buddy-bot.service", "print-buddy-listener.service"], key="run_start")
        w.say(f"\nCheck it: {python} -m print_buddy.bot check")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Print Buddy setup wizard")
    ap.add_argument("--answers", help="answers file (YAML or KEY=value); unanswered questions are asked")
    ap.add_argument("--dry-run", action="store_true", help="ask, show what would happen, change nothing")
    ap.add_argument("--yes", action="store_true", help="take defaults for unanswered questions and confirmations")
    ap.add_argument("--python", help="Python the services run with (default: this one)")
    args = ap.parse_args(argv)
    stream = sys.stdin
    if not _isatty(sys.stdin):
        try:
            stream = open("/dev/tty", encoding="utf-8")
        except OSError:
            stream = io.StringIO("")
    w = Wizard(parse_answers(args.answers), stream, sys.stdout, args.yes)
    w.say("Print Buddy setup. Press Enter to take the default in [brackets].\n")
    found = bool(shutil.which("hermes")) or (Path.home() / ".hermes" / "hermes-agent").is_dir()
    plan = build_plan(w, hermes_found=found, existing_profiles=hermes_profiles() if found else ())
    w.say("\n" + summary(plan))
    if not args.dry_run and not w.confirm("apply", "\nApply these settings?"):
        w.say("Nothing was changed.")
        return 1
    apply(plan, w, python=args.python, dry_run=args.dry_run)
    w.say("\nDone." if not args.dry_run else "\nDry run: nothing was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
