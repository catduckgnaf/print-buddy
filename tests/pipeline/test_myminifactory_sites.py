"""#462 Stage 2: MyMiniFactory via its official API v2 — INVENTORY ONLY.

catduck's decision (2026-10-27): inventory-only with the download gap named;
Cults3D skipped. Per MyMiniFactory's own API guidelines, downloading an object
inside an app requires the downloader to be logged in (OAuth); that route is
not built, so intake refuses before any choice/preview/download with the gap
named. All network is mocked; no live MMF request in tests/CI (no API key was
available when this was built, and the parser is defensive for that reason)."""
import asyncio
import io
import json
import urllib.error
from types import SimpleNamespace as S
from unittest import mock

import pytest

from print_buddy.core import model_job as model_job
from print_buddy.core import prepared_intake
from print_buddy.core.link_intake import model_link
from .test_color_intake import source, state  # noqa: F401  (state used by the e2e flow)
from .test_prepared_intake import Adapter, env  # noqa: F401  (env is the shared harness fixture)

MMF_URL = 'https://www.myminifactory.com/object/3d-print-benchy-boat-12345'
OBJ_LIST_FILES = {
    'id': 12345, 'name': 'Benchy Boat',
    'license': {'name': 'Creative Commons - Attribution'},
    'files': [
        {'id': 11, 'filename': 'benchy.stl', 'size': 54321},
        {'id': 12, 'name': 'benchy_hull.3mf', 'size': 999},
        {'id': 13, 'filename': 'notes.txt', 'size': 10},
        {'id': 14, 'filename': 'all_files.zip', 'size': 20000},
    ]}
OBJ_ITEMS_FILES = {
    'id': 777, 'name': 'Gear', 'license': 'CC BY-SA',
    'files': {'items': [{'id': 21, 'name': 'gear.stl', 'size': 42}]}}


def _key_home(tmp_path, monkeypatch, key='test-key'):
    home = tmp_path / 'home'
    cfg = home / '.config' / 'myminifactory'
    cfg.mkdir(parents=True)
    if key is not None:
        (cfg / 'token').write_text(key + '\n')
    monkeypatch.setenv('HOME', str(home))
    return home


def _api(monkeypatch, obj=OBJ_LIST_FILES):
    calls = []

    def fake_request_json(url, **kw):
        calls.append(url)
        return obj

    monkeypatch.setattr(model_job, 'request_json', fake_request_json)
    return calls


@pytest.mark.parametrize('text,hit', [
    ('https://www.myminifactory.com/object/3d-print-benchy-boat-12345', True),
    ('https://myminifactory.com/object/3d-print-benchy-boat-12345', True),
    ('https://www.myminifactory.com/object/12345', True),
    ('print https://www.myminifactory.com/object/3d-print-benchy-boat-12345 please', True),
    ('https://www.myminifactory.com/designer/someone', False),
    ('https://www.myminifactory.com/object/3d-print-benchy-boat', False),
    ('https://www.myminifactory.com/object/', False),
])
def test_model_link_myminifactory(text, hit):
    assert (model_link(text) is not None) is hit


def test_myminifactory_id():
    assert model_job.myminifactory_id(MMF_URL) == '12345'
    assert model_job.myminifactory_id('https://www.myminifactory.com/object/12345') == '12345'
    assert model_job.myminifactory_id(MMF_URL + '?download_show=1') == '12345'
    with pytest.raises(ValueError, match=r'/object/'):
        model_job.myminifactory_id('https://www.myminifactory.com/designer/someone')
    with pytest.raises(ValueError, match=r'/object/'):
        model_job.myminifactory_id('https://www.myminifactory.com/object/3d-print-benchy-boat')


def test_myminifactory_inventory_list_files_shape(tmp_path, monkeypatch):
    _key_home(tmp_path, monkeypatch)
    calls = _api(monkeypatch)
    job = model_job.myminifactory_inventory(MMF_URL)
    assert job['site'] == 'myminifactory'
    assert job['model_id'] == '12345'
    assert job['title'] == 'Benchy Boat'
    # License dict normalised to its name string.
    assert job['license'] == 'Creative Commons - Attribution'
    # Only .stl/.3mf files are sources: the .txt note and the zip are not.
    # "filename" and "name" keys are both honoured.
    assert [(s['id'], s['name'], s['bytes'], s['kind']) for s in job['sources']] == [
        (11, 'benchy.stl', 54321, 'files'), (12, 'benchy_hull.3mf', 999, 'files')]
    assert 'no_geometry_reason' not in job
    # The named download gap rides on every MMF job.
    assert job['download_gap'] == model_job.MYMINIFACTORY_DOWNLOAD_GAP
    assert 'logged in' in job['download_gap']
    # The API key goes as the key= query parameter on the API v2 object URL.
    assert calls == ['https://www.myminifactory.com/api/v2/objects/12345?key=test-key']


def test_myminifactory_inventory_items_files_shape(tmp_path, monkeypatch):
    _key_home(tmp_path, monkeypatch)
    _api(monkeypatch, obj=OBJ_ITEMS_FILES)
    job = model_job.myminifactory_inventory(
        'https://www.myminifactory.com/object/3d-print-gear-777')
    assert job['model_id'] == '777'
    assert job['license'] == 'CC BY-SA'  # license as a plain string passes through
    assert [(s['id'], s['name'], s['bytes']) for s in job['sources']] == [(21, 'gear.stl', 42)]
    assert job['download_gap'] == model_job.MYMINIFACTORY_DOWNLOAD_GAP


