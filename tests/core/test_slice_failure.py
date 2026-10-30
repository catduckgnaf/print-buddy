"""Failures must retain their cause without putting raw worker output in chat."""
import asyncio
import json
import subprocess
import sys

import pytest

from print_handy import diagnostics
from print_handy.core import owned_worker, prepared_intake, slice_failure, worker_errors
from print_handy.core.resources import ResourceLimitError
from print_handy.core.slice_refusal import unconfirmed_slot_color


@pytest.mark.parametrize('error,category,phrase', [
    (subprocess.TimeoutExpired(['secret-command'], 600), 'transient', 'time limit'),
    (ResourceLimitError('container is at its process limit SECRET'), 'configuration', 'process limit'),
    (TypeError('SECRET implementation detail'), 'programming', 'internal error'),
    (slice_failure.SliceFailure('SECRET stderr', kind='guard'), 'configuration', 'safety check'),
    (slice_failure.SliceFailure('SECRET stderr', kind='engine', slicer='OrcaSlicer'), 'unknown', 'OrcaSlicer'),
    (RuntimeError('SECRET unknown'), 'unknown', 'could not identify the cause'),
])
def test_error_protocol_preserves_category_and_plain_cause(error, category, phrase):
    reply = json.loads(json.dumps(worker_errors.encode(error)))
    back = worker_errors.decode(reply)
    assert str(back) == str(error)
    assert diagnostics.classify(back).value == category
    post = slice_failure.post(back)
    assert phrase in post
    assert 'SECRET' not in post and 'secret-command' not in post
    assert 'nothing was uploaded or started' in post
    assert 'Reference: PH_SLICING_' in post


def test_protocol_preserves_refusal_and_safe_fix():
    original = unconfirmed_slot_color(2, {'spoolman_id': 3, 'material': 'PLA', 'name': 'Blue PLA'}, 'raw')
    back = worker_errors.decode(json.loads(json.dumps(worker_errors.encode(original))))
    assert back.fix == original.fix and back.plain == original.plain
    assert diagnostics.classify(back) == diagnostics.Category.CONFIGURATION


def test_worker_protocol_never_imports_a_reported_type():
    back = worker_errors.decode({'type': 'os.system', 'error': 'SECRET'})
    assert isinstance(back, RuntimeError)
    assert diagnostics.classify(back) == diagnostics.Category.UNKNOWN
    assert 'SECRET' not in slice_failure.post(back)


@pytest.mark.parametrize('error_code,phrase,category', [
    ("subprocess.TimeoutExpired(['SECRET-command'], 600)", 'time limit', 'transient'),
    ("ResourceLimitError('container is at its process limit SECRET')", 'process limit', 'configuration'),
    ("SliceFailure('SECRET-stderr', kind='engine', slicer='OrcaSlicer')", 'OrcaSlicer', 'unknown'),
])
def test_real_child_process_error_reaches_parent_heavy_boundary(monkeypatch, tmp_path, error_code, phrase, category):
    # Run the production worker __main__ and its error encoder in a real child.
    # Only the slice function is replaced; the transport, JSON and parent decoder
    # are real. No printer, external download or installed slicer is needed.
    script = f'''import runpy, subprocess
from print_handy.core import model_job
from print_handy.core.resources import ResourceLimitError
from print_handy.core.slice_failure import SliceFailure
def fail(*args, **kwargs):
    raise {error_code}
model_job.slice_job = fail
runpy.run_module('print_handy.core.heavy_worker', run_name='__main__')
'''
    real_run = owned_worker.run

    async def child(command, payload, **kwargs):
        return await real_run([sys.executable, '-c', script], payload, **kwargs)

    monkeypatch.setattr(owned_worker, 'run', child)
    from print_handy.core import model_job
    with pytest.raises(RuntimeError) as info:
        asyncio.run(prepared_intake._heavy(model_job.slice_job, str(tmp_path / 'JOB.json')))
    assert diagnostics.classify(info.value).value == category
    post = slice_failure.post(info.value)
    assert phrase in post and 'SECRET' not in post


def test_slicer_timeout_keeps_partial_output_before_cleanup(monkeypatch, tmp_path):
    from print_handy.core import orca_adapter
    work = tmp_path / 'work'
    work.mkdir()
    kept = tmp_path / 'kept'
    from print_handy.hermes import _config
    monkeypatch.setattr(_config, 'hermes_home', lambda: str(kept))

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(['secret'], 600, output=b'partial output', stderr=b'partial error')

    monkeypatch.setattr(orca_adapter, '_spawn_slicer', timeout)
    with pytest.raises(slice_failure.SliceFailure) as info:
        orca_adapter._run_slicer(['secret'], 'OrcaSlicer', work)
    assert info.value.kind == 'timeout'
    retained = kept / 'state' / 'slice-failures' / work.name / 'orca.log'
    assert retained.read_text() == 'partial outputpartial error'
    assert str(retained.parent) in str(info.value)


def test_invalid_wire_kind_and_slicer_cannot_inject_chat_text():
    back = slice_failure.SliceFailure.from_dict({'message': 'SECRET', 'kind': 'fake', 'slicer': 'SECRET'})
    assert 'SECRET' not in slice_failure.post(back)
    assert 'could not identify the cause' in slice_failure.post(back)


@pytest.mark.parametrize('kind,phrase', [
    ('launch', 'could not be opened'), ('output', 'generator could not be verified'),
    ('conflict', 'conflicting toolpaths'),
])
def test_other_identified_failures_survive_serialization_without_blind_retry(kind, phrase):
    error = slice_failure.SliceFailure('SECRET', kind=kind, slicer='OrcaSlicer')
    back = worker_errors.decode(json.loads(json.dumps(worker_errors.encode(error))))
    assert phrase in slice_failure.post(back)
    assert 'SECRET' not in slice_failure.post(back)
    assert not slice_failure.explain(back).retryable


def test_configuration_error_remains_nonretryable_after_worker_roundtrip():
    from print_handy.settings import SettingsError
    back = worker_errors.decode(worker_errors.encode(SettingsError('SECRET configuration')))
    assert diagnostics.classify(back) == diagnostics.Category.CONFIGURATION
    assert 'configuration check failed' in slice_failure.post(back)
    assert not slice_failure.explain(back).retryable


def test_failed_retry_keeps_new_known_cause_remedy():
    post = slice_failure.post(ResourceLimitError('container is at its process limit SECRET'), retry_failed=True)
    assert 'The one retry also failed' in post and '--pids-limit' in post
    assert 'PH_SLICING_CONFIGURATION' in post and 'SECRET' not in post


def test_timeout_log_write_failure_does_not_replace_original_cause(monkeypatch, tmp_path):
    from pathlib import Path
    from print_handy.core import orca_adapter

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(['secret'], 600, output=b'partial')

    monkeypatch.setattr(orca_adapter, '_spawn_slicer', timeout)
    monkeypatch.setattr(Path, 'write_text', lambda *a, **k: (_ for _ in ()).throw(PermissionError('read-only')))
    with pytest.raises(slice_failure.SliceFailure) as info:
        orca_adapter._run_slicer(['secret'], 'OrcaSlicer', tmp_path)
    assert info.value.kind == 'timeout'
