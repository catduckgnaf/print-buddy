#!/usr/bin/env python3
"""Diff-scoped US-spelling check for prose (Markdown) changes; stdlib only.

catduck's rule (2026-10-29): prose written for this project uses American
spellings for the color/honor family -- color, honor, behavior -- not the
British forms. This check scans only the lines a change ADDS to Markdown
files (plus, optionally, a PR description saved to a file), so the British
spellings that already exist in shipped docs, and the `colour` code/domain
identifiers in Python, are untouched and unrelated branches stay green.

BRITISH_TO_US below is the single place that defines the word list; extend
it there. Matching is whole-word and case-insensitive, so a longer token
that merely contains these letters (an identifier, a file name) never
matches. Deliberately not listed: "centre" -- it sits outside the family
named for this rule and shows up in quoted upstream material; add it to
the map if the rule is ever extended to cover it.

Exception: a line that must keep a British spelling (quoted upstream text,
an exact identifier) carries an HTML comment naming the allowed word(s):

    <!-- us-spelling: allow colour -->

A bare `<!-- us-spelling: allow -->` allows every listed word on that one
line. HTML comments are otherwise ignored by the scan, like the
contribution-policy check ignores them in PR bodies.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

# British spelling -> American spelling. The one place to extend the list.
BRITISH_TO_US = {
    "colour": "color",
    "colours": "colors",
    "coloured": "colored",
    "colouring": "coloring",
    "honour": "honor",
    "honours": "honors",
    "honoured": "honored",
    "honouring": "honoring",
    "honourable": "honorable",
    "behaviour": "behavior",
    "behaviours": "behaviors",
    "favour": "favor",
    "favours": "favors",
    "favoured": "favored",
    "favouring": "favoring",
    "favourite": "favorite",
    "favourites": "favorites",
    "neighbour": "neighbor",
    "neighbours": "neighbors",
    "neighbouring": "neighboring",
    "recognise": "recognize",
    "recognises": "recognizes",
    "recognised": "recognized",
    "recognising": "recognizing",
    "organise": "organize",
    "organises": "organizes",
    "organised": "organized",
    "organising": "organizing",
}

_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(BRITISH_TO_US, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_ALLOW_MARKER = re.compile(r"<!--\s*us-spelling:\s*allow\b(.*?)-->", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def match_replacement(found):
    """The American replacement, keeping the found word's capitalization."""
    replacement = BRITISH_TO_US[found.casefold()]
    if found.isupper():
        return replacement.upper()
    if found[:1].isupper():
        return replacement.capitalize()
    return replacement


def line_violations(text):
    """British spellings on one line of prose, honoring the allow marker."""
    allowed = set()
    allow_all = False
    marker = _ALLOW_MARKER.search(text)
    if marker:
        words = {word.casefold() for word in re.findall(r"[A-Za-z]+", marker.group(1))}
        if words:
            allowed = words
        else:
            allow_all = True
    if allow_all:
        return []
    prose = _COMMENT.sub("", text)
    return [
        (match.group(0), match_replacement(match.group(0)))
        for match in _PATTERN.finditer(prose)
        if match.group(0).casefold() not in allowed
    ]


def text_violations(text, source):
    """(source, line, found, replacement) for every line of a text block."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for word, replacement in line_violations(line):
            found.append((source, number, word, replacement))
    return found


def diff_violations(diff_text):
    """Violations on lines a unified diff adds to Markdown files.

    Context and removed lines are never scanned: British spellings that a
    change does not touch are not its problem.
    """
    found = []
    path = None
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++"):
            target = raw[3:].strip()
            if target == "/dev/null":
                path = None
            else:
                if target.startswith("b/"):
                    target = target[2:]
                path = target if target.endswith(".md") else None
            continue
        hunk = _HUNK.match(raw)
        if hunk:
            new_line = int(hunk.group(1))
            continue
        if path is None:
            continue
        if raw.startswith("+"):
            for word, replacement in line_violations(raw[1:]):
                found.append((path, new_line, word, replacement))
            new_line += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            continue
        else:  # context line: present in the new file, but not added
            new_line += 1
    return found


def git_diff(base):
    result = subprocess.run(
        ["git", "diff", "--unified=3", "--no-color", f"{base}...HEAD", "--", "*.md"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git diff against {base!r} failed: {result.stderr.strip()}")
    return result.stdout


def format_violation(violation):
    source, line, word, replacement = violation
    return f"{source}:{line}: British spelling '{word}' -- use '{replacement}' instead"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", help="Git ref to diff HEAD against (three-dot), e.g. origin/main")
    group.add_argument("--diff-file", help="Read a unified diff from this file instead of running git")
    parser.add_argument("--body-file", help="Also scan this text file line by line (e.g. a PR description)")
    args = parser.parse_args(argv)

    violations = []
    if args.base:
        violations += diff_violations(git_diff(args.base))
    else:
        violations += diff_violations(Path(args.diff_file).read_text(encoding="utf-8"))
    if args.body_file:
        violations += text_violations(
            Path(args.body_file).read_text(encoding="utf-8"), "PR description"
        )

    for violation in violations:
        print(format_violation(violation))
    if violations:
        print(
            f"\n{len(violations)} British spelling(s) in added prose. Use the American "
            "spelling, or mark a line that must keep the British form with "
            "<!-- us-spelling: allow <word> --> (see scripts/check_us_spelling.py).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
