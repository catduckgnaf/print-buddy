"""Auto light-off policy and Moonraker light commands (#516).

Pure policy, no I/O and no config reads: the Moonraker listener owns the
snapshot, the verdict call and the G-code send, and feeds this module
printer-state transitions and verdicts with an injected clock. Everything
here is unit-testable offline.

The feature, in one paragraph: when ``vision.auto_light_off_minutes`` is
set above zero, a print start turns the printer's light on (state event
only — once the light is off the camera frame is dark, so vision can
never be the on-trigger). When a print reaches a terminal state an idle
window opens; while the printer stays idle the listener checks the plate
on a slow cadence, and only a *sustained* streak of ``empty_idle``
verdicts spanning the configured minutes turns the light off. Any
non-empty verdict resets the streak, and ``uncertain`` resets it too
(conservative: darkness or ambiguity never turns a light off). A part
left on the plate therefore keeps the light on indefinitely, which is
the spec — "nothing on the plate" is a hard condition, no long-idle
override. After lights-out the window closes and checking stops; the
next print start is the wake-up.

Boundary: this is the one deliberate exception to the camera watchdog's
alert-only posture (#455), and it extends to exactly one accessory — the
light. Nothing here touches motion, heaters, pause/stop or a print in
progress, and the listener only consults the policy while the printer
is idle (turn-on at print start aside).
"""
from __future__ import annotations

import re

# Moonraker/Klipper object types that can be a printer light. Names come
# from the printer's own object list (discovery, the #442 precedent) or
# from the operator's vision.light_object setting — never hardcoded.
LIGHT_OBJECT_TYPES = ("led", "neopixel", "output_pin")

# A light object's name part: one word of letters, digits and ``._-``
# (the macros.py argument-value posture), so a configured or discovered
# name can never smuggle a second command, a comment or whitespace into
# the script line this module builds.
_NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*")

DEFAULT_CHECK_INTERVAL_S = 300


def parse_light_object(value):
    """Parse "led chamber_led" into ("led", "chamber_led"); ValueError otherwise.

    Strict on purpose: exactly two whitespace-separated tokens, a known
    light type, and a name matching the safe charset above. Anything
    else — extra tokens, parameters (``led x RED=1``), semicolons,
    newlines — is refused, because the parsed name is interpolated into
    a G-code script.
    """
    if not isinstance(value, str):
        raise ValueError(f"light object must be a string like 'led chamber_led', got {value!r}")
    parts = value.split()
    if len(parts) != 2:
        raise ValueError(f"light object must look like '<type> <name>' (e.g. 'led chamber_led'), "
                         f"got {value!r}")
    kind, name = parts[0].lower(), parts[1]
    if kind not in LIGHT_OBJECT_TYPES:
        raise ValueError(f"light object type must be one of {', '.join(LIGHT_OBJECT_TYPES)}, "
                         f"got {parts[0]!r}")
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"light object name {name!r} is not a single safe word "
                         f"(letters, digits, '.', '_' or '-')")
    return kind, name


def light_scripts(value):
    """(on_script, off_script) for a light object like "led chamber_led".

    led/neopixel switch through SET_LED with every channel driven
    together (on = all channels 1, off = all 0 — the monochrome-safe
    shape for single-colour strips and RGB(W) strips alike);
    output_pin switches through SET_PIN VALUE=1/0.
    """
    kind, name = parse_light_object(value)
    if kind in ("led", "neopixel"):
        return (f"SET_LED LED={name} RED=1 GREEN=1 BLUE=1 WHITE=1",
                f"SET_LED LED={name} RED=0 GREEN=0 BLUE=0 WHITE=0")
    return (f"SET_PIN PIN={name} VALUE=1", f"SET_PIN PIN={name} VALUE=0")


