"""Standalone bot tests: a fake discord.py client, no token, no network, no Hermes.

The bot switches process globals on (the core prompt registry, the plugin's Stop sender). Each test gets
them back off, so Hermes-path suites that run later keep their clarify stand-in.
"""
import copy

import pytest

from print_handy.core import prepared_intake, prompts
from print_handy.hermes import _config


@pytest.fixture(autouse=True)
def _restore_bot_globals(monkeypatch):
    monkeypatch.setattr(prompts, "_active", False)
    monkeypatch.setattr(prepared_intake, "STOP_SENDER", None)
    yield


@pytest.fixture
def cfg(tmp_path):
    data = copy.deepcopy(_config.cfg())
    data["bot"]["mode"] = "standalone"
    data["discord"].update(chat_id="100000000000000001", allowed_user_ids="200000000000000002",
                           approval_user_id="")
    data["paths"]["cache"] = tmp_path / "cache"
    data["llm"].update(chat_url="", model="")
    return data