def test_myminifactory_no_geometry_names_the_reason(tmp_path, monkeypatch):
    _key_home(tmp_path, monkeypatch)
    _api(monkeypatch, obj={'id': 55, 'name': 'Notes Only', 'license': None,
                           'files': [{'id': 1, 'filename': 'readme.txt', 'size': 5},
                                     {'id': 2, 'filename': 'pack.zip', 'size': 9}]})
    job = model_job.myminifactory_inventory('https://www.myminifactory.com/object/3d-print-notes-55')
    assert job['sources'] == []
    assert 'exposes no STL/3MF' in job['no_geometry_reason']
    assert job['download_gap'] == model_job.MYMINIFACTORY_DOWNLOAD_GAP


def test_myminifactory_missing_key_error(tmp_path, monkeypatch):
    _key_home(tmp_path, monkeypatch, key=None)
    with pytest.raises(RuntimeError, match=r'\.config/myminifactory/token'):
        model_job.myminifactory_inventory(MMF_URL)
    with pytest.raises(RuntimeError, match=r'\.config/myminifactory/token'):
        model_job.myminifactory_api_key()


def test_myminifactory_empty_key_error(tmp_path, monkeypatch):
    _key_home(tmp_path, monkeypatch, key='')
    with pytest.raises(RuntimeError, match='MyMiniFactory API key empty'):
        model_job.myminifactory_api_key()


def _http_error(code):
    return urllib.error.HTTPError(
        'https://www.myminifactory.com/api/v2/objects/1', code, 'blocked', {}, io.BytesIO(b''))


@pytest.mark.parametrize('code', [401, 403])
def test_myminifactory_refusal_is_plain(tmp_path, monkeypatch, code):
    _key_home(tmp_path, monkeypatch, key='SECRETKEY123')
    monkeypatch.setattr(model_job, 'request_json', mock.Mock(side_effect=_http_error(code)))
    with pytest.raises(RuntimeError, match=r'401/403') as excinfo:
        model_job.myminifactory_inventory(MMF_URL)
    # The key value never appears in any raised message.
    assert 'SECRETKEY123' not in str(excinfo.value)


def test_myminifactory_download_refuses_without_network(tmp_path, monkeypatch):
    job = {'site': 'myminifactory', 'model_id': '12345', 'title': 'Benchy Boat'}
    chosen = {'id': 11, 'name': 'benchy.stl', 'bytes': 1, 'kind': 'files'}
    monkeypatch.setattr(model_job, 'request_json',
                        mock.Mock(side_effect=AssertionError('network contacted')))
    monkeypatch.setattr(model_job, 'download',
                        mock.Mock(side_effect=AssertionError('network contacted')))
    with pytest.raises(RuntimeError, match='cannot download files from MyMiniFactory'):
        model_job.myminifactory_download(job, chosen, tmp_path / 'src')
    # The registry route refuses the same way, so no caller can download by accident.
    with pytest.raises(RuntimeError, match='cannot download files from MyMiniFactory'):
        model_job.download_for_site(job, chosen, tmp_path / 'src')


def test_inventory_for_url_routes_myminifactory(monkeypatch):
    sentinel = {'site': 'myminifactory'}
    monkeypatch.setattr(model_job, 'myminifactory_inventory', lambda url: sentinel)
    assert model_job.inventory_for_url(MMF_URL) is sentinel
    with pytest.raises(ValueError, match='MyMiniFactory'):
        model_job.inventory_for_url('https://example.com/object/3d-print-x-1')


def test_prepared_intake_myminifactory_refuses_with_the_gap(env, monkeypatch):
    monkeypatch.setattr(model_job, 'myminifactory_inventory', lambda url: {
        'site': 'myminifactory', 'model_id': '12345', 'slug': 'benchy-boat',
        'title': 'Benchy Boat', 'license': 'Creative Commons - Attribution',
        'sources': [{'id': 11, 'name': 'benchy.stl', 'bytes': 10, 'kind': 'files'},
                    {'id': 12, 'name': 'benchy_hull.3mf', 'bytes': 9, 'kind': 'files'}],
        'download_gap': model_job.MYMINIFACTORY_DOWNLOAD_GAP})
    download = mock.Mock(side_effect=AssertionError('download attempted'))
    monkeypatch.setattr(model_job, 'myminifactory_download', download)
    previews = []

    async def fake_preview(*args, **kw):
        previews.append(args)

    monkeypatch.setattr(prepared_intake, 'send_preview', fake_preview)
    event = S(source=S(profile='3dprinting', chat_id='c1', thread_id=None, user_id='u'),
              message_id='mmf1', text=MMF_URL)
    adapter = Adapter([])
    asyncio.run(prepared_intake.prepare_link(event, adapter, state(), env.root, timeout=1))
    receipt = json.loads(next(env.root.glob('*.json')).read_text())
    assert receipt['status'] == 'FAILED'
    error = receipt['error']
    assert 'Benchy Boat' in error                    # the model title
    assert 'benchy.stl' in error                     # an inventoried file name
    assert '2 printable file(s)' in error
    assert 'logged in' in error and 'OAuth' in error  # the named download gap
    assert 'Nothing was downloaded' in error
    assert 'drop the file here' in error             # the workaround
    # Nothing reached a choice, a preview, a download or a start.
    assert adapter.questions == []
    assert previews == []
    download.assert_not_called()
    assert not env.starts
