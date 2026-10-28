"""Error taxonomy, greppable markers and operator messages (#390, Stage 1).

The diagnostics overhaul's foundation. Before #390, Print Handy's worst
failures were silent or unhelpful ones (#373, #364, #384): the system knew
something was wrong and said nothing useful about it. This module is the
shared vocabulary every later stage uses:

* a small **taxonomy** — every failure at a main boundary is one of
  ``transient``, ``configuration``, ``hardware`` or ``programming``
  (``unknown`` when nothing honest can be said yet);
* a stable, greppable **marker** per (subsystem, category) pair, in the
  spirit of the ``DISCORD_STARTUP_RETRY`` log line from #369, so a support
  conversation can start from one searchable string;
* an **operator message** builder enforcing the Discord-message bar from
  #390 scope 1: what failed, the most likely cause, and what the operator
  can do about it — never bare exception text, never a silent drop.

Nothing here changes print-path behaviour: classification and formatting
only, and every string that leaves this module is passed through
``print_handy.logs.redact`` so no secret material can ride along.
"""
from __future__ import annotations

import errno
import re
import socket
from enum import Enum

from . import logs


class Category(str, Enum):
    TRANSIENT = "transient"
    CONFIGURATION = "configuration"
    HARDWARE = "hardware"
    PROGRAMMING = "programming"
    UNKNOWN = "unknown"


#: Errnos that mean "the network hiccuped", mirroring the Discord startup
#: retry classification in print_handy.bot.client (#364).
TRANSIENT_ERRNOS = frozenset({
    getattr(socket, "EAI_AGAIN", -3),
    errno.EAGAIN, errno.EWOULDBLOCK, errno.ECONNABORTED, errno.ECONNREFUSED,
    errno.ECONNRESET, errno.EHOSTUNREACH, errno.ENETUNREACH, errno.ETIMEDOUT,
})

#: Default remedy per category, used when a boundary has nothing more
#: specific to say. Wording is operator-facing: an action, not a diagnosis.
DEFAULT_REMEDIES = {
    Category.TRANSIENT: "Wait a moment and try again; if it keeps happening, "
                        "check the network connection between Print Handy and the service.",
    Category.CONFIGURATION: "Check the named setting in your Print Handy configuration, "
                            "then run `python3 -m print_handy.doctor` (or `/print-handy debugging`) to confirm.",
    Category.HARDWARE: "Check the printer and its connection; no print was started by this message.",
    Category.PROGRAMMING: "This looks like a Print Handy bug. Please file a bug report with the "
                          "reference marker below and the diagnostics bundle (see docs/DIAGNOSTICS.md).",
    Category.UNKNOWN: "Run `python3 -m print_handy.doctor` (or `/print-handy debugging`) for a "
                      "check-by-check diagnosis, and include the reference marker below in any report.",
}

#: Markers that predate this module and must never be renamed: support
#: history and tests already search for them.
LEGACY_MARKERS = {
    "DISCORD_STARTUP_RETRY": "Discord login failed transiently at startup and is being retried (#364/#369).",
}

_SUBSYSTEM_RE = re.compile(r"[^A-Z0-9]+")


def _token(text: str) -> str:
    return _SUBSYSTEM_RE.sub("_", str(text).upper()).strip("_") or "GENERAL"


def marker(subsystem: str, category: Category) -> str:
    """The stable greppable marker for one subsystem/category pair.

    Example: ``marker("spoolman", Category.TRANSIENT)`` is
    ``"PB_SPOOLMAN_TRANSIENT"``. Markers are append-only: once a marker
    has shipped in a log line or a user-facing message it is never
    renamed, so old support threads stay searchable.
    """
    return f"PB_{_token(subsystem)}_{Category(category).value.upper()}"


def classify(exc: BaseException, *, category: Category | None = None) -> Category:
    """Classify one failure. An explicit ``category`` always wins.

    The heuristic fallback is deliberately conservative: transport and
    timeout failures are transient, Print Handy's own settings errors are
    configuration, and anything unrecognised is ``unknown`` rather than
    a guessed cause — a boundary that knows better passes its category
    explicitly.
    """
    if category is not None:
        return Category(category)
    from . import settings  # lazy: settings is imported by nearly everything
    if isinstance(exc, settings.SettingsError):
        return Category.CONFIGURATION
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return Category.TRANSIENT
    if isinstance(exc, OSError):
        return Category.TRANSIENT if exc.errno in TRANSIENT_ERRNOS else Category.UNKNOWN
    return Category.UNKNOWN


def plain_post(first_line: str, *, not_happened: str | None = None,
               next_step: str | None = None, subsystem: str | None = None,
               exc: BaseException | None = None,
               category: Category | None = None) -> str:
    """One user-facing failure/refusal post meeting the #467 plain-language bar.

    The first line says in plain words what the person asked for and what
    happened — no exception class names, no raw exception or stderr text,
    no ALL-CAPS prefix, no internal jargon. ``not_happened`` states what
    did *not* happen where that matters ("Nothing was uploaded or
    started."), and ``next_step`` gives the one clear thing to do next.
    Technical detail is demoted, not deleted: when ``subsystem`` is named
    the post ends with the stable greppable ``PB_*`` marker (classified
    from ``exc`` when given, never its text), and the full detail stays in
    the log and the diagnostics bundle, where the caller already put it.

    This is the shared builder for chat posts; the Discord action
    handlers' ``_failure_post`` (#390) and the intake/guided surfaces use
    it so there is one wording system, not two.
    """
    lines = [str(first_line).strip()]
    tail = " ".join(part.strip() for part in (not_happened, next_step) if part and part.strip())
    if tail:
        lines.append(tail)
    if subsystem is not None:
        resolved = classify(exc, category=category) if exc is not None else (
            Category(category) if category is not None else Category.UNKNOWN)
        lines.append(f"Reference: {marker(subsystem, resolved)}")
    return logs.redact("\n".join(lines))


def operator_message(what: str, *, subsystem: str,
                     category: Category | None = None,
                     exc: BaseException | None = None,
                     cause: str | None = None,
                     remedy: str | None = None) -> str:
    """One user-facing failure message meeting the #390 bar.

    ``what`` names what failed (never a bare exception string). The result
    always carries the likely cause line (from ``cause``, else the
    exception type — never its raw text, which can embed secrets or
    internals), an actionable remedy line, and the greppable marker.
    The whole message is redacted before it is returned.
    """
    resolved = classify(exc, category=category) if exc is not None else (
        Category(category) if category is not None else Category.UNKNOWN)
    if cause is None:
        cause = (f"{type(exc).__name__} while talking to {subsystem}" if exc is not None
                 else "the cause is not known yet")
    lines = [f"⚠ {what}",
             f"Likely cause: {cause} ({resolved.value}).",
             f"What to do: {remedy or DEFAULT_REMEDIES[resolved]}",
             f"Reference: {marker(subsystem, resolved)}"]
    return logs.redact("\n".join(lines))
