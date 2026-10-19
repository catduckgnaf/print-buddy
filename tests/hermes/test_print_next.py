"""Offline tests for /print-next. Fake transport and fake print-now; no printer contact."""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace as S
from unittest import mock

import pytest

HERE = Path(__file__).resolve().parent
from print_buddy.hermes import print_next
from print_buddy.hermes import print_records


def make_job(tmp_path, plates=2):
    folder = tmp_path / 'archive' / 'ghost--abc'
    sliced = folder / 'sliced' / 'orca' / 'run1'
    sliced.mkdir(parents=True)
    rows = []
    for n in range(1, plates + 1):
        g = sliced / f'plate_{n}.gcode'
        g.write_text(f'; plate {n}\n')
        rows.append({'slot': n, 'gcode': str(g)})
    job = {'title': 'Ghost', 'gcode': rows[0]['gcode'], 'derived_plates': rows}
    (folder / 'JOB.json').write_text(json.dumps(job))
    return folder, rows


def make_plan(tmp_path, folder, rows, **second):
    plan = {'plan_id': 'ghost', 'parts': [
        {'id': 'body', 'label': 'Body', 'status': 'completed', 'quantity': 1, 'completed_quantity': 1,
         'run_id': 1, 'plate_id': 1, 'gcode_file': 'plate_1.gcode'},
        {'id': 'tail', 'label': 'Tail', 'quantity': 1, 'completed_quantity': 0, 'run_id': 2, 'plate_id': 2,
         'gcode_file': 'plate_2.gcode', 'job_json': str(folder / 'JOB.json'), 'gcode_path': rows[1]['gcode'],
         **second},
    ]}
    plans = tmp_path / 'Plans'
    plans.mkdir(exist_ok=True)
    (plans / 'ghost.json').write_text(json.dumps(plan))
    return plans


def test_resolves_exact_next_plate(tmp_path):
    folder, rows = make_job(tmp_path)
    plans = make_plan(tmp_path, folder, rows)
    target = print_next.resolve_next(print_next.load_plan('ghost', plans), tmp_path / 'archive')
    assert target['gcode'] == rows[1]['gcode']
    assert target['label'] == 'Tail' and target['reprint'] is False
    assert 'Run 2, Plate 2' in print_next.question_text(target)


@pytest.mark.parametrize('bad', [
    {'job_json': None},
    {'gcode_path': '/etc/passwd'},
    {'gcode_file': 'plate_9.gcode'},
])
def test_refuses_inexact_targets(tmp_path, bad):
    folder, rows = make_job(tmp_path)
    plans = make_plan(tmp_path, folder, rows, **bad)
    with pytest.raises(print_next.NextPlateError):
        print_next.resolve_next(print_next.load_plan('ghost', plans), tmp_path / 'archive')


def test_refuses_artifact_not_current_in_job(tmp_path):
    folder, rows = make_job(tmp_path)
    stale = Path(rows[1]['gcode']).with_name('old_plate_2.gcode')
    stale.write_text('; stale\n')
    plans = make_plan(tmp_path, folder, rows, gcode_path=str(stale), gcode_file='old_plate_2.gcode')
    with pytest.raises(print_next.NextPlateError, match='not a current artifact'):
        print_next.resolve_next(print_next.load_plan('ghost', plans), tmp_path / 'archive')


def test_refuses_path_traversal_plan_id(tmp_path):
    with pytest.raises(print_next.NextPlateError):
        print_next.load_plan('../etc/x', tmp_path)


def test_second_copy_uses_reprint(tmp_path):
    folder, rows = make_job(tmp_path)
    plans = make_plan(tmp_path, folder, rows, quantity=2, completed_quantity=1)
    target = print_next.resolve_next(print_next.load_plan('ghost', plans), tmp_path / 'archive')
    assert target['reprint'] is True and target['copy'] == 2


def test_start_refuses_changed_gcode_without_running(tmp_path):
    folder, rows = make_job(tmp_path)
    plans = make_plan(tmp_path, folder, rows)
    target = print_next.resolve_next(print_next.load_plan('ghost', plans), tmp_path / 'archive')
    Path(target['gcode']).write_text('; tampered\n')
    with mock.patch('asyncio.create_subprocess_exec') as spawn:
        ok, detail = asyncio.run(print_next.start(target))
    assert not ok and 'changed' in detail
    spawn.assert_not_called()


