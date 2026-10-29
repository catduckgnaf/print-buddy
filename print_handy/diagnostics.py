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
    ``"PH_SPOOLMAN_TRANSIENT"``. Markers are append-only within a
    naming generation: once a marker has shipped in a log line or a
    user-facing message it is not renamed again, so support threads
    stay searchable. The one rename that has happened is #590: the
    ``PB_`` prefix (Print Buddy, the old product name) became ``PH_``
    (Print Handy); docs/DIAGNOSTICS.md carries the old -> new alias
    table so old reports stay searchable too.
    """
    return f"PH_{_token(subsystem)}_{Category(category).value.upper()}"


class KnownCause:
    """A recognised, operator-fixable cause for one failure (#590).

    ``cause`` says in plain words what went wrong and ``remedy`` says
    what to do about it; both are written here, in this module, from
    the recognised pattern — never copied out of raw exception text,
    so nothing internal (paths beyond the named token files, secrets,
    tracebacks) can ride along into chat.
    """

    __slots__ = ("category", "cause", "remedy")

    def __init__(self, category: Category, cause: str, remedy: str):
        self.category = Category(category)
        self.cause = cause
        self.remedy = remedy


#: Model sites whose curated token/auth failures carry a specific,
#: user-safe message (print_handy.core.model_job raises them): the
#: site name, the credential the operator must set up, and the
#: docs/PROJECT-REFERENCE.md section that explains it.
_SITE_CREDENTIALS = (
    ("MakerWorld", "MakerWorld account token", "MakerWorld account token"),
    ("Thingiverse", "Thingiverse App Token", "Thingiverse App Token"),
    ("MyMiniFactory", "MyMiniFactory API key", "MyMiniFactory API key"),
    ("Cults3D", "Cults3D API key", "Cults3D API key"),
)

_CREDENTIAL_CUES = ("token", "api key", "app token", "credentials", "nickname")
_CREDENTIAL_PROBLEMS = ("need", "missing", "empty", "refused", "401", "403",
                        "must contain", "invalid", "expired", "no api key",
                        "needs an api key first", "is wrong")

#: Download gaps that are a property of the site, not of the install:
#: the remedy is a browser download, never a retry.
_SITE_DOWNLOAD_GAPS = (
    ("MyMiniFactory",
     "MyMiniFactory only lets a logged-in account download its files, and that "
     "login route is not built in Print Handy, so the file cannot be fetched from here."),
    ("Cults3D",
     "Cults3D's API gives a listing's details but never its 3D files, so the "
     "file cannot be fetched from here."),
)


def known_cause(exc: BaseException) -> KnownCause | None:
    """The recognised operator-fixable cause of ``exc``, or None.

    Recognition is an allowlist over the curated, operator-phrased
    messages Print Handy itself raises at its model-site boundaries
    (#590): a missing/expired/refused site credential, a site robot
    check, or a site's built-in download gap. Anything else returns
    None and keeps the conservative ``unknown`` treatment — an
    unrecognised exception's text is never surfaced in chat.
    """
    text = str(exc or "")
    low = text.lower()
    for site, gap in _SITE_DOWNLOAD_GAPS:
        if site.lower() in low and "cannot download" in low:
            return KnownCause(
                Category.CONFIGURATION,
                gap,
                "Download the .stl or .3mf file from the model page in a browser, "
                "then upload or drop that file here instead.")
    for site, credential, section in _SITE_CREDENTIALS:
        if site.lower() not in low:
            continue
        challenged = "robot check" in low or "cloudflare" in low or "challenging" in low
        if challenged and "refused" not in low and "401" not in low and "403" not in low:
            return KnownCause(
                Category.TRANSIENT,
                f"{site} is challenging this connection with a robot check, so "
                "Print Handy could not fetch the model.",
                f"Open {site} in a browser and pass any check there, and check the "
                f"{credential} (see \"{section}\" in docs/PROJECT-REFERENCE.md). "
                "Print Handy does not try to bypass robot checks.")
        if not any(cue in low for cue in _CREDENTIAL_CUES):
            continue
        if any(cue in low for cue in _CREDENTIAL_PROBLEMS):
            return KnownCause(
                Category.CONFIGURATION,
                f"{site} links need your {credential}, and it is missing, empty "
                "or was refused.",
                f"Set up the {credential} — see \"{section}\" in "
                "docs/PROJECT-REFERENCE.md. Until it is in place, "
                f"{site} links cannot be fetched.")
    if type(exc).__name__ == "SpoolmanUnavailable":
        if "not configured" in low:
            return KnownCause(
                Category.CONFIGURATION,
                "Spoolman is not configured: services.spoolman_url is empty.",
                "Set services.spoolman_url to your Spoolman service, then try again.")
        return KnownCause(
            Category.TRANSIENT,
            "Spoolman did not answer.",
            "Check that the Spoolman service is running and that "
            "services.spoolman_url points at it.")
    return None


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
    known = known_cause(exc)
    if known is not None:
        return known.category
    code = getattr(exc, "code", None)  # urllib HTTPError and friends
    if isinstance(code, int):
        if code in (401, 403):
            return Category.CONFIGURATION
        if code == 429 or code >= 500:
            return Category.TRANSIENT
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return Category.TRANSIENT
    if isinstance(exc, OSError):
        return Category.TRANSIENT if exc.errno in TRANSIENT_ERRNOS else Category.UNKNOWN
    return Category.UNKNOWN


def next_step_for(exc: BaseException, *, transient: str, other: str) -> str:
    """Pick a post's next step by whether retrying can actually help (#590).

    ``transient`` (worded by the caller, e.g. "send it again") is only
    honest for a transient failure; every other category gets
    ``other`` — for a known cause that is the cause's own remedy, and
    for an unknown failure the caller's non-retry step (typically the
    diagnostics bundle hint).
    """
    known = known_cause(exc) if exc is not None else None
    if known is not None:
        return known.remedy
    if exc is not None and classify(exc) == Category.TRANSIENT:
        return transient
    return other


def known_post(first_line: str, *, not_happened: str | None = None,
               subsystem: str, exc: BaseException) -> str | None:
    """A plain post naming the recognised cause of ``exc``, or None (#590).

    When :func:`known_cause` recognises the failure, the post leads
    with ``first_line``, states the cause in plain words, and gives
    the cause's remedy as the next step — no retry advice for a
    failure retrying cannot fix. Returns None when the cause is not
    recognised, so the caller falls back to its generic wording.
    """
    known = known_cause(exc)
    if known is None:
        return None
    return plain_post(f"{first_line} {known.cause}",
                      not_happened=not_happened,
                      next_step=known.remedy,
                      subsystem=subsystem, exc=exc)


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
    the post ends with the stable greppable ``PH_*`` marker (classified
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
