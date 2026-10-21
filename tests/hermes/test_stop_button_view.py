"""Status-only progress has no Stop view; final pre-start work keeps cancellation."""
import asyncio
import sys
from types import SimpleNamespace as S

from print_buddy.core import prepared_intake
from tests.hermes.test_print_next import Interaction, load_plugin


def _fake_discord(monkeypatch):
    class Button:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class View:
        def __init__(self, timeout=None):
            self.items = []

        def add_item(self, item):
            self.items.append(item)
    monkeypatch.setitem(sys.modules, 'discord', S(ui=S(View=View, Button=Button),
                                                  ButtonStyle=S(success=3, danger=4)))


def _install(monkeypatch):
    _fake_discord(monkeypatch)
    sent, handlers = [], {}

    class Msg:
        def __init__(self, text, view):
            self.text, self.view, self.edits = text, view, []

        async def edit(self, **kw):
            self.edits.append(kw)

    class Channel:
        async def send(self, text, view=None):
            msg = Msg(text, view)
            sent.append(msg)
            return msg
    bot = S(add_listener=lambda fn, name: handlers.update({name: fn}), get_channel=lambda cid: Channel())
    monkeypatch.setattr(prepared_intake, 'STOP_SENDER', None)
    load_plugin().alert_button_handlers(bot, S())
    return sent, handlers['on_interaction']


class _NoClarify:
    def __init__(self):
        self.status = []

    async def send_clarify(self, **kw):
        raise AssertionError('status-only progress must not create an interactive prompt')

    async def send(self, **kw):
        self.status.append(kw['content'])
        return S(success=True)


def test_status_step_sends_plain_progress_without_a_stop_view(monkeypatch):
    sent, _ = _install(monkeypatch)
    adapter = _NoClarify()

    async def work():
        await asyncio.sleep(0.01)
        return 'fits'

    async def run():
        return await asyncio.wait_for(prepared_intake._with_stop(
            adapter, S(chat_id='123', thread_id=None), 'k-view', None,
            'Checking whether it fits the bed. Press Stop to cancel.', work()), 5)

    assert asyncio.run(run()) == 'fits'
    assert adapter.status == ['Checking whether it fits the bed.']
    assert sent == []


def test_pressing_plugin_stop_cancels_the_final_start_step(monkeypatch):
    sent, on_interaction = _install(monkeypatch)

    async def slow():
        await asyncio.sleep(30)
        return 'never'

    async def run():
        step = asyncio.ensure_future(prepared_intake._with_stop(
            _NoClarify(), S(chat_id='123', thread_id=None), 'k-press', None,
            'Uploading to the printer. Press Stop to cancel before it starts.', slow(), allow_stop=True))
        while not sent:
            await asyncio.sleep(0.01)
        press = Interaction(sent[0].view.items[0].custom_id)
        await on_interaction(press)
        try:
            await asyncio.wait_for(step, 5)
        except prepared_intake.Stopped:
            return 'stopped', press.out
        return 'not stopped', press.out

    outcome, out = asyncio.run(run())
    assert outcome == 'stopped'
    assert ('followup', 'Stopping.') in out