def test_start_runs_print_now_once_with_exact_path(tmp_path):
    folder, rows = make_job(tmp_path)
    plans = make_plan(tmp_path, folder, rows)
    target = print_next.resolve_next(print_next.load_plan('ghost', plans), tmp_path / 'archive')
    fake = tmp_path / 'fake_model_job.sh'
    log = tmp_path / 'calls.txt'
    fake.write_text(f'#!/bin/sh\necho "$@" >> {log}\necho "START REQUEST ACCEPTED"\n')
    fake.chmod(0o755)
    ok, detail = asyncio.run(print_next.start(target, model_job=fake, idle_check=lambda: None,
                                              claims_dir=tmp_path / 'claims'))
    assert ok and 'START REQUEST ACCEPTED' in detail
    assert log.read_text().splitlines() == [f"print-now {rows[1]['gcode']}"]


def _fake_job(tmp_path, body):
    fake = tmp_path / 'fake_model_job.sh'
    log = tmp_path / 'calls.txt'
    fake.write_text(f'#!/bin/sh\necho "$@" >> {log}\n{body}\n')
    fake.chmod(0o755)
    return fake, log


def _target(tmp_path):
    folder, rows = make_job(tmp_path)
    plans = make_plan(tmp_path, folder, rows)
    return print_next.resolve_next(print_next.load_plan('ghost', plans), tmp_path / 'archive')


def test_replayed_button_cannot_start_same_plate_twice(tmp_path):
    target = _target(tmp_path)
    fake, log = _fake_job(tmp_path, 'echo "START REQUEST ACCEPTED"')
    kw = dict(model_job=fake, idle_check=lambda: None, claims_dir=tmp_path / 'claims')
    assert asyncio.run(print_next.start(target, **kw))[0] is True
    ok, detail = asyncio.run(print_next.start(target, **kw))
    assert not ok and 'already started' in detail
    assert len(log.read_text().splitlines()) == 1


def test_busy_or_unreadable_printer_refuses_before_spawn(tmp_path):
    target = _target(tmp_path)
    fake, log = _fake_job(tmp_path, 'echo ok')

    def busy():
        raise RuntimeError('printer is not idle (printing, x.gcode, Printing)')
    ok, detail = asyncio.run(print_next.start(target, model_job=fake, idle_check=busy,
                                              claims_dir=tmp_path / 'claims'))
    assert not ok and 'fresh printer check failed' in detail
    assert not log.exists() and not (tmp_path / 'claims').exists()


def test_clean_refusal_releases_claim_but_failure_keeps_it(tmp_path):
    target = _target(tmp_path)
    claims = tmp_path / 'claims'
    fake, _ = _fake_job(tmp_path, 'echo "REFUSED: mesh stale. Nothing uploaded or started."; exit 1')
    ok, _ = asyncio.run(print_next.start(target, model_job=fake, idle_check=lambda: None, claims_dir=claims))
    assert not ok and list(claims.glob('*.json')) == []
    fake2, _ = _fake_job(tmp_path, 'echo "UPLOAD FAILED: boom"; exit 1')
    ok, _ = asyncio.run(print_next.start(target, model_job=fake2, idle_check=lambda: None, claims_dir=claims))
    kept = list(claims.glob('*.json'))
    assert not ok and len(kept) == 1 and json.loads(kept[0].read_text())['outcome'] == 'failed_uncertain'


def test_timeout_stops_print_now_and_keeps_claim(tmp_path):
    target = _target(tmp_path)
    claims = tmp_path / 'claims'
    marker = tmp_path / 'late_start'
    fake, _ = _fake_job(tmp_path, f'sleep 5; touch {marker}')
    ok, detail = asyncio.run(print_next.start(target, model_job=fake, idle_check=lambda: None,
                                              claims_dir=claims, timeout=0.5))
    import time as _t
    _t.sleep(5.5)
    assert not ok and 'UNCERTAIN' in detail and not marker.exists()
    assert json.loads(next(claims.glob('*.json')).read_text())['outcome'] == 'uncertain_timeout'


def test_summary_names_command_only_with_exact_target(tmp_path):
    folder, rows = make_job(tmp_path)
    plan = json.loads(make_plan(tmp_path, folder, rows).joinpath('ghost.json').read_text())
    summary = print_records.format_multipart_summary(plan, 'plate_1.gcode')
    assert '/print-next ghost' in summary
    assert str(folder) not in summary
    plan['parts'][1].pop('job_json')
    assert '/print-next' not in print_records.format_multipart_summary(plan, 'plate_1.gcode')


