"""Bounded Discord startup retries for transient network failures (#364)."""
import errno
import logging
import socket
from unittest import mock

import aiohttp
import discord
import pytest
from aiohttp.client_reqrep import ConnectionKey

from print_buddy.bot import client
from print_buddy.hermes import _config


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(_config, "discord_token", lambda: "test-token")


def _dns_error():
    key = ConnectionKey("discord.com", 443, True, None, None, None, None)
    return aiohttp.ClientConnectorDNSError(
        key, socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution"))


def _bot_factory(monkeypatch, outcomes):
    instances = []

    class FakeBot:
        def __init__(self, cfg):
            self.cfg = cfg
            instances.append(self)

        def run(self, token, log_handler=None):
            assert token == "test-token"
            assert log_handler is None
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome

    monkeypatch.setattr(client, "PrintBuddyBot", FakeBot)
    return instances


def _fast_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(client, "_startup_retry_delay", lambda attempt: float(attempt))
    monkeypatch.setattr(client, "_startup_sleep", sleeps.append)
    return sleeps


def _retry_lines(caplog):
    return [record.getMessage() for record in caplog.records
            if "DISCORD_STARTUP_RETRY" in record.getMessage()]


def test_transient_dns_failures_then_success_starts_a_fresh_bot_each_time(monkeypatch, caplog, cfg):
    instances = _bot_factory(monkeypatch, [
        socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution"),
        _dns_error(),
        None,
    ])
    sleeps = _fast_retries(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=client.__name__):
        assert client.run_bot(cfg) == 0

    assert len(instances) == 3
    assert len({id(bot) for bot in instances}) == 3  # a closed discord.py client is not reused
    assert sleeps == [1.0, 2.0]
    lines = _retry_lines(caplog)
    assert len(lines) == 2
    assert "attempt 1/5" in lines[0] and "gaierror" in lines[0] and "errno=-3" in lines[0]
    assert "attempt 2/5" in lines[1] and "ClientConnectorDNSError" in lines[1] and "errno=-3" in lines[1]


def test_transient_failure_on_every_attempt_reraises_after_the_bounded_count(monkeypatch, caplog, cfg):
    instances = _bot_factory(monkeypatch, [
        socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
        for _ in range(client.STARTUP_ATTEMPTS)
    ])
    sleeps = _fast_retries(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=client.__name__):
        with pytest.raises(socket.gaierror):
            client.run_bot(cfg)

    assert len(instances) == client.STARTUP_ATTEMPTS == 5
    assert sleeps == [1.0, 2.0, 3.0, 4.0]
    lines = _retry_lines(caplog)
    assert len(lines) == client.STARTUP_ATTEMPTS
    assert "attempt 5/5" in lines[-1] and "no retries left" in lines[-1]


def test_exhausted_retry_line_carries_the_taxonomy_marker(monkeypatch, caplog, cfg):
    """#390 Stage 2: the final startup failure is findable by its PB_ marker."""
    _bot_factory(monkeypatch, [
        socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
        for _ in range(client.STARTUP_ATTEMPTS)
    ])
    _fast_retries(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=client.__name__):
        with pytest.raises(socket.gaierror):
            client.run_bot(cfg)

    assert "PB_DISCORD_TRANSIENT" in _retry_lines(caplog)[-1]


def test_login_failure_exits_3_immediately_without_retry(monkeypatch, cfg):
    instances = _bot_factory(monkeypatch, [discord.LoginFailure("bad token")])
    sleeps = _fast_retries(monkeypatch)

    assert client.run_bot(cfg) == 3
    assert len(instances) == 1
    assert sleeps == []


def test_privileged_intents_exits_3_immediately_without_retry(monkeypatch, cfg):
    instances = _bot_factory(monkeypatch, [discord.PrivilegedIntentsRequired(0)])
    sleeps = _fast_retries(monkeypatch)

    assert client.run_bot(cfg) == 3
    assert len(instances) == 1
    assert sleeps == []


def test_non_transient_error_is_not_retried(monkeypatch, cfg):
    instances = _bot_factory(monkeypatch, [ValueError("programming error")])
    sleeps = _fast_retries(monkeypatch)

    with pytest.raises(ValueError, match="programming error"):
        client.run_bot(cfg)
    assert len(instances) == 1
    assert sleeps == []


def test_startup_retry_delay_schedule_is_bounded(monkeypatch):
    monkeypatch.setattr(client.random, "uniform", lambda low, high: (low + high) / 2)
    delays = [client._startup_retry_delay(attempt) for attempt in range(1, client.STARTUP_ATTEMPTS)]
    assert delays == [10.0, 20.0, 40.0, 80.0]
    assert sum(delays) == 150.0


def _http_error(status):
    return discord.HTTPException(mock.Mock(status=status, reason="test"), {"message": "oops"})


def test_transient_startup_error_classification():
    key = ConnectionKey("discord.com", 443, True, None, None, None, None)

    assert client._is_transient_startup_error(_dns_error())
    assert client._is_transient_startup_error(aiohttp.ClientConnectorError(
        key, ConnectionRefusedError(errno.ECONNREFUSED, "connection refused")))
    assert not client._is_transient_startup_error(aiohttp.ClientConnectorError(
        key, PermissionError(errno.EACCES, "permission denied")))
    assert client._is_transient_startup_error(TimeoutError("timed out"))
    assert client._is_transient_startup_error(aiohttp.ServerTimeoutError("timed out"))
    assert client._is_transient_startup_error(_http_error(503))
    assert client._is_transient_startup_error(_http_error(429))
    assert not client._is_transient_startup_error(_http_error(403))
    assert not client._is_transient_startup_error(discord.LoginFailure("bad token"))
    assert not client._is_transient_startup_error(ValueError("programming error"))
