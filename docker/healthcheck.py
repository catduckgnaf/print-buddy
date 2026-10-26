#!/usr/bin/env python3
"""Container readiness across the bot, the printer listener and local Spoolman."""
import os
import sys
import urllib.error
import urllib.request

# Installed as /usr/local/bin/print-buddy-healthcheck: for a script invocation Python
# puts the SCRIPT's directory on sys.path, not /app, so without this the probe dies
# with ModuleNotFoundError (the combined container could never report healthy).
# Same pattern as tests/docker/image_probe.py and docker/slicer-smoke.py.
sys.path.insert(0, "/app")

from print_buddy import go2rtc, settings
from print_buddy.bot.health import check as bot_check
from print_buddy.healthcheck import check as listener_check
from print_buddy.healthcheck import listener_domain, listener_required
from print_buddy.webui_gate import webui_config


def main():
    healthy = True
    if os.environ.get("DISCORD_BOT_TOKEN"):
        healthy &= bot_check() == 0
    else:
        print("ok  Discord bot disabled by empty token")
    # The listener is required exactly when the supervisor started it: the
    # listener registry (print_buddy.listeners, #299) decides from the
    # configured instance's domain, mirroring the disabled-bot branch above.
    # An unresolved configuration fails instead of passing.
    try:
        required = listener_required()
    except settings.SettingsError as exc:
        print(f"FAIL  listener: configuration unresolved: {exc}")
        required, healthy = None, False
    if required:
        ok, reason = listener_check()
        print(f"{'ok' if ok else 'FAIL'}  listener: {reason}")
        healthy &= ok
    elif required is not None:
        detail = ""
        try:
            domain = listener_domain()
        except Exception:
            domain = None
        if domain is not None:
            state = "has no listener yet" if domain.availability == "planned" \
                else "has no listener"
            detail = f" (domain {domain.name!r} {state})"
        print(f"ok  listener: not required for this printer connection{detail}")
    # go2rtc (#246 stage 1) is covered exactly when the supervisor started
    # it: the same gate decision (print_buddy.go2rtc), mirroring the
    # disabled-bot branch above. Capture disabled (or enabled with no
    # camera source) is a healthy, reported state; enabled in an image
    # without the binary (a WITH_GO2RTC=false build) fails with the reason.
    gate = go2rtc.gate()
    if gate == 2:
        print("FAIL  go2rtc: configuration unresolved")
        healthy = False
    elif gate == 0:
        if not go2rtc.binary_present():
            print("FAIL  go2rtc: timelapse capture is enabled but go2rtc is "
                  "not in this image (built with WITH_GO2RTC=false)")
            healthy = False
        else:
            ok, reason = go2rtc.check()
            print(f"{'ok' if ok else 'FAIL'}  go2rtc: {reason}")
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
    # The Web UI row mirrors the supervisor's webui gate (#286 stage 4):
    # skipped when disabled or portless, exactly like the listener row
    # above. When the supervisor started the server, any HTTP answer from
    # /healthz proves it is up: the status code itself is the bot
    # heartbeat's verdict (200 healthy, 503 stale), which the bot row
    # above already owns, so both mean the Web UI is serving. A token is
    # sent when the environment carries one, matching the server's rule
    # that a configured token guards every route.
    try:
        webui_enabled, webui_host, webui_port, webui_env_name = webui_config()
        webui_resolved = True
    except settings.SettingsError as exc:
        print(f"FAIL  webui: configuration unresolved: {exc}")
        webui_enabled, webui_resolved, healthy = False, False, False
    if webui_resolved and webui_enabled and webui_port > 0:
        probe_host = "127.0.0.1" if webui_host in ("0.0.0.0", "::") else webui_host
        request = urllib.request.Request(
            f"http://{probe_host}:{webui_port}/healthz")
        token = os.environ.get(webui_env_name, "")
        if token:
            request.add_header("X-WebUI-Token", token)
        status = None
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        except Exception as exc:
            print(f"FAIL  webui: {exc}")
            healthy = False
        if status is not None:
            if status in (200, 503):
                print(f"ok  webui: serving on {webui_host}:{webui_port} (HTTP {status})")
            else:
                print(f"FAIL  webui: HTTP {status} from /healthz")
                healthy = False
    elif webui_resolved and webui_enabled:
        print("ok  webui: enabled but no port chosen; not started")
    elif webui_resolved:
        print("ok  webui: disabled")
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
