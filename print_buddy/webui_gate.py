"""Shell-facing probe: is the optional Web UI enabled with a port? (#286)

docker/supervise.sh runs ``python3 -m print_buddy.webui_gate`` before
starting children (stage 4), mirroring print_buddy.listener_gate (#256).
The decision comes from the resolved configuration ([webui] enabled and
port, via print_buddy.settings), never from whether an environment
variable happens to be filled in, so a misconfiguration still fails
loudly in settings validation instead of silently changing which
children run. The gate only decides *whether* to start the server: the
server's own start rules (print_buddy.webui.server.check_start — a
non-loopback bind requires the access token) still apply to the child
and are never bypassed here.

Exit codes: 0 = the Web UI is enabled and a port is chosen, start it
(``python3 -m print_buddy.webui``); 3 = the Web UI is disabled, or
enabled without a port, so the supervisor starts nothing; 2 = the
configuration could not be resolved (the supervisor stops with the
printed error rather than guessing).
"""
from __future__ import annotations

import sys

from . import settings


def webui_config(data=None):
    """(enabled, host, port, access_token_env) from the resolved settings.

    Settings problems propagate as SettingsError, the gate's unresolved
    case (#256). docker/healthcheck.py reuses this for its Web UI row so
    the probe and the supervisor can never disagree.
    """
    data = settings.load() if data is None else data
    webui = data["webui"]
    return (bool(webui["enabled"]), str(webui["host"]),
            int(webui["port"] or 0), str(webui["access_token_env"]))


def decide(data=None):
    """0 when the supervisor should start the Web UI, 3 when it should not."""
    enabled, _host, port, _env_name = webui_config(data)
    return 0 if enabled and port > 0 else 3


def main():
    try:
        enabled, host, port, _env_name = webui_config()
    except settings.SettingsError as exc:
        print(f"webui gate: configuration unresolved: {exc}", file=sys.stderr)
        return 2
    if enabled and port > 0:
        print(f"webui gate: enabled on {host}:{port}")
        return 0
    if enabled:
        print("webui gate: enabled but no port chosen ([webui] port is 0); not starting it")
    else:
        print("webui gate: [webui] enabled is false; not starting it")
    return 3


if __name__ == "__main__":
    sys.exit(main())
