"""The connect-account flow end to end through the real bot (#464).

A Nexprint link arrives as a real Telegram update and runs through BotCore,
the print-feedback plugin handlers and the real prepared intake. The
Nexprint API and the file host are faked (no network), and no token is
saved, so the download stops with SiteLoginNeeded. The test then does what
an operator does: presses "Connect Nexprint account" (a real callback
query), reads the walkthrough, saves the token file on disk, and types
`saved` as a plain chat message. The same download must then be retried
with the saved token. The intake is stopped right after the download by a
sentinel, so this covers exactly the connect loop on the real path.

The typed `saved` matters: typed text reaches the prompt through
link_intake.typed_reply, which resolves it with the parser's value, and
ask() must read that value back as the button. This test is what caught
the parser returning an index that ask() then re-asked forever.
"""
import asyncio
from pathlib import Path
from unittest import mock

from print_handy.core import intake_resources, model_job, site_accounts
from .test_telegram import CHAT, USER, BotApiStub, _callback, cfg, make_core, run  # noqa: F401

LINK = 'https://www.nexprint.com/en/models/2076455756517335040'
MODEL = {'code': 0, 'data': {
    'id': '2076455756517335040', 'modelName': 'Penguin keychain', 'licenseType': 0,
    'modelFileList': [{'fileId': '2076455174108495872', 'fileName': 'Penguin+keychain.stl',
                       'fileSize': 584084.0, 'fileExt': 'stl', 'isCreator': True}],
    'settingInfoList': []}}
SIGNED = 'https://nexprint.oss-eu-central-1.aliyuncs.com/models/1/penguin.stl?X-Amz-Signature=1'


class Stopped(RuntimeError):
    pass


def _message(update_id, text):
    return {'update_id': update_id, 'message': {
        'message_id': 40 + update_id, 'from': {'id': int(USER), 'is_bot': False},
        'chat': {'id': int(CHAT)}, 'text': text}}


async def _wait_prompt(core, starts):
    for _ in range(400):
        cid = next((c for c, row in core.adapter._prompts.items()
                    if row['question'].startswith(starts)), None)
        if cid is not None:
            return cid
        await asyncio.sleep(0.01)
    raise AssertionError(f'no prompt {starts!r}: {core.adapter._prompts}')


def test_link_connect_saved_retry_through_the_real_bot(cfg, tmp_path, monkeypatch):
    home = tmp_path/'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.delenv('NEXPRINT_TOKEN', raising=False)
    monkeypatch.setattr(model_job, 'ARCHIVE', tmp_path/'archive')
    api_calls = []

    def fake_api(method, url, *, body=None, headers=None, timeout=25):
        api_calls.append((url, dict(headers or {})))
        if 'model-base-info/get' in url:
            return 200, MODEL
        if 'presigned-download-url' in url:
            if (headers or {}).get('Authorization') != 'Bearer saved-in-file':
                return 200, {'code': 401, 'data': None, 'msg': '账号未登录'}
            return 200, {'code': 0, 'data': {'fileInfoList': [
                {'fileId': '2076455174108495872', 'type': 2, 'resultUrl': SIGNED}]}}
        raise AssertionError(url)
    fetched = []

    def fake_download(url, target, headers=None):
        fetched.append(url)
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(b'solid penguin\n')

    def stop_after_download(path, *a, **kw):
        raise Stopped(f'downloaded {Path(path).name}')
    monkeypatch.setattr(model_job, '_web_api', fake_api)
    monkeypatch.setattr(model_job, 'download', fake_download)
    monkeypatch.setattr(intake_resources, 'check_source', stop_after_download)

    stub = BotApiStub()
    client, core = make_core(cfg, stub)

    async def flow():
        task = asyncio.create_task(client.handle_update(_message(1, LINK)))
        cid = await _wait_prompt(core, 'Nexprint needs you to be signed in')
        await client.handle_update({'update_id': 2, 'callback_query': _callback(cid, 0)})
        await _wait_prompt(core, 'Press Saved once the Nexprint token file')
        # The operator saves the token on the Print Handy machine — never in chat.
        path = site_accounts.token_path('nexprint')
        path.parent.mkdir(parents=True)
        path.write_text('saved-in-file\n')
        await client.handle_update(_message(3, 'saved'))
        return await asyncio.wait_for(task, 10)

    with mock.patch('print_handy.core.printer_state.load', return_value={}):
        run(flow())

    texts = [p.get('text', '') for p in stub.payloads('sendMessage')]
    walkthrough = next(t for t in texts if 'Connect your Nexprint account' in t)
    assert 'auth_token' in walkthrough and "Don't paste the token here" in walkthrough
    assert str(site_accounts.token_path('nexprint')) in walkthrough
    downloads = [h for url, h in api_calls if 'presigned-download-url' in url]
    # First attempt never reached the network (no token); the retry sent the saved one.
    assert [h.get('Authorization') for h in downloads] == ['Bearer saved-in-file']
    assert fetched == [SIGNED]
    assert any('Penguin+keychain.stl' in p.name for p in (tmp_path/'archive').rglob('*.stl'))
    assert 'saved-in-file' not in '\n'.join(texts)  # the token never appears in chat
