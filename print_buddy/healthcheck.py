"""Container health: the running Print Buddy process writes a heartbeat, the health check reads it.

    python3 -m print_buddy.healthcheck          # exit 0 healthy, 1 unhealthy
    python3 -m print_buddy.healthcheck --json   # the same, plus the last heartbeat

A runtime calls beat() on its own event loop every HEARTBEAT_S seconds. The check fails when settings
no longer load, the bundled slicer is missing, or the heartbeat is missing, stale, or written by a
process that is not running in this container. A printer that is switched off is not a failure: the
heartbeat carries the printer connection state for operators, but a container restart cannot fix it.

Any runtime (today the Moonraker listener, later the standalone bot from #73) only needs to call beat().
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path

from . import settings

HEARTBEAT = "heartbeat.json"
HEARTBEAT_S = 30
# Three missed beats; override with PRINT_BUDDY_HEALTH_MAX_AGE_S.
DEFAULT_MAX_AGE_S = 90


def heartbeat_path(data=None) -> Path:
    return settings.state_dir(data) / HEARTBEAT


def beat(runtime, data=None, **details):
    """Atomically record that runtime is alive. details must be JSON serialisable."""
    path = heartbeat_path(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"runtime": runtime, "pid": os.getpid(), "host": socket.gethostname(),
              "time": time.time(), **details}
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(record, sort_keys=True))
    os.replace(tmp, path)
    return record


def _pid_running(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError, OverflowError):
        return False
    return True


def check(data=None, now=None, environ=None):
    """Return (healthy, reason, heartbeat record or None)."""
    environ = os.environ if environ is None else environ
    try:
        data = data or settings.load(environ=environ)
    except settings.SettingsError as exc:
        return False, f"settings: {exc}", None
    command = data["orca"]["command"][0]
    if not (shutil.which(command) or Path(command).is_file()):
        return False, f"orca.command {command} is not installed", None
    path = heartbeat_path(data)
    try:
        record = json.loads(path.read_text())
    except FileNotFoundError:
        return False, f"no heartbeat at {path} yet", None
    except (OSError, ValueError) as exc:
        return False, f"unreadable heartbeat {path}: {exc}", None
    max_age = float(environ.get("PRINT_BUDDY_HEALTH_MAX_AGE_S") or DEFAULT_MAX_AGE_S)
    age = (time.time() if now is None else now) - float(record.get("time") or 0)
    if age > max_age:
        return False, f"heartbeat is {age:.0f}s old (limit {max_age:.0f}s)", record
    if record.get("host") != socket.gethostname() or not _pid_running(record.get("pid")):
        return False, "heartbeat was written by a process that is not running here", record
    return True, f"{record.get('runtime')} alive {age:.0f}s ago", record


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    healthy, reason, record = check()
    if "--json" in argv:
        print(json.dumps({"healthy": healthy, "reason": reason, "heartbeat": record}, sort_keys=True))
    else:
        print(f"{'ok' if healthy else 'FAIL'}  {reason}")
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
