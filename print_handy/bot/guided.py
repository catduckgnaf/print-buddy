"""Guided setup and read-only debugging for ``/print-handy`` (#162).

Two flows, both driven by plain Discord messages so the standalone bot and the Hermes
print-feedback plugin share one implementation:

- ``/print-handy setup`` walks a fresh install through small validated steps. Progress is a
  checklist persisted as JSON in the state folder, so cancelling, a timeout, or a bot restart
  resumes where the person left off. Nothing is written to the real configuration until the
  person explicitly replies ``apply`` at the review step; ``manual`` returns precise steps
  instead. The Discord bot token is never collected in chat: the token step only explains
  where to store it (the environment variable named by ``[discord] token_env``, in the
  profile/data folder ``.env`` with mode 600) and records that it was stored.
- ``/print-handy debugging`` runs read-only diagnostics: configuration validity, bot mode and
  Discord login readiness, channel/user permission prerequisites, service connectivity (GET
  probes only), required executables and versions, and state/log locations. It never calls a
  printer operation, never edits configuration, and never restarts anything. Every line of
  output passes through :func:`redact`, which removes secret values, private filesystem
  paths, and long numeric identifiers.

Printer operations and print authorization are deliberately out of scope for both flows.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .. import printers, settings

STORE_NAME = "guided-setup.json"
# A saved checklist survives this long. After it, a plain reply is not consumed as an answer;
# ``/print-handy setup`` resumes the saved answers and says the session had timed out.
SESSION_TIMEOUT_S = 24 * 3600

HELP = """**Print Handy setup and debugging** — neither flow prints, moves, or authorizes a printer.
- `/print-handy setup`: guided setup in small steps. Your checklist is saved, so you can stop and resume later. At the review step, reply `add` to set up more printers — each gets its own channel and state folder.
- `/print-handy debugging`: read-only checks (configuration, bot login, permissions, connectivity, executables, state and logs). Secrets and private paths are redacted.
- `/print-handy bundle`: write a redacted diagnostics bundle (versions, configuration summary, doctor output, recent log tail) into the state folder, ready to attach to a bug report. Nothing is uploaded.
- `/print-handy status`: show the saved setup checklist.
- `/print-handy cancel`: pause setup; the saved checklist is kept for resuming.
While setup is waiting for an answer, reply with the answer as a plain message."""


# ---------------------------------------------------------------------- redaction

_TOKEN_SHAPE = re.compile(r"\b[MN][A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}\b")
_SECRET_PAIR = re.compile(r"(?i)\b(token|password|passwd|secret|api[_-]?key|access[_-]?code)\b\s*[:=]\s*\S+")
_LONG_ID = re.compile(r"\b\d{17,20}\b")
_ABS_PATH = re.compile(r"(?<![:/\w])/(?:[\w.~-]+/)+[\w.~-]*")


def redact(text, *, secrets=(), roots=()):
    """Remove secret values, private paths, and long numeric identifiers from ``text``."""
    out = str(text or "")
    for secret in secrets:
        secret = str(secret or "")
        if len(secret) >= 4:
            out = out.replace(secret, "[redacted]")
    for root in roots:
        root = str(root or "")
        if len(root) > 1:
            out = out.replace(root, "<local path>")
    out = _TOKEN_SHAPE.sub("[redacted]", out)
    out = _SECRET_PAIR.sub(lambda m: f"{m.group(1)}=[redacted]", out)
    out = _LONG_ID.sub(lambda m: "…" + m.group(0)[-2:], out)
    out = _ABS_PATH.sub("<local path>", out)
    return out


def _env_secrets(environ):
    env = os.environ if environ is None else environ
    return [v for k, v in env.items()
            if any(word in k.upper() for word in ("TOKEN", "PASSWORD", "SECRET", "API_KEY")) and v]


# ---------------------------------------------------------------------- setup steps

def _validate_model(value, _answers):
    key = value.strip()
    if key not in printers.MODELS:
        raise ValueError(f"unknown model key {key!r}; reply with one of: {', '.join(sorted(printers.MODELS))}")
    return key


def _validate_mode(value, _answers):
    mode = value.strip().lower()
    if mode not in settings.BOT_MODES:
        raise ValueError("reply `standalone` (Print Handy runs its own bot) or `hermes` (a Hermes Agent profile)")
    return mode


def _one_id(value, label):
    from ..setup_wizard import _ids
    error = _ids(value)
    if error:
        raise ValueError(error)
    parts = [p for p in re.split(r"[,\s]+", value.strip()) if p]
    if len(parts) != 1:
        raise ValueError(f"reply with exactly one numeric {label} ID")
    return parts[0]


def _validate_chat_id(value, _answers):
    return _one_id(value, "channel")


def _validate_user_ids(value, _answers):
    from ..setup_wizard import _ids
    if value.strip().casefold() in ("everyone", "anyone", "all"):
        return ""  # channel mode (#386): the print channel is the access boundary
    error = _ids(value)
    if error:
        raise ValueError(error)
    if not value.strip():
        raise ValueError("reply with user IDs, or `everyone` to let anyone in the print channel use the bot")
    return value.strip()


def _validate_service_url(value, answers):
    text = value.strip()
    if text.lower() in ("", "skip", "none"):
        return ""
    model = printers.MODELS.get(answers.get("model"))
    if model is not None and model.vendor.connection in ("offline", "bambulab_lan", "flashforge_stock", "prusalink", "elegoo_sdcp"):
        raise ValueError("this printer model has no Moonraker connection (Print Handy would refuse the "
                         "setting); reply `skip`")
    from ..setup_wizard import _url
    error = _url(text)
    if error:
        raise ValueError(f"Moonraker URL {error}, or reply `skip`")
    return text


def _validate_spoolman_url(value, _answers):
    text = value.strip()
    if text.lower() in ("", "skip", "none"):
        return ""
    # Spoolman is printer-independent (unlike Moonraker above): every model can use it,
    # so there is no model-connection refusal here.
    from ..setup_wizard import _url
    error = _url(text)
    if error:
        raise ValueError(f"Spoolman URL {error}, or reply `skip`")
    return text


def _validate_token_ack(value, _answers):
    text = value.strip().lower()
    if text == "stored":
        return True
    if text == "skip":
        return False
    raise ValueError("reply `stored` once the token is saved in that environment variable, or `skip` to "
                     "do it later. Never paste the token here: it is not collected in chat.")


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    prompt: str
    validate: object  # callable(value, answers) -> stored value, raising ValueError


def steps(token_env="DISCORD_BOT_TOKEN"):
    model_list = ", ".join(sorted(printers.MODELS))
    return (
        Step("model", "Printer model",
             f"Which printer? Reply with its model key, one of: {model_list}.", _validate_model),
        Step("mode", "Bot mode",
             "How should Print Handy talk to Discord? Reply `standalone` for its own bot, or "
             "`hermes` for a Hermes Agent profile.", _validate_mode),
        Step("chat_id", "Print channel",
             "Reply with the print channel's numeric ID. In Discord: User Settings > Advanced > "
             "Developer Mode on, then right-click the channel > Copy Channel ID.", _validate_chat_id),
        Step("user_ids", "Allowed users",
             "Reply with the numeric Discord user IDs allowed to use Print Handy, separated by "
             "commas (right-click a user > Copy User ID, with Developer Mode on) — or reply "
             "`everyone` to let anyone who can post in the print channel use it.", _validate_user_ids),
        Step("moonraker_url", "Moonraker URL (optional)",
             "If this printer runs Klipper/Moonraker, reply with its URL (for example "
             "http://printer.local:7125). Otherwise reply `skip`.", _validate_service_url),
        Step("spoolman_url", "Spoolman URL (optional)",
             "If you run Spoolman for filament inventory, reply with its URL (for example "
             "http://spoolman.local:7912; the Spoolman included in the Docker stack is "
             "http://spoolman:8000). Otherwise reply `skip`.", _validate_spoolman_url),
        Step("token_stored", "Bot token stored securely",
             f"Create the bot in the Discord developer portal and store its token as the "
             f"environment variable ${token_env} in the profile/data folder's `.env` file "
             f"(file mode 600) — see docs/DISCORD-BOT-SETUP.md. Never paste the token in chat; "
             f"Print Handy only ever reads ${token_env}. Reply `stored` when it is saved, or "
             f"`skip` to do it later.", _validate_token_ack),
    )


STEP_LABELS = {s.key: s.label for s in steps()}


# ---------------------------------------------------------------------- add-a-printer loop (#337)

def _taken_ids(answers):
    ids = {p["id"] for p in answers.get("printers") or [] if isinstance(p, dict) and p.get("id")}
    if answers.get("printer_id"):
        ids.add(answers["printer_id"])
    return ids


def _validate_first_id(value, answers):
    from ..setup_wizard import _printer_id_error
    error = _printer_id_error(value.strip(), _taken_ids(answers))
    if error:
        raise ValueError(error)
    return value.strip()


def _validate_new_id(value, answers):
    from ..setup_wizard import _printer_id_error
    error = _printer_id_error(value.strip(), _taken_ids(answers))
    if error:
        raise ValueError(error)
    return value.strip()


def _validate_new_chat_id(value, _answers):
    # An added printer always needs its OWN channel in this flow: the main
    # channel is the first printer's fallback claim, and two entries claiming
    # one channel are refused at load (design §2.3).
    return _one_id(value.strip(), "channel")


def _add_step_defs():
    model_list = ", ".join(sorted(printers.MODELS))
    return {
        "first_id": Step("first_id", "First printer's id",
                         "Your first printer needs an id too — it names its state folder and "
                         "binds its channel. Reply with a short slug (lowercase letters, digits, "
                         "- or _), for example `garage-a1`.", _validate_first_id),
        "id": Step("id", "Printer id",
                   "Give the new printer an id (a short slug, for example `workshop-ad5x`). "
                   "It names its state folder and binds its channel.", _validate_new_id),
        "model": Step("model", "Printer model",
                      f"Which printer? Reply with its model key, one of: {model_list}.",
                      _validate_model),
        "chat_id": Step("chat_id", "Printer channel",
                        "Reply with the new printer's own channel ID. It cannot share the main "
                        "print channel — that one is the first printer's, and approvals in a "
                        "channel can only start that channel's printer.", _validate_new_chat_id),
        "moonraker_url": Step("moonraker_url", "Moonraker URL (optional)",
                              "If this printer runs Klipper/Moonraker, reply with its URL (for "
                              "example http://printer.local:7125). Otherwise reply `skip`.",
                              _validate_service_url),
    }


def _add_keys(session):
    """The step keys of one add-a-printer cycle, frozen when the cycle starts.

    The first cycle also asks the first printer's id (the base flow never needed
    one); freezing the list keeps the step index stable as answers land."""
    keys = ["id", "model", "chat_id", "moonraker_url"]
    if "printer_id" not in (session.get("answers") or {}):
        keys.insert(0, "first_id")
    return keys


def _add_prompt_text(session, note=""):
    keys = session["add_keys"]
    step = _add_step_defs()[keys[session["add_step"]]]
    head = f"**Add a printer ({session['add_step'] + 1} of {len(keys)}): {step.label}**\n{step.prompt}"
    return (note + "\n" if note else "") + head + "\n\n" + checklist_text(session) + \
        "\n\nReply with the answer, or `/print-handy cancel` to pause (your checklist is saved)."


# ---------------------------------------------------------------------- session store

class SetupStore:
    """All guided-setup sessions in one JSON file (mode 600: it holds Discord user IDs)."""

    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, key):
        session = self._load().get(key)
        return session if isinstance(session, dict) else None

    def save(self, session):
        data = self._load()
        data[session["key"]] = session
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from ..setup_wizard import _atomic_write
        _atomic_write(self.path, json.dumps(data, indent=1), 0o600)

    def clear(self, key):
        data = self._load()
        if key in data:
            del data[key]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            from ..setup_wizard import _atomic_write
            _atomic_write(self.path, json.dumps(data, indent=1), 0o600)


def default_store(cfg=None):
    data = cfg if cfg is not None else settings.current()
    return SetupStore(settings.state_dir(data) / STORE_NAME)


def _new_session(key, now):
    return {"key": key, "status": "in_progress", "answers": {}, "step": 0,
            "created_at": now, "updated_at": now}


def _expired(session, now):
    return (session["status"] in ("in_progress", "awaiting_consent", "adding_printer")
            and now - float(session.get("updated_at") or 0) > SESSION_TIMEOUT_S)


def checklist_text(session):
    flow = steps()
    answers = session.get("answers") or {}
    lines = []
    for index, step in enumerate(flow):
        if step.key in answers:
            mark = "☑"
        elif session["status"] == "in_progress" and index == session.get("step"):
            mark = "▶"
        else:
            mark = "☐"
        lines.append(f"{mark} {step.label}")
    for extra in answers.get("printers") or []:
        if isinstance(extra, dict) and extra.get("id"):
            lines.append(f"☑ Added printer {extra['id']} ({extra.get('model', '?')})")
    if session["status"] == "awaiting_consent":
        lines.append("▶ Review and choose how to apply")
    return "\n".join(lines)


def _prompt_text(session, note=""):
    flow = steps()
    step = flow[session["step"]]
    head = f"**Setup step {session['step'] + 1} of {len(flow)}: {step.label}**\n{step.prompt}"
    return (note + "\n" if note else "") + head + "\n\n" + checklist_text(session) + \
        "\n\nReply with the answer, or `/print-handy cancel` to pause (your checklist is saved)."


def _review_text(session):
    answers = session["answers"]
    lines = ["**Setup is ready to review.** Nothing has been written yet.",
             f"- Printer model: `{answers.get('model')}`",
             f"- Bot mode: `{answers.get('mode')}`",
             "- Print channel and access: the user IDs you entered (not repeated here), "
             "or everyone in the channel if you chose `everyone`",
             f"- Moonraker URL: {answers.get('moonraker_url') or 'not set'}",
             f"- Spoolman URL: {answers.get('spoolman_url') or 'not set'}",
             f"- Bot token: {'stored in its environment variable' if answers.get('token_stored') else 'not stored yet — the bot cannot log in until it is'}"]
    roster = answers.get("printers") or []
    if roster:
        lines.append(f"- First printer id: `{answers.get('printer_id')}`")
        for extra in roster:
            lines.append(f"- Added printer: `{extra['id']}` — model `{extra.get('model')}`, "
                         f"channel {'its own' if extra.get('chat_id') else 'the main print channel'}"
                         + (f", Moonraker {extra['moonraker_url']}" if extra.get('moonraker_url') else ""))
    lines += ["", checklist_text(session), "",
              "Reply `apply` to write these settings to config/local.yaml (values already there "
              "always win; the token is never written). Reply `add` to add another printer — it "
              "gets its own channel and state folder. Reply `manual` for precise steps to do it "
              "yourself instead, or `/print-handy cancel` to leave setup unfinished and resume later."]
    return "\n".join(lines)


def _manual_text(session):
    answers = session["answers"]
    roster = answers.get("printers") or []
    lines = ["**Manual setup steps** — nothing was changed for you.",
             "1. In the Print Handy folder, create or edit `config/local.yaml` with:"]
    if roster:
        lines.append("   - a `printers:` list (TOML spelling: `[[printers]]`), one entry per printer:")
        first = f"     - `id` = `{answers.get('printer_id')}`, `model` = `{answers.get('model')}`"
        if answers.get("moonraker_url"):
            first += ", `moonraker_url` = the URL you entered above"
        lines.append(first)
        for extra in roster:
            entry = f"     - `id` = `{extra['id']}`, `model` = `{extra.get('model')}`"
            if extra.get("chat_id"):
                entry += ", `chat_id` = the channel ID you entered above"
            if extra.get("moonraker_url"):
                entry += ", `moonraker_url` = the URL you entered above"
            lines.append(entry)
        lines.append("   - entry values can be overridden later with PRINT_HANDY__PRINTERS__<ID>__<KEY>; "
                     "the list itself is file-only (docs/SETTINGS.md, 'Printers list')")
    else:
        lines.append(f"   - `[printer] model` = `{answers.get('model')}`")
    lines += [f"   - `[bot] mode` = `{answers.get('mode')}`",
              "   - `[discord] chat_id` and `allowed_user_ids` = what you entered above "
              "(blank `allowed_user_ids` = everyone in the channel)"]
    if answers.get("moonraker_url") and not roster:
        lines.append("   - `[services] moonraker_url` = the URL you entered above")
    if answers.get("spoolman_url"):
        lines.append("   - `[services] spoolman_url` = the URL you entered above")
    lines += ["2. Store the Discord bot token in the environment variable named by `[discord] "
              "token_env` (default `DISCORD_BOT_TOKEN`) in the profile/data folder `.env` "
              "(file mode 600). Do not put the token in the YAML file or in chat.",
              "3. Validate offline: `python3 -m print_handy.bot check` (standalone) or "
              "`python3 -m print_handy.doctor`.",
              "4. Run `/print-handy debugging` here to re-check. Your saved checklist stays "
              "available with `/print-handy status` until you finish or restart setup."]
    return "\n".join(lines)


def _roster_config(answers):
    """The [[printers]] config for a roster apply (#337): the first printer plus
    every added one, with Spoolman kept as the one shared inventory service."""
    first = {"id": answers["printer_id"], "model": answers["model"]}
    if answers.get("moonraker_url"):
        first["moonraker_url"] = answers["moonraker_url"]
    entries = [first]
    for extra in answers["printers"]:
        entry = {"id": extra["id"], "model": extra["model"]}
        if extra.get("chat_id"):
            entry["chat_id"] = extra["chat_id"]
        if extra.get("moonraker_url"):
            entry["moonraker_url"] = extra["moonraker_url"]
        entries.append(entry)
    config = {"printers": entries, "bot": {"mode": answers["mode"]},
              "discord": {"chat_id": answers["chat_id"], "allowed_user_ids": answers["user_ids"]}}
    if answers.get("spoolman_url"):
        config["services"] = {"spoolman_url": answers["spoolman_url"]}
    return config


def _refuse_unsafe_roster_target(config_path):
    """A roster apply never merges into a file that already describes printers.

    The wizard merge is existing-keys-win, so a roster merged into a file with a
    legacy [printer] shape (or an existing roster) would be silently dropped or
    clash; and a file the wizard cannot round-trip is never rewritten at all.
    Both cases raise with the file left byte-for-byte unchanged."""
    from .. import setup_wizard
    path = Path(config_path)
    if not path.exists():
        return
    parsed = setup_wizard._load_for_rewrite(path.read_text(encoding="utf-8"))
    if parsed is None:
        raise RuntimeError("the existing config/local.yaml cannot be safely rewritten (it does "
                           "not parse and re-emit faithfully), so it was left unchanged. Fix it "
                           "by hand or move it aside, then reply `apply` again.")
    printer = parsed.get("printer") if isinstance(parsed.get("printer"), dict) else {}
    services = parsed.get("services") if isinstance(parsed.get("services"), dict) else {}
    legacy = ("printers" in parsed or bool(printer.get("model") or printer.get("name"))
              or any(services.get(k) for k in ("moonraker_url", "octoprint_url", "camera_snapshot_url"))
              or any(isinstance(parsed.get(section), dict)
                     and any(parsed[section].get(k) for k in ("lan_host", "link_host", "host"))
                     for section in ("bambu", "prusa", "elegoo_sdcp", "flashforge_stock")))
    if legacy:
        raise RuntimeError("the existing config/local.yaml already describes a printer, so guided "
                           "setup will not merge a roster into it; the file was left unchanged. "
                           "Edit it by hand (docs/SETTINGS.md, 'Printers list') or move it aside, "
                           "then reply `apply` again.")


def _apply_answers(answers, config_path):
    """Write the collected settings after the explicit `apply` consent.

    Only config/local.yaml is touched, through the setup wizard's merge (existing keys win).
    No secret is written: the token step collected none. Installing software, restarting
    services, and changing network exposure are never done by this flow. When printers were
    added, the write is the [[printers]] roster form instead, and it refuses (leaving the
    file untouched) when the existing file already describes printers or cannot be
    round-tripped by the wizard (#337).
    """
    from .. import setup_wizard

    class _Consent:
        """The Discord `apply` reply is the consent merge_config asks for."""
        def __init__(self):
            self.notes = []

        def say(self, text=""):
            self.notes.append(str(text))

        def confirm(self, _key, _prompt, default=True):
            return True

    roster = bool(answers.get("printers"))
    if roster:
        _refuse_unsafe_roster_target(config_path)
        config = _roster_config(answers)
    else:
        config = {"printer": {"model": answers["model"]}, "bot": {"mode": answers["mode"]},
                  "discord": {"chat_id": answers["chat_id"], "allowed_user_ids": answers["user_ids"]}}
        services = {}
        if answers.get("moonraker_url"):
            services["moonraker_url"] = answers["moonraker_url"]
        if answers.get("spoolman_url"):
            services["spoolman_url"] = answers["spoolman_url"]
        if services:
            config["services"] = services
    writer = _Consent()
    if not setup_wizard.merge_config(Path(config_path), config, writer):
        detail = writer.notes[-1] if writer.notes else "the wizard merge declined to write"
        raise RuntimeError("the settings were not written: " + detail)
    lead = (f"Settings written to config/local.yaml as a [[printers]] roster "
            f"({len(answers['printers']) + 1} printers; any values already there were kept). "
            if roster else
            "Settings written to config/local.yaml (any values already there were kept). ")
    return (lead + "The bot token was not written anywhere by this flow. Nothing was installed, "
            "restarted, or exposed on the network. Next: `python3 -m print_handy.bot check`, "
            "then `/print-handy debugging`.")


# ---------------------------------------------------------------------- the flow

def handle_text(key, text, *, store, now=None, token_env="DISCORD_BOT_TOKEN",
                apply_config=None, report=None, bundle=None):
    """One message in the guided flows. Returns the reply text, or None when not ours.

    ``key`` identifies one person's session in one channel/thread. ``report`` is a zero-arg
    callable returning the debugging report; ``bundle`` is a zero-arg callable that writes
    the #390 diagnostics bundle and returns the reply saying where it went;
    ``apply_config`` writes the consented settings.
    """
    now = time.time() if now is None else now
    raw = str(text or "").strip()
    low = raw.casefold()
    session = store.get(key)

    if low.startswith("/print-handy"):
        rest = low[len("/print-handy"):].strip()
        if rest in ("", "help"):
            return HELP
        if rest == "debugging" or rest == "debug":
            if report is None:
                return "Debugging is not available in this runtime."
            return report()
        if rest == "bundle":
            if bundle is None:
                return ("Diagnostics bundles are not available in this runtime. On the host, run "
                        "`python3 -m print_handy.diagnostics_bundle` instead.")
            return bundle()
        if rest == "status":
            if session is None:
                return "No guided setup has been started here. `/print-handy setup` begins one."
            state = {"in_progress": "in progress", "adding_printer": "adding another printer",
                     "awaiting_consent": "waiting for your review choice",
                     "cancelled": "paused (cancelled)", "complete": "complete"}[session["status"]]
            return f"**Guided setup: {state}**\n" + checklist_text(session)
        if rest == "cancel":
            if session is None or session["status"] == "complete":
                return "No guided setup is in progress. Nothing was changed."
            session["status"] = "cancelled"
            session["updated_at"] = now
            store.save(session)
            return ("Setup paused. Your answers are saved in the checklist and nothing was "
                    "written to the configuration.\n" + checklist_text(session) +
                    "\nResume any time with `/print-handy setup`.")
        if rest in ("setup", "setup restart"):
            if rest == "setup restart" or session is None or session["status"] == "complete":
                session = _new_session(key, now)
                store.save(session)
                return _prompt_text(session, "**Guided setup started.** One question at a time; "
                                             "nothing is written until you approve it at the end.")
            note = ""
            if session["status"] == "cancelled":
                note = "**Welcome back — resuming your saved checklist.**"
            elif _expired(session, now):
                note = "**Your previous session timed out; your saved answers were kept.** Resuming:"
            if session.get("add_keys") is not None and session.get("draft") is not None:
                # paused mid add-a-printer cycle: resume the cycle, not the base flow
                session["status"] = "adding_printer"
                session["updated_at"] = now
                store.save(session)
                return _add_prompt_text(session, note)
            session["status"] = "in_progress" if session["status"] != "awaiting_consent" else "awaiting_consent"
            session["updated_at"] = now
            store.save(session)
            if session["status"] == "awaiting_consent":
                return (note + "\n" if note else "") + _review_text(session)
            return _prompt_text(session, note)
        return ("Use `/print-handy setup`, `/print-handy debugging`, `/print-handy bundle`, "
                "`/print-handy status`, or `/print-handy cancel`.")

    if session is None or session["status"] not in ("in_progress", "awaiting_consent", "adding_printer"):
        return None
    if raw.startswith("/"):
        return None  # another command; setup stays open for a later plain reply
    if _expired(session, now):
        return ("This setup session timed out, so that reply was not used as an answer. "
                "Your saved answers were kept — run `/print-handy setup` to resume the checklist.")

    if session["status"] == "awaiting_consent":
        if low == "apply":
            apply_config = apply_config or (lambda answers: _apply_answers(answers, settings.LOCAL))
            try:
                detail = apply_config(session["answers"])
            except Exception as exc:  # a failed write must not lose the checklist
                return ("The settings could not be saved, so nothing was changed. "
                        "This looks like a problem on the Print Handy side, not with your answers — "
                        "the detail is in the log, and `/print-handy bundle` gathers it for a report.\n"
                        "Your checklist is unchanged. Reply `apply` to retry, `manual` for "
                        "steps, or `/print-handy cancel` to pause.")
            session["status"] = "complete"
            session["updated_at"] = now
            store.save(session)
            return "**Setup complete.** " + detail
        if low == "manual":
            session["status"] = "cancelled"  # finished with the flow, checklist kept for reference
            session["updated_at"] = now
            store.save(session)
            return _manual_text(session)
        if low == "add":
            session["status"] = "adding_printer"
            session["draft"] = {}
            session["add_keys"] = _add_keys(session)
            session["add_step"] = 0
            session["updated_at"] = now
            store.save(session)
            return _add_prompt_text(session, "**Adding another printer.** Same idea: a few "
                                    "questions, and nothing is written until you reply `apply`.")
        return "Reply `apply` to write the settings, `add` to add another printer, `manual` for precise manual steps, or `/print-handy cancel` to pause."

    if session["status"] == "adding_printer":
        defs = _add_step_defs()
        key = session["add_keys"][session["add_step"]]
        step = defs[key]
        context = dict(session["answers"])
        if key == "moonraker_url" and session["draft"].get("model"):
            context["model"] = session["draft"]["model"]  # validate against the new printer's model
        try:
            value = step.validate(raw, context)
        except ValueError as exc:
            return f"That answer does not work: {exc}\n\n" + _add_prompt_text(session)
        if key == "first_id":
            session["answers"]["printer_id"] = value
        else:
            session["draft"][key] = value
        session["add_step"] += 1
        session["updated_at"] = now
        if session["add_step"] >= len(session["add_keys"]):
            draft = session["draft"]
            session["answers"].setdefault("printers", []).append(
                {"id": draft["id"], "model": draft["model"],
                 "chat_id": draft.get("chat_id", ""), "moonraker_url": draft.get("moonraker_url", "")})
            session["status"] = "awaiting_consent"
            for scratch in ("draft", "add_keys", "add_step"):
                session.pop(scratch, None)
            store.save(session)
            return (f"Saved: printer {draft['id']}.\n\n" + _review_text(session))
        store.save(session)
        return _add_prompt_text(session, f"Saved: {step.label}.")

    flow = steps(token_env)
    step = flow[session["step"]]
    try:
        value = step.validate(raw, session["answers"])
    except ValueError as exc:
        return f"That answer does not work: {exc}\n\n" + _prompt_text(session)
    session["answers"][step.key] = value
    session["step"] += 1
    session["updated_at"] = now
    if session["step"] >= len(flow):
        session["status"] = "awaiting_consent"
        store.save(session)
        return _review_text(session)
    store.save(session)
    return _prompt_text(session, f"Saved: {step.label}.")


# ---------------------------------------------------------------------- debugging

@dataclass
class Finding:
    name: str
    status: str  # ok | warn | fail | skip
    detail: str
    action: str = ""


_MARKS = {"ok": "✓", "warn": "⚠", "fail": "✗", "skip": "–"}


def _default_probe(url):
    """A read-only GET. Returns the HTTP status; raises on any failure."""
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status


def _default_login_probe(token):
    from . import rest
    return rest.whoami(token)


def _default_version_runner(command):
    run = subprocess.run([*command, "--version"], capture_output=True, text=True, timeout=15)
    out = (run.stdout or run.stderr or "").strip()
    if run.returncode != 0 or not out:
        run = subprocess.run([*command, "--help"], capture_output=True, text=True, timeout=15)
        out = (run.stdout or run.stderr or "").strip()
    return out.splitlines()[0] if out else ""


def _default_token_getter(cfg):
    from ..hermes import _config
    return _config.profile_env_value(str(cfg["discord"].get("token_env") or "DISCORD_BOT_TOKEN"))


def run_diagnostics(*, loader=None, token_getter=None, probe=None, login_probe=None,
                    which=shutil.which, version_runner=None, environ=None):
    """Read-only checks. Every external contact is a GET probe or a `--version` run."""
    loader = loader or (lambda: settings.load(environ={}))
    probe = probe or _default_probe
    version_runner = version_runner or _default_version_runner
    findings: list[Finding] = []
    secrets = _env_secrets(environ)
    roots = [Path.home()]

    def clean(text):
        return redact(text, secrets=secrets, roots=roots)

    cfg = None
    try:
        cfg = loader()
    except Exception as exc:
        findings.append(Finding("configuration", "fail", clean(f"settings do not load: {exc}"),
                                "Fix the named setting in config/local.yaml (see "
                                "docs/CONFIGURATION-YAML.md), then run debugging again."))
    if cfg is not None:
        for section in ("paths",):
            for value in (cfg.get(section) or {}).values():
                if isinstance(value, (str, Path)):
                    roots.append(str(value))
        printer = cfg.get("printer") or {}
        findings.append(Finding("configuration", "ok",
                                clean(f"settings load and validate; printer model {printer.get('model')}, "
                                      f"bed {printer.get('bed_mm')}")))

        # Bot mode, token presence, and (standalone only) a read-only login probe.
        mode = str((cfg.get("bot") or {}).get("mode") or "hermes")
        token = ""
        if token_getter is not None or mode == "standalone":
            try:
                token = (token_getter or _default_token_getter)(cfg) or ""
            except Exception:
                token = ""
        if token:
            secrets.append(token)
        token_env = str((cfg.get("discord") or {}).get("token_env") or "DISCORD_BOT_TOKEN")
        if mode != "standalone":
            findings.append(Finding("bot mode and login", "skip",
                                    f"mode is {mode}; the Hermes gateway owns the Discord login",
                                    ""))
        elif not token:
            findings.append(Finding("bot mode and login", "fail",
                                    f"mode is standalone but ${token_env} is empty",
                                    f"Store the bot token in ${token_env} in the profile/data "
                                    "folder .env (mode 600); never paste it in chat."))
        else:
            try:
                me = (login_probe or _default_login_probe)(token)
                findings.append(Finding("bot mode and login", "ok",
                                        clean(f"standalone; Discord accepted the token "
                                              f"(bot user {me.get('username')})")))
            except Exception as exc:
                findings.append(Finding("bot mode and login", "warn",
                                        clean(f"standalone; ${token_env} is set but the read-only "
                                              "login check did not pass"),
                                        "Check network/DNS to discord.com and that the token was "
                                        "not reset in the developer portal."))

        # Permission prerequisites: what configuration can prove offline. Channel overrides
        # themselves are only visible to the logged-in bot, so they stay a manual next step.
        from .. import setup_wizard
        discord_cfg = cfg.get("discord") or {}
        chat = str(discord_cfg.get("chat_id") or "")
        try:
            users = settings.user_ids(discord_cfg.get("allowed_user_ids"))
        except Exception:
            users = []
        missing = []
        if not chat.isdigit():
            missing.append("discord.chat_id is not a numeric channel ID")
        needed = ", ".join(setup_wizard.discord_permissions())
        if missing:
            findings.append(Finding("permissions", "fail", clean("; ".join(missing)),
                                    f"The bot needs these channel permissions: {needed}. "
                                    "Set the IDs in config/local.yaml and check channel overrides."))
        else:
            # No allow list is a valid mode (#386): everyone in the channel.
            access = f"{len(users)} allowed user(s)" if users else "channel access (everyone in the print channel)"
            findings.append(Finding("permissions", "ok",
                                    clean(f"print channel set; access: {access}; "
                                          f"required channel permissions: {needed}"),
                                    ""))

        # Service connectivity and health: GET probes only, never a printer operation.
        from .. import doctor
        services = cfg.get("services") or {}
        probe_paths = dict(doctor.SERVICE_PATHS)
        if services.get("octoprint_url"):
            probe_paths["octoprint_url"] = "/api/version"
        for key, path in probe_paths.items():
            url = str(services.get(key) or "")
            label = key.replace("_url", "")
            if not url:
                findings.append(Finding(f"service: {label}", "skip", "not configured", ""))
                continue
            try:
                status = probe(url.rstrip("/") + path)
                findings.append(Finding(f"service: {label}", "ok",
                                        f"answered HTTP {status} on its read-only health path"))
            except Exception as exc:
                findings.append(Finding(f"service: {label}", "warn",
                                        clean("the health check did not answer"),
                                        f"Check the {label} service is running and reachable at "
                                        "the configured URL; debugging did not try to restart it."))

        # Executables and versions.
        findings.append(Finding("executable: python", "ok",
                                f"Python {sys.version_info.major}.{sys.version_info.minor}."
                                f"{sys.version_info.micro}"))
        orca = (cfg.get("orca") or {}).get("command") or []
        if orca:
            exe = orca[0]
            found = which(exe) or (str(exe) if Path(str(exe)).is_file() else None)
            if not found:
                findings.append(Finding("executable: slicer", "fail",
                                        clean(f"{exe} is not on PATH"),
                                        "Install OrcaSlicer or fix [orca] command in the settings."))
            else:
                try:
                    version = version_runner(list(orca))
                    findings.append(Finding("executable: slicer", "ok",
                                            clean(f"{exe} runs: {version}" if version else f"{exe} runs")))
                except Exception as exc:
                    findings.append(Finding("executable: slicer", "warn",
                                            clean(f"{exe} was found but did not run cleanly: {exc}"),
                                            "Run the slicer command in a terminal and fix what it reports."))
        ffmpeg = str((cfg.get("paths") or {}).get("ffmpeg") or "")
        if ffmpeg:
            found = which(ffmpeg) or (ffmpeg if Path(ffmpeg).is_file() else None)
            findings.append(Finding("executable: ffmpeg", "ok" if found else "warn",
                                    "found" if found else "not found; timelapse/video features "
                                    "that need it will fail",
                                    "" if found else "Install ffmpeg or fix [paths] ffmpeg."))

        # State and log locations: existence/access only. Exact paths stay out of the report.
        state = settings.state_dir(cfg)
        if not state.is_dir():
            findings.append(Finding("state and logs", "warn", "the state folder does not exist yet",
                                    "It is created when the bot or a check first runs: "
                                    "`python3 -m print_handy.bot check`."))
        elif not os.access(state, os.W_OK):
            findings.append(Finding("state and logs", "fail", "the state folder is not writable",
                                    "Fix ownership/permissions on the profile/data folder; "
                                    "the bot must save state and its heartbeat there."))
        else:
            log_file = str((cfg.get("logging") or {}).get("file") or "")
            detail = "state folder exists and is writable"
            if log_file:
                parent = Path(log_file).expanduser()
                parent = parent if parent.is_absolute() else state / parent
                detail += "; a log file is configured" + ("" if parent.parent.is_dir()
                                                          else " but its folder is missing")
            findings.append(Finding("state and logs", "ok", detail))
            try:
                from . import health
                heartbeat = health.read()
                if heartbeat:
                    fresh, why = health.evaluate(heartbeat, stale_s=int(cfg["bot"]["health_stale_s"]))
                    findings.append(Finding("bot heartbeat", "ok" if fresh else "warn",
                                            clean(f"standalone heartbeat: {why}"),
                                            "" if fresh else "Start the standalone bot, or ignore "
                                                              "this in Hermes mode."))
                else:
                    findings.append(Finding("bot heartbeat", "skip",
                                            "no standalone heartbeat found (expected in Hermes mode)", ""))
            except Exception:
                pass
    return findings


def format_report(findings, *, secrets=(), roots=()):
    roots = [Path.home(), *roots]
    lines = ["**Print Handy debugging** — read-only: no settings, services, or printer state were changed."]
    for finding in findings:
        line = f"{_MARKS.get(finding.status, '?')} {finding.name}: " + \
            redact(finding.detail, secrets=secrets, roots=roots)
        lines.append(line)
        if finding.action:
            lines.append("  → Next: " + redact(finding.action, secrets=secrets, roots=roots))
    failed = sum(1 for f in findings if f.status == "fail")
    warned = sum(1 for f in findings if f.status == "warn")
    lines.append(f"Summary: {failed} failed, {warned} warning(s), "
                 f"{sum(1 for f in findings if f.status == 'ok')} ok. "
                 "Anything that would edit configuration, install software, restart a service, "
                 "or change network exposure needs your explicit go-ahead first; otherwise the "
                 "Next steps above are the manual path.")
    return "\n".join(lines)


def debugging_report(**kwargs):
    """The full redacted report text for ``/print-handy debugging``."""
    secrets = list(kwargs.pop("secrets", ()) or ())
    return format_report(run_diagnostics(**kwargs), secrets=secrets)
