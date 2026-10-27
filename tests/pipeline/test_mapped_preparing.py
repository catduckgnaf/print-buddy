"""Mapped native start: slow AD5X preparation is reported as accepted/preparing, not a failure."""
import json
from print_handy.core import model_job as mj


def _status(ext, bed):
    return {'result': {'status': {'extruder': {'target': ext}, 'heater_bed': {'target': bed}}}}


def test_preparation_evidence_reads_heater_targets(monkeypatch):
    monkeypatch.setattr(mj, '_mr', lambda st, path, **k: _status(0, 60))
    assert mj._preparation_evidence({}) is True
    monkeypatch.setattr(mj, '_mr', lambda st, path, **k: _status(0, 0))
    assert mj._preparation_evidence({}) is False
    def boom(*a, **k): raise OSError('offline')
    monkeypatch.setattr(mj, '_mr', boom)
    assert mj._preparation_evidence({}) is None
