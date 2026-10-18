#!/usr/bin/env python3
"""Approve protected settings from an offline Orca G-code artifact."""
import sys
from pathlib import Path
from slice_guard import approve_baseline

if len(sys.argv) != 3 or sys.argv[1] != "approve-baseline":
    raise SystemExit("Usage: slice_guard.py approve-baseline <artifact>")
approve_baseline(Path(sys.argv[2]))
