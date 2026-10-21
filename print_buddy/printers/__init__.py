"""Printer models, one module per printer inside a brand package. See base.py for the contract and the responsibility map.

    from print_buddy import printers
    printers.current().build_volume()
    printers.MODELS["flashforge.ad5x"].defaults()

Every brand package (flashforge/, sovol/, klipper/) is scanned; each module in it that defines MODEL is
registered under its "brand.model" key. Adding a printer is one new file there plus its templates.
"""
from __future__ import annotations

import importlib
import pkgutil

from .base import MultiColorUnsupported, PrinterAdapter, PrinterModel

# Jobs written before the model was recorded were sliced for the AD5X.
DEFAULT_MODEL = "flashforge.ad5x"


def _discover():
    found = {}
    for brand in pkgutil.iter_modules(__path__):
        if not brand.ispkg:
            continue
        package = importlib.import_module(f"{__name__}.{brand.name}")
        for module in pkgutil.iter_modules(package.__path__):
            if module.ispkg:
                continue
            model = getattr(importlib.import_module(f"{package.__name__}.{module.name}"), "MODEL", None)
            if model is None:
                continue
            if model.key != f"{brand.name}.{module.name}":
                raise RuntimeError(f"{package.__name__}.{module.name}: MODEL key {model.key!r} must be "
                                   f"{brand.name}.{module.name}")
            found[model.key] = model
    return dict(sorted(found.items()))


MODELS: dict[str, PrinterModel] = _discover()


def model(key):
    """The PrinterModel registered under a "brand.model" key."""
    if key not in MODELS:
        raise ValueError(f"unknown printer model {key!r}; expected one of {', '.join(MODELS)}")
    return MODELS[key]


def get(key, config=None):
    """Adapter for a model key, built on `config` (default: the process settings)."""
    selected = model(key)
    return selected.adapter(config, selected)


def current(config=None):
    """The adapter selected by [printer] model."""
    from .. import settings
    config = config or settings.current()
    return get(config["printer"]["model"], config)


class JobModelMismatch(RuntimeError):
    """A job was prepared for a different printer model than the one configured."""


# JOB.json written by 2.0.2 and 2.0.3 records printer_family instead of printer_model.
LEGACY_FAMILY = {"flashforge_zmod": "flashforge.ad5x", "sovol_klipper": "sovol.sv06",
                 "generic_klipper": "klipper.generic"}


def job_model(job):
    """Model a JOB.json was prepared for. Jobs older than either field are flashforge.ad5x."""
    if not isinstance(job, dict):
        return DEFAULT_MODEL
    return job.get("printer_model") or LEGACY_FAMILY.get(job.get("printer_family")) or DEFAULT_MODEL


def check_job_model(job, config=None):
    """Raise JobModelMismatch unless the job's model is the configured one."""
    want = current(config).key
    have = job_model(job)
    if have != want:
        raise JobModelMismatch(f"this job was prepared for {have}, but the configured printer model is {want}")