def light_candidates(objects):
    """Light object names ("led chamber_led", ...) from a Moonraker object list.

    The discovery half of the #442 filament-sensor precedent: names come
    from the printer's own objects/list payload, filtered to the light
    types and to names that pass the same strict parse the command
    builder applies — an exotic object name that could not be commanded
    safely is not a candidate.
    """
    if not isinstance(objects, (list, tuple)):
        return []
    found = []
    for name in objects:
        if not isinstance(name, str):
            continue
        try:
            kind, _ = parse_light_object(name)
        except ValueError:
            continue
        found.append(f"{kind} {name.split(None, 1)[1]}")
    return found


def resolve_light_object(configured, objects):
    """Resolve the light target: (object, candidates).

    The operator-configured object wins (validated by the same strict
    parse; an invalid configured value raises ValueError so the caller
    can log it once and stay off). Without one, auto-discovery resolves
    only when the printer lists exactly one candidate — zero or several
    candidates leave the feature unresolved (object None) with the
    candidate list returned for logging, because guessing which of
    several lights is "the" light would switch the wrong one.
    """
    candidates = light_candidates(objects)
    configured = str(configured or "").strip()
    if configured:
        kind, name = parse_light_object(configured)
        return f"{kind} {name}", candidates
    if len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


class AutoLightPolicy:
    """The idle-window state machine. Injected clock: every method takes `now`.

    ``minutes`` <= 0 disables the feature: every method is a no-op and
    nothing is ever returned. ``check_interval_s`` is the idle plate-check
    cadence (default 300s, the listener's suggested ~5 minutes).
    """

    def __init__(self, minutes=0, check_interval_s=DEFAULT_CHECK_INTERVAL_S):
        self.minutes = minutes if isinstance(minutes, int) and minutes > 0 else 0
        self.check_interval_s = (check_interval_s if isinstance(check_interval_s, (int, float))
                                 and check_interval_s > 0 else DEFAULT_CHECK_INTERVAL_S)
        self.printing = False
        self.window_open = False
        self.window_opened_at = None
        self.empty_since = None
        self.last_check_at = None
        self.light_off = False

    @property
    def enabled(self):
        return self.minutes > 0

    def print_started(self, now):
        """A print started: close any window and return "turn_on" (once per print)."""
        if not self.enabled or self.printing:
            return None
        self.printing = True
        self.window_open = False
        self.window_opened_at = None
        self.empty_since = None
        self.last_check_at = None
        self.light_off = False
        return "turn_on"

    def print_finished(self, now):
        """A print reached a terminal state: open the idle window. Returns None."""
        if not self.enabled:
            return None
        self.printing = False
        self.window_open = True
        self.window_opened_at = now
        self.empty_since = None
        # Due immediately: the first check happens at the first tick after
        # the window opens, so the streak span is measured from real checks.
        self.last_check_at = None
        return None

    def should_check(self, now):
        """True when the window is open, the printer is idle, the light is
        still on, and the check interval has elapsed since the last check."""
        if not self.enabled or self.printing or not self.window_open or self.light_off:
            return False
        if self.last_check_at is None:
            return True
        return now - self.last_check_at >= self.check_interval_s

    def note_check(self, now):
        """Record that an idle plate check ran at `now` (whatever its outcome)."""
        self.last_check_at = now

    def note_verdict(self, verdict, now):
        """Feed one plate verdict; returns "turn_off" exactly once, else None.

        Only ``empty_idle`` builds the streak, and lights-out needs the
        streak to *span* at least the configured minutes (first empty
        verdict to this one), not merely the window to be that old — a
        plate first seen empty one minute ago has not been seen empty
        for the configured minutes. Any other verdict, ``uncertain``
        included, resets the streak. Verdicts outside an open idle
        window are ignored.
        """
        if not self.enabled or self.printing or not self.window_open or self.light_off:
            return None
        self.last_check_at = now
        if verdict != "empty_idle":
            self.empty_since = None
            return None
        if self.empty_since is None:
            self.empty_since = now
            return None
        if now - self.empty_since >= self.minutes * 60:
            self.light_off = True
            self.window_open = False
            return "turn_off"
        return None
