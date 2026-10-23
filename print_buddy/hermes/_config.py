"""Shared access to Print Buddy settings, state files and secrets for the Hermes helpers.

Every hardcoded host, path and interval of the original scripts is a setting in the home configuration.
Tests install an override with set_override() so no code path reads a live setup.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from print_buddy import settings

_override: dict[str, Any] | None = None


def set_override(data: dict[str, Any] | None) -> None:
    """Use this settings dict instead of settings.current() (tests only)."""
    global _override
    _override = data


def cfg() -> dict[str, Any]:
    return _override if _override is not None else settings.current()


def hermes_home() -> Path:
    return Path(cfg()["paths"]["hermes_home"])


_pinned: dict[str, Any] | None = None


def pinned_hermes_home() -> Path:
    """The profile home from config files only, ignoring $HERMES_HOME.

    A cron job's HERMES_HOME is the launching profile, not the print profile, so anything that
    must find the print profile's state.db reads this instead.
    """
    global _pinned
    if _override is not None:
        return Path(_override["paths"]["hermes_home"])
    if _pinned is None:
        _pinned = settings.load(environ={})
    return Path(_pinned["paths"]["hermes_home"])


def bot_name() -> str:
    """The name the bot uses for itself: [discord] bot_name."""
    return str(cfg()["discord"]["bot_name"]).strip() or "Print Buddy"


def state_dir() -> Path:
    return settings.state_dir(cfg())


def state_file(env_var: str | None, name: str) -> Path:
    """A state file: the legacy env var if set (tests rely on it), else <state_dir>/<name>."""
    if env_var and os.environ.get(env_var):
        return Path(os.environ[env_var])
    return state_dir() / name


def service_url(key: str) -> str:
    """A [services] URL without a trailing slash. Empty when not configured."""
    return str(cfg()["services"].get(key) or "").rstrip("/")


def require(url: str, setting: str) -> str:
    """Return url, or fail clearly when the setting is empty."""
    if not url:
        raise RuntimeError(f"{setting} is not configured. Set it in config/local.yaml (or legacy config/local.toml).")
    return url


def moonraker_url() -> str:
    return service_url("moonraker_url")


def archive_dir() -> Path:
    return Path(cfg()["paths"]["archive"])


def records_vault() -> Path:
    return Path(cfg()["paths"]["records_vault"])


def hermes_bin() -> str:
    return str(cfg()["paths"]["hermes_bin"])


def ffmpeg_bin() -> str:
    return str(cfg()["paths"]["ffmpeg"])


def cache_dir() -> Path:
    return Path(cfg()["paths"]["cache"])


def timezone_name() -> str:
    return str(cfg()["discord"]["timezone"])


def tz():
    """The configured display timezone (discord.timezone)."""
    from zoneinfo import ZoneInfo
    return ZoneInfo(timezone_name())


def tz_label(dt=None) -> str:
    """Short zone label for messages: ET for America/New_York, else the zone's own abbreviation."""
    if timezone_name() == "America/New_York":
        return "ET"
    from datetime import datetime
    return (dt or datetime.now(tz())).tzname() or timezone_name()


def discord_chat_id() -> str:
    return str(cfg()["discord"]["chat_id"] or "")


def bot_mode() -> str:
    """hermes (the gateway runs the plugin) or standalone (python3 -m print_buddy.bot)."""
    return str((cfg().get("bot") or {}).get("mode") or "hermes")


def standalone() -> bool:
    return bot_mode() == "standalone"


def discord_token() -> str:
    """The Discord bot token: the [discord] token_env variable, then the profile .env files."""
    name = str((cfg().get("discord") or {}).get("token_env") or "DISCORD_BOT_TOKEN")
    return profile_env_value(name)


def question_timeout_s() -> int:
    """How long a Discord question waits for a button press."""
    return int(cfg()["discord"]["question_timeout_s"])


def safety_confirm_timeout_s() -> int:
    """How long a safety confirmation (stop, resume, reboot, cold-pull go-ahead) waits."""
    return int(cfg()["discord"]["safety_confirm_timeout_s"])


def upload_wait_s() -> int:
    """How long an upload-wait freeze stays active before it expires."""
    return int(cfg()["discord"]["upload_wait_s"])


def cold_pull_outcome_s() -> int:
    """How long a cold-pull outcome prompt stays open."""
    return int(cfg()["discord"]["cold_pull_outcome_s"])


def add_hermes_agent_to_path() -> None:
    """Make hermes_state / hermes_cli importable, using [paths] hermes_agent."""
    agent = str(Path(cfg()["paths"]["hermes_agent"]).expanduser())
    if agent not in sys.path:
        sys.path.insert(0, agent)


def _env_file_value(path: Path, name: str) -> str:
    try:
        for line in path.read_text().splitlines():
            if line.startswith(f"{name}="):
                found = line.split("=", 1)[1].strip().strip("'\"")
                if found:
                    return found
    except OSError:
        pass
    return ""


def profile_env_value(name: str, *, include_global: bool = True) -> str:
    """A secret: the environment, then the profile .env, then the global .env next to the hermes root."""
    value = os.environ.get(name)
    if value:
        return value
    home = hermes_home()
    paths = [home / ".env"]
    if include_global:
        paths.append(home.parent.parent / ".env")
    for path in paths:
        found = _env_file_value(path, name)
        if found:
            return found
    return ""
