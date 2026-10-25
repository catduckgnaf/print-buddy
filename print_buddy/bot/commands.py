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
    Command("print-buddy", "Guided setup and read-only debugging (never prints)",
            (Option("action", "setup, debugging, status, cancel or help",
                    ("setup", "debugging", "status", "cancel", "help")),),
            "/print-buddy [setup | debugging | status | cancel | help]"),
    Command("print-help", "What Print Buddy can do", usage="/print-help"),
)


def by_name(name):
    return next((c for c in COMMANDS if c.name == name), None)


def as_text(name, values):
    """The typed form of a slash command: '/spool change 1 12'."""
    command = by_name(name)
    args = [str(values.get(o.name) or "").strip() for o in (command.options if command else ())]
    return " ".join(["/" + name] + [a for a in args if a])


def help_text(bot_name="Print Buddy"):
    lines = [f"**{bot_name}** prints from this channel. Nothing starts without a button press.",
             "- Post a MakerWorld or Printables link, or drop one .3mf or .stl file, to slice and print it.",
             '- "print it" after a link, or "print the last one again", reuses the last model.']
    lines += [f"- `{c.usage}`: {c.description}" for c in COMMANDS if c.name != "print-help"]
    return "\n".join(lines)
