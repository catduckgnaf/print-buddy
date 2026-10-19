"""Pluggable printer families. See base.py for the adapter contract and the responsibility map.

    from print_buddy import printers
    printers.current().build_volume()
"""
from __future__ import annotations

import importlib

from .families import DEFAULT_FAMILY, FAMILIES

_CLASSES = {
    "flashforge_zmod": ("flashforge_zmod", "FlashforgeZmodAdapter"),
    "generic_klipper": ("generic_klipper", "GenericKlipperAdapter"),
    "sovol_klipper": ("sovol_klipper", "SovolKlipperAdapter"),
}


def get(family, config=None):
    """Adapter for a family name, built on `config` (default: the process settings)."""
    if family not in _CLASSES:
        raise ValueError(f"unknown printer family {family!r}; expected one of {', '.join(FAMILIES)}")
    module, cls = _CLASSES[family]
    return getattr(importlib.import_module(f".{module}", __name__), cls)(config)


def current(config=None):
    """The adapter selected by [printer] family."""
    from .. import settings
    config = config or settings.current()
    return get(config["printer"]["family"], config)
