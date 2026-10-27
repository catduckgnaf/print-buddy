"""Corrupt / partial state files (#391 scope 2): the fail-soft readers.

Several small JSON state files sit on hot paths (the last model link per
channel, the print-alert buttons, the recorded start messages, the bot
heartbeat). Their shared contract is fail-soft: a damaged file must cost
the feature, never the flow — unparseable JSON already degrades to the
empty state in every one of these modules, and those paths are pinned
here as passing tests.

The parseable-but-malformed shape is NOT handled today: a row whose
timestamp is not a number (partial write, hand edit, foreign writer)
raises out of recent_links, print_alert_buttons and print_next. That is
bug #404, filed from this pass per #391's rules (tests only here, no
drive-by fix); the strict xfails below pin the expected behaviour, so
the fix PR must remove the markers when they start passing.
"""
import json
import time

import pytest

from print_buddy.bot import health, recent_links
from print_buddy.hermes import print_alert_buttons as pab
from print_buddy.hermes import print_next

NOW = 1_760_000_000.0


@pytest.fixture
def links(tmp_path, monkeypatch):
    path = tmp_path / "recent_model_links.json"
    monkeypatch.setattr(recent_links, "_path", lambda: path)
    return path


@pytest.fixture
def alerts(tmp_path, monkeypatch):
    path = tmp_path / "print_alert_buttons.json"
    monkeypatch.setattr(pab, "STATE", path)
    return path


@pytest.fixture
def starts(tmp_path, monkeypatch):
    path = tmp_path / "print_buddy_start_messages.json"
    monkeypatch.setattr(print_next, "START_MESSAGES", path)
    return path


# -- unparseable / wrong-shape files: already fail-soft, pinned green ------


def test_recent_links_unparseable_file_recalls_nothing_and_recovers(links):
    links.write_text('{"chan:": {"url": "https://example.com/x", "at": ')
    assert recent_links.recall("chan") is None
    recent_links.remember("chan", "https://example.com/y", now=NOW)
    assert recent_links.recall("chan", now=NOW) == "https://example.com/y"


def test_recent_links_non_mapping_file_recalls_nothing(links):
    links.write_text('["not", "a", "mapping"]')
    assert recent_links.recall("chan") is None


def test_recent_links_non_mapping_row_recalls_nothing(links):
    links.write_text(json.dumps({"chan:": "just-a-string"}))
    assert recent_links.recall("chan") is None


def test_recent_links_expired_row_recalls_nothing(links):
    links.write_text(json.dumps(
        {"chan:": {"url": "https://example.com/x", "at": NOW - recent_links.TTL_S - 1}}))
    assert recent_links.recall("chan", now=NOW) is None


def test_alert_buttons_unparseable_file_is_empty_and_recovers(alerts):
    alerts.write_text("{oops")
    assert pab.peek("anything") is None
    assert pab.take("anything") is None
    aid = pab.record("paused", "f.gcode")
    assert pab.peek(aid)["filename"] == "f.gcode"


def test_start_messages_unparseable_file_is_empty_and_recovers(starts):
    starts.write_text("{oops")
    assert print_next.take_start_message("a.gcode", now=NOW) is None
    print_next.record_start_message("a.gcode", "42", now=NOW)
    assert print_next.take_start_message("a.gcode", now=NOW) == "42"
    assert print_next.take_start_message("a.gcode", now=NOW) is None  # consumed once


def test_bot_health_unparseable_heartbeat_reads_as_none(tmp_path, monkeypatch):
    path = tmp_path / "bot_health.json"
    path.write_text("{oops")
    monkeypatch.setattr(health, "path", lambda: path)
    assert health.read() is None
    path.write_text('["not", "a", "mapping"]')
    assert health.read() is None


# -- parseable but malformed timestamps: bug #404, pinned as strict xfails --

MALFORMED_AT = pytest.mark.xfail(
    strict=True, reason="bug #404: fail-soft state readers crash on a "
                        "non-numeric stored timestamp")


@MALFORMED_AT
def test_recent_links_recall_survives_a_non_numeric_timestamp(links):
    links.write_text(json.dumps({"chan:": {"url": "https://example.com/x", "at": "bad"}}))
    assert recent_links.recall("chan", now=NOW) is None


@MALFORMED_AT
def test_recent_links_remember_prunes_a_non_numeric_timestamp_row(links):
    links.write_text(json.dumps({"chan:": {"url": "https://example.com/x", "at": [1]}}))
    recent_links.remember("other", "https://example.com/y", now=NOW)
    assert recent_links.recall("other", now=NOW) == "https://example.com/y"


@MALFORMED_AT
def test_alert_buttons_survive_a_non_numeric_timestamp(alerts):
    alerts.write_text(json.dumps({"old": {"kind": "paused", "filename": "f", "at": "bad"}}))
    assert pab.peek("old") is None
    assert pab.take("old") is None
    aid = pab.record("paused", "f.gcode", now=NOW)
    assert aid


@MALFORMED_AT
def test_alert_buttons_survive_a_non_mapping_row(alerts):
    alerts.write_text(json.dumps({"old": "just-a-string"}))
    assert pab.peek("old") is None


@MALFORMED_AT
def test_start_messages_survive_a_non_numeric_timestamp(starts):
    starts.write_text(json.dumps({"a.gcode": {"message_id": "1", "ts": "bad"}}))
    assert print_next.take_start_message("a.gcode", now=NOW) is None
    print_next.record_start_message("b.gcode", "2", now=NOW)
