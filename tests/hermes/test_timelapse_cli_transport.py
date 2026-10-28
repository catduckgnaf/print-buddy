"""Offline contract tests for timelapse delivery through the Hermes CLI boundary."""
from types import SimpleNamespace

from print_handy.hermes import moonraker_event_listener as listener


def test_post_passes_media_marker_and_configured_discord_target_to_hermes(monkeypatch):
    calls = []
    monkeypatch.setattr(listener, "DISCORD_TARGET", "discord:channel-42")
    monkeypatch.setattr(listener, "HERMES_BIN", "/opt/hermes/bin/hermes")
    monkeypatch.setattr(listener, "log", lambda _line: None)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(listener.subprocess, "run", fake_run)
    message = "Print complete: Stand\nMEDIA:/cache/stand.discord.mp4"

    assert listener.post(message) is True
    assert calls == [(
        ["/opt/hermes/bin/hermes", "-p", "3dprinting", "send", "--quiet",
         "--to", "discord:channel-42", message],
        {"capture_output": True, "text": True, "timeout": 120},
    )]


def test_post_reports_cli_rejection_as_delivery_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(listener, "DISCORD_TARGET", "discord:channel-42")
    monkeypatch.setattr(listener, "log", calls.append)
    monkeypatch.setattr(listener.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stderr="upload rejected"))

    assert listener.post("Print complete: Stand\nMEDIA:/cache/stand.mp4") is False
    assert any("rc=1" in line for line in calls)


def test_post_refuses_unconfigured_discord_target_without_sending(monkeypatch):
    calls = []
    monkeypatch.setattr(listener, "DISCORD_TARGET", "discord:")
    monkeypatch.setattr(listener, "log", calls.append)
    monkeypatch.setattr(listener.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    assert listener.post("Print complete: Stand\nMEDIA:/cache/stand.mp4") is False
    assert calls == ["post skipped: discord.chat_id is not configured"]
