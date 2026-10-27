"""The slash commands the standalone bot registers, and the help text it answers unmatched messages with.

Each slash command becomes the same text a person could type ("/print-stop"), so one handler serves both.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Option:
    name: str
    description: str
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    options: tuple[Option, ...] = ()
    usage: str = ""
    # Short names for the same command (#388 close-out): an alias registers,
    # parses and answers exactly like the canonical name — slash registration,
    # the typed form and help all derive from this one table entry.
    aliases: tuple[str, ...] = ()


COMMANDS = (
    Command("print-next", "Offer the next plate of a multi plate plan behind one bed-clear button",
            (Option("plan_id", "Plan id from the completion message"),
             Option("part_id", "A specific plate (optional)")), "/print-next <plan_id> [part_id]"),
    Command("print-stop", "Stop the current print (asks first)", usage="/print-stop"),
    Command("print-resume", "Resume a paused print (asks first)", usage="/print-resume"),
    Command("print-again", "Reprint an archived job, or list recent ones",
            (Option("query", "list, a number from the list, a name, or 'next'; add x3 for copies"),),
            "/print-again [list | N | name]"),
    Command("print-reboot", "Safe printer restart (asks first)", usage="/print-reboot"),
    Command("print-coldpull", "Guided cold pull at the printer (asks first)", usage="/print-coldpull"),
    Command("print-maintenance", "Guided maintenance checklist",
            (Option("mode", "full or quick", ("full", "quick")),), "/print-maintenance [full | quick]"),
    Command("print-colors", "Choose part colors for an archived job",
            (Option("job", "Path to the archived JOB.json"),), "/print-colors <JOB.json>"),
    Command("spool", "List, change, add or sync spools (never moves the printer)",
            (Option("args", "list | change <slot> <spool#> | new brand, material, color, grams | sync"),),
            "/spool [list | change <slot> <spool#> | new ... | sync]"),
    Command("print-lookup", "Look up a firmware command, macro, error, symptom or printer (read-only, sends nothing)",
            (Option("query", "e.g. M600, zmod ifs load, bed mesh klipper, first layer not sticking"),),
            "/print-lookup <query>"),
    Command("print-troubleshoot", "Guided step-by-step physical troubleshooting (advice only, sends nothing)",
            (Option("flow", "Which problem", ("first-layer", "clog", "heat-creep", "bed-level", "ringing")),),
            "/print-troubleshoot [first-layer | clog | heat-creep | bed-level | ringing]"),
    Command("print-macros", "List the macros your Moonraker printer actually defines, or run one by name (run asks first)",
            (Option("args", "run <name> [KEY=VALUE ...]"),),
            "/print-macros [run <name> [KEY=VALUE ...]]"),
    Command("print-live", "Start, stop or check the live camera view in the Discord voice channel (Discord only)",
            (Option("action", "start, stop or status", ("start", "stop", "status")),),
            "/print-live [start | stop | status]"),
    Command("print-design", "Design a part, or edit a dropped/linked model, with AI + OpenSCAD (asks before slicing)",
            (Option("prompt", "What to make or change, e.g. a 40x20x3 plate with two 4 mm holes, or 'make it taller' with a file dropped"),),
            "/print-design <what to make or change>", aliases=("design",)),
    Command("print-handy", "Guided setup and read-only debugging (never prints)",
            (Option("action", "setup, debugging, bundle, debug, status, cancel or help",
                    ("setup", "debugging", "bundle", "debug", "status", "cancel", "help")),),
            "/print-handy [setup | debugging | bundle | debug on/off/status | status | cancel | help]"),
    Command("print-help", "What Print Handy can do", usage="/print-help"),
)


def by_name(name):
    return next((c for c in COMMANDS if c.name == name or name in c.aliases), None)


def registrations():
    """(name, command) for every slash registration: canonical names, then aliases."""
    return [(c.name, c) for c in COMMANDS] + \
        [(alias, c) for c in COMMANDS for alias in c.aliases]


def as_text(name, values):
    """The typed form of a slash command: '/spool change 1 12'."""
    command = by_name(name)
    args = [str(values.get(o.name) or "").strip() for o in (command.options if command else ())]
    return " ".join(["/" + name] + [a for a in args if a])


def help_text(bot_name="Print Handy"):
    lines = [f"**{bot_name}** prints from this channel. Nothing starts without a button press.",
             "- Post a MakerWorld or Printables link, or drop one .3mf or .stl file, to slice and print it.",
             '- "print it" after a link, or "print the last one again", reuses the last model.',
             '- "print 57" (or "print #57") reprints print #57, exactly like "/print-again 57".']
    lines += [f"- `{c.usage}`: {c.description}"
              + (f" (also `/{c.aliases[0]}`)" if c.aliases else "")
              for c in COMMANDS if c.name != "print-help"]
    return "\n".join(lines)
