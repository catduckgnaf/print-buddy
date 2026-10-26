"""Transactional launch state: consumed bed-clear approvals and one submission lease per printer.

One small SQLite database per printer, under <state>/printers/<id>/jobs.db (#334, design §2.4),
so the check and the write happen in one transaction across processes (the bot, print_next
children, a CLI print-now) and one printer's lease or approval table can never leak into
another's. JOB.json keeps its human-readable approvals list; model archives stay ordinary files.

Upgrade adoption: the first time the default printer's database is opened and it does not
exist yet, the legacy single database (<state>/print_buddy_launches.sqlite3) is copied into
place — held lease and consumed approvals intact — and the legacy file is left untouched for
one release so a rollback still finds it. $PRINT_BUDDY_LAUNCH_DB keeps naming one explicit
database and disables the per-printer layout (tests and operator overrides).

Lease phases: ``leased`` (checks and upload, nothing started), ``submitting`` (persisted before the
start request), ``uncertain`` (sent, outcome unknown). A confirmed or failed start deletes the row.
An unfinished ``leased`` row whose process is gone is released: nothing was sent. A ``submitting``
or ``uncertain`` row is never released by guessing and never replayed. It is reconciled when the
printer reports that exact file, or by the operator with ``model_job reconcile-launch``.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .. import settings

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS approvals (job_json TEXT NOT NULL, gcode_sha256 TEXT NOT NULL, "
    "kind TEXT NOT NULL, consumed_at TEXT NOT NULL, pid INTEGER)",
    "CREATE TABLE IF NOT EXISTS leases (printer TEXT PRIMARY KEY, token TEXT NOT NULL, phase TEXT NOT NULL, "
    "job_json TEXT, gcode_sha256 TEXT, remote TEXT, pid INTEGER, host TEXT, leased_at TEXT, updated_at TEXT, "
    "detail TEXT)",
)


def _adopt_legacy_db(target, printer_id):
    """Copy the legacy single launch database into the default printer's folder, once.

    Only the default printer adopts it: the legacy database was the singleton
    printer's, and copying it to a second printer would duplicate its held
    lease and consumed approvals. The legacy file (and any WAL sidecars) is
    left in place for one release.
    """
    if printer_id != settings.default_printer_id():
        return
    legacy = settings.state_dir() / "print_buddy_launches.sqlite3"
    if target.exists() or not legacy.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".adopting")
    shutil.copy2(legacy, tmp)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(legacy) + suffix)
        if sidecar.is_file():
            shutil.copy2(sidecar, Path(str(tmp) + suffix))
    os.replace(tmp, target)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(tmp) + suffix)
        if sidecar.is_file():
            os.replace(sidecar, Path(str(target) + suffix))


def db_path(printer_id=None):
    """The launch database for one printer: $PRINT_BUDDY_LAUNCH_DB, else its per-printer jobs.db."""
    override = os.environ.get("PRINT_BUDDY_LAUNCH_DB")
    if override:
        return Path(override)
    printer_id = printer_id or settings.default_printer_id()
    target = settings.printer_state_dir(printer_id) / "jobs.db"
    _adopt_legacy_db(target, printer_id)
    return target


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


@contextmanager
def transaction(printer_id=None):
    """One exclusive write transaction on one printer's database.

    Every launch-state check-then-write runs inside one.
    """
    path = db_path(printer_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=60, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN IMMEDIATE")
        for statement in SCHEMA:
            con.execute(statement)
        try:
            yield con
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
    finally:
        con.close()


def consumed(con, job_json, gcode_sha256):
    return [dict(r) for r in con.execute("SELECT * FROM approvals WHERE job_json=? AND gcode_sha256=? ORDER BY rowid",
                                         (str(job_json), gcode_sha256))]


def record_consumed(con, job_json, gcode_sha256, kind, when):
    con.execute("INSERT INTO approvals VALUES (?,?,?,?,?)", (str(job_json), gcode_sha256, kind, when, os.getpid()))


def _owner_alive(row, unknown=True):
    """Whether the lease's process still runs. Another host or container cannot be checked: unknown."""
    if row["host"] != socket.gethostname():
        return unknown
    try:
        os.kill(int(row["pid"]), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, TypeError, ValueError):
        return True
    return True


def _describe(row):
    return f"job {row['job_json'] or 'unknown'}, file {row['remote'] or 'unknown'}, since {row['leased_at']}"


