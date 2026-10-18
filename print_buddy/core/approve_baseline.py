#!/usr/bin/env python3
"""Approve protected settings from an offline Orca G-code artifact.

Run from the repository root: python3 -m print_buddy.core.approve_baseline approve-baseline <artifact>
"""
import sys
from pathlib import Path

from .slice_guard import approve_baseline


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "approve-baseline":
        raise SystemExit("Usage: python3 -m print_buddy.core.approve_baseline approve-baseline <artifact>")
    approve_baseline(Path(argv[1]))


if __name__ == "__main__":
    main()
