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


class JobFamilyMismatch(RuntimeError):
    """A job was prepared for a different printer family than the one configured."""


def job_family(job):
    """Family a JOB.json was prepared for. Jobs written before the field existed are flashforge_zmod."""
    family = job.get("printer_family") if isinstance(job, dict) else None
    return family or DEFAULT_FAMILY


def check_job_family(job, config=None):
    """Raise JobFamilyMismatch unless the job's family is the configured one."""
    want = current(config).family
    have = job_family(job)
    if have != want:
        raise JobFamilyMismatch(f"this job was prepared for {have}, but the configured printer family is {want}")