class Lease:
    """The one launch allowed on a printer right now. Every update is scoped to this lease's token."""

    def __init__(self, printer, token):
        self.printer, self.token = printer, token

    def _set(self, phase, detail=None):
        with transaction(self.printer) as con:
            con.execute("UPDATE leases SET phase=?, detail=?, updated_at=? WHERE printer=? AND token=?",
                        (phase, detail, _now(), self.printer, self.token))

    def submitting(self):
        """Persist before the external start request: from here a crash is uncertain, not retried."""
        self._set("submitting")

    def uncertain(self, detail):
        self._set("uncertain", str(detail)[-500:])

    def release(self):
        with transaction(self.printer) as con:
            con.execute("DELETE FROM leases WHERE printer=? AND token=?", (self.printer, self.token))


def acquire(printer, *, job_json=None, gcode_sha256=None, remote=None, observed_file=None):
    """Take the printer's lease or refuse. observed_file is the file the printer reports right now.

    `printer` is the roster printer id (#334): the lease lives in that
    printer's own database and its row is keyed by the id.
    """
    with transaction(printer) as con:
        row = con.execute("SELECT * FROM leases WHERE printer=?", (printer,)).fetchone()
        if row is not None:
            if row["phase"] == "leased" and not _owner_alive(row):
                print(f"LAUNCH LEASE RELEASED: an earlier launch stopped before submission ({_describe(row)}).", flush=True)
            elif row["phase"] != "leased" and row["remote"] and observed_file == row["remote"]:
                print(f"LAUNCH RECONCILED: the printer reports {row['remote']}, so the earlier {row['phase']} "
                      "submission reached it. Not resubmitted.", flush=True)
            elif row["phase"] == "leased" or (row["phase"] == "submitting" and _owner_alive(row)):
                raise SystemExit(f"REFUSED: another launch on this printer is in progress ({_describe(row)}). "
                                 "Nothing uploaded or started.")
            else:
                raise SystemExit(f"REFUSED: an earlier start on this printer is uncertain ({_describe(row)}). "
                                 "Check the printer, then run `python3 -m print_buddy.core.model_job reconcile-launch "
                                 "--started` or `--not-started`. It is never resubmitted automatically. "
                                 "Nothing uploaded or started.")
            con.execute("DELETE FROM leases WHERE printer=?", (printer,))
        token = uuid.uuid4().hex
        now = _now()
        con.execute("INSERT INTO leases VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (printer, token, "leased", str(job_json) if job_json else None, gcode_sha256, remote,
                     os.getpid(), socket.gethostname(), now, now, None))
    return Lease(printer, token)


def pending(printer=None):
    """Held leases: one printer's, or every roster printer's when none is named."""
    if printer is not None or os.environ.get("PRINT_BUDDY_LAUNCH_DB"):
        with transaction(printer) as con:
            rows = con.execute("SELECT * FROM leases" + (" WHERE printer=?" if printer else ""),
                               (printer,) if printer else ()).fetchall()
        return [dict(r) for r in rows]
    found = []
    for entry in settings.printers():
        path = settings.printer_state_dir(entry["id"]) / "jobs.db"
        if not path.is_file():
            continue  # a printer that never launched has no database yet; reading must not create one
        with transaction(entry["id"]) as con:
            found += [dict(r) for r in con.execute("SELECT * FROM leases").fetchall()]
    return found


def resolve(printer, outcome):
    """Operator reconciliation of an uncertain start. Clears the lease; consumed approvals stay consumed."""
    if outcome not in ("started", "not_started"):
        raise ValueError("outcome must be started or not_started")
    with transaction(printer) as con:
        row = con.execute("SELECT * FROM leases WHERE printer=?", (printer,)).fetchone()
        if row is None:
            raise SystemExit("No launch is pending on this printer; nothing to reconcile.")
        if row["phase"] == "leased" and _owner_alive(row, unknown=False):  # the operator vouches for other hosts
            raise SystemExit(f"REFUSED: that launch is still running ({_describe(row)}); nothing changed.")
        con.execute("DELETE FROM leases WHERE printer=?", (printer,))
    out = dict(row, reconciled=outcome, reconciled_at=_now())
    print("LAUNCH RECONCILED " + json.dumps(out), flush=True)
    return out
