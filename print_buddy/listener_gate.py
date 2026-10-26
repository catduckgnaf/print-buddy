"""Shell-facing probe: which listener serves the configured printer instance?

docker/supervise.sh runs ``python3 -m print_buddy.listener_gate`` before
starting children (#256, generalised by #299). The decision comes from the
resolved configuration (the printer model and its vendor connection, via
print_buddy.healthcheck) and the listener registry (print_buddy.listeners),
never from whether a service URL happens to be filled in, so a
misconfiguration still fails loudly in settings validation instead of
silently changing which children run.

Exit codes: 0 = the instance's listener domain is implemented, start the
listener (through the registry launcher, ``python3 -m print_buddy.listeners``);
3 = the domain is known but has no listener yet, or has none by definition
(the supervisor starts nothing and idles as before); 2 = the configuration
could not be resolved (the supervisor stops with the printed error rather
than guessing).
"""
from __future__ import annotations

import sys

from . import healthcheck, listeners, settings


def main():
    try:
        domain = healthcheck.listener_domain()
    except settings.SettingsError as exc:
        print(f"listener gate: configuration unresolved: {exc}", file=sys.stderr)
        return 2
    if domain is None:
        connection = healthcheck.listener_connection()
        print(f"listener gate: connection {connection!r} has no registered listener domain; not starting one")
        return 3
    if domain.implemented:
        print(f"listener gate: domain {domain.name!r} listener is {domain.module}")
        return 0
    if domain.availability == listeners.NONE:
        print(f"listener gate: domain {domain.name!r} has no listener; not starting one")
    else:
        print(f"listener gate: domain {domain.name!r} has no listener yet; not starting one")
    return 3


if __name__ == "__main__":
    sys.exit(main())
