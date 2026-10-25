#!/usr/bin/env python3
"""Container readiness across the bot, Moonraker listener and local Spoolman."""
import os
import sys
import urllib.request

from print_buddy.bot.health import check as bot_check
from print_buddy.healthcheck import check as listener_check


def main():
    healthy = True
    if os.environ.get("DISCORD_BOT_TOKEN"):
        healthy &= bot_check() == 0
    else:
        print("ok  Discord bot disabled by empty token")
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
