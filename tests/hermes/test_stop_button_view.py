"""2.0.6: status steps show one Stop button from the plugin view, never 'Other (type answer)'."""
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
    async def send_clarify(self, **kw):
        raise AssertionError('status step must not use the gateway clarify prompt (it adds Other)')


def test_status_step_shows_only_stop_and_finishes_without_a_press(monkeypatch):
    sent, _ = _install(monkeypatch)

    async def work():
        await asyncio.sleep(0.01)
        return 'fits'

    async def run():
        return await asyncio.wait_for(prepared_intake._with_stop(
            _NoClarify(), S(chat_id='123', thread_id=None), 'k-view', None,
            'Checking whether it fits the bed. Press Stop to cancel.', work()), 5)

    assert asyncio.run(run()) == 'fits'
    labels = [item.label for item in sent[0].view.items]
    assert labels == ['Stop']
    assert sent[0].edits == [{'view': None}], 'the Stop button must be removed once the step finishes'


def test_pressing_plugin_stop_cancels_the_step(monkeypatch):
    sent, on_interaction = _install(monkeypatch)

    async def slow():
        await asyncio.sleep(30)
        return 'never'

    async def run():
        step = asyncio.ensure_future(prepared_intake._with_stop(
            _NoClarify(), S(chat_id='123', thread_id=None), 'k-press', None, 'Slicing. Press Stop to cancel.', slow()))
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