def test_completion_binds_sibling_plate_from_same_job(tmp_path, monkeypatch):
    folder, rows = make_job(tmp_path)
    monkeypatch.setattr(print_records, 'PLANS_DIR', tmp_path / 'Plans2')
    data = {'multipart_plan_id': 'ghost', 'gcode_file': 'plate_1.gcode', 'part_id': 'body',
            'completed_at': '2026-10-06T22:00:00Z', 'slicer_settings': {'local_gcode': rows[0]['gcode']},
            'required_parts': [
                {'id': 'body', 'label': 'Body', 'gcode_file': 'plate_1.gcode'},
                {'id': 'tail', 'label': 'Tail', 'gcode_file': 'plate_2.gcode'},
                {'id': 'other', 'label': 'Other', 'gcode_file': 'plate_7.gcode'}]}
    plan_id, complete = print_records.update_multipart_plan(data)
    saved = json.loads((tmp_path / 'Plans2' / 'ghost.json').read_text())
    tail = next(p for p in saved['parts'] if p['id'] == 'tail')
    other = next(p for p in saved['parts'] if p['id'] == 'other')
    assert plan_id == 'ghost' and not complete
    assert tail['gcode_path'] == rows[1]['gcode'] and tail['job_json'] == str(folder / 'JOB.json')
    assert 'job_json' not in other


# Plugin hook ---------------------------------------------------------------

def load_plugin():
    plugin = HERE.parents[1] / 'plugins/print-feedback/__init__.py'
    spec = importlib.util.spec_from_file_location('print_feedback_next', plugin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Transport:
    def __init__(self, pick):
        self.pick, self.questions, self.sent = pick, [], []

    async def send_clarify(self, **kwargs):
        self.questions.append(kwargs)
        import tools.clarify_gateway as cm
        cm.resolve_gateway_clarify(kwargs['clarify_id'], kwargs['choices'][self.pick])
        return S(success=True)

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        # Mirrors DiscordAdapter.send exactly; a text= keyword raises TypeError like production.
        self.sent.append({'chat_id': chat_id, 'content': content, 'reply_to': reply_to, 'metadata': metadata})
        return S(success=True)


def run_hook(tmp_path, text, pick=0, authorized=True, start_result=(True, 'START REQUEST ACCEPTED'), plugin_patch=None):
    folder, rows = make_job(tmp_path)
    plans = make_plan(tmp_path, folder, rows)
    mod = load_plugin()
    for name, value in (plugin_patch or {}).items():
        setattr(mod, name, value)
    adapter = Transport(pick)
    src = S(platform=S(value='discord'), profile='3dprinting', user_id='42', chat_id='c', thread_id=None)
    gateway = S(_is_user_authorized_for_source=lambda s: authorized, _delivery_adapter_for=lambda s: adapter)
    started = []

    async def fake_start(target):
        started.append(target['gcode'])
        return start_result
    real_resolve, real_load = print_next.resolve_next, print_next.load_plan
    with mock.patch.object(print_next, 'load_plan', lambda pid: real_load(pid, plans)), \
            mock.patch.object(print_next, 'start', fake_start), \
            mock.patch.object(print_next, 'resolve_next',
                              lambda plan: real_resolve(plan, tmp_path / 'archive')):
        result = asyncio.run(mod.print_next_dispatch(S(source=src, text=text, internal=False), gateway))
    return result, adapter, started, rows


def test_hook_button_starts_exact_plate_once(tmp_path):
    result, adapter, started, rows = run_hook(tmp_path, '/print-next ghost', pick=0)
    assert result['action'] == 'skip'
    assert adapter.questions[0]['choices'] == [print_next.START_LABEL, print_next.CANCEL_LABEL]
    assert started == [rows[1]['gcode']]
    assert adapter.sent[-1]['content'].startswith('Preparing to start Tail')
    assert not any(message['content'].startswith('Print started:') for message in adapter.sent)


def test_hook_cancel_starts_nothing(tmp_path):
    result, adapter, started, _ = run_hook(tmp_path, '/print-next ghost', pick=1)
    assert started == [] and 'Nothing uploaded or started' in adapter.sent[-1]['content']


def test_hook_unknown_plan_has_no_button(tmp_path):
    result, adapter, started, _ = run_hook(tmp_path, '/print-next nope')
    assert adapter.questions == [] and started == []
    assert 'No next plate' in adapter.sent[-1]['content']


def test_hook_unauthorized_is_silent(tmp_path):
    result, adapter, started, _ = run_hook(tmp_path, '/print-next ghost', authorized=False)
    assert result is None and adapter.questions == [] and adapter.sent == [] and started == []


def test_hook_ignores_other_text(tmp_path):
    result, adapter, _, _ = run_hook(tmp_path, '/print-nextghost')
    assert result is None and adapter.sent == []


def test_hook_refused_start_offers_force_restart(tmp_path):
    async def offer(adapter, source, metadata, pc, reason):
        return 'RESTART OFFERED'
    _result, adapter, _started, _ = run_hook(
        tmp_path, '/print-next ghost', pick=0, start_result=(False, 'Refused: printer state is paused'),
        plugin_patch={'_offer_force_restart': offer})
    assert 'RESTART OFFERED' in adapter.sent[-1]['content']
