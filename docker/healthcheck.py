#!/usr/bin/env python3
"""Container readiness across the bot, Moonraker listener and local Spoolman."""
import os
import sys
import urllib.request

# Installed as /usr/local/bin/print-buddy-healthcheck: for a script invocation Python
# puts the SCRIPT's directory on sys.path, not /app, so without this the probe dies
# with ModuleNotFoundError (the combined container could never report healthy).
# Same pattern as tests/docker/image_probe.py and docker/slicer-smoke.py.
sys.path.insert(0, "/app")

from print_buddy.bot.health import check as bot_check
from print_buddy.healthcheck import check as listener_check


def bot_token_env():
    """(platform, token env var name) for the configured chat platform (#164).

    Mirrors docker/supervise.sh: the platform and the name of the environment
    variable holding its token come from Print Buddy's own settings. When the
    settings cannot be loaded, the Discord default applies.
    """
    try:
        from print_buddy import settings
        cfg = settings.current()
        platform = str(cfg["bot"].get("platform") or "discord")
        if platform == "matrix":
            return platform, str(cfg["matrix"]["access_token_env"])
        return platform, str(cfg[platform]["token_env"])
    except Exception:
        return "discord", "DISCORD_BOT_TOKEN"


def main():
    healthy = True
    platform, token_env = bot_token_env()
    if os.environ.get(token_env):
        healthy &= bot_check() == 0
    else:
        label = {"discord": "Discord", "telegram": "Telegram", "matrix": "Matrix"}.get(platform, platform)
        print(f"ok  {label} bot disabled by empty token")
    ok, reason = listener_check()
    print(f"{'ok' if ok else 'FAIL'}  listener: {reason}")
    healthy &= ok
    try:
        url = ("http://127.0.0.1:" + os.environ.get("SPOOLMAN_PORT", "8000")
               if os.environ.get("PRINT_BUDDY_BUNDLED_SPOOLMAN", "true") == "true"
               else os.environ["PRINT_BUDDY__SERVICES__SPOOLMAN_URL"].rstrip("/"))
        with urllib.request.urlopen(url + "/api/v1/health", timeout=3) as response:
            healthy &= response.status == 200
            print(f"{'ok' if response.status == 200 else 'FAIL'}  Spoolman: HTTP {response.status}")
    except Exception as exc:
        print(f"FAIL  Spoolman: {exc}")
        healthy = False
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
