"""Offline delivery regression coverage. Never contacts Discord or a printer."""
from print_buddy.hermes import moonraker_event_listener as listener


def test_failed_completion_retries_and_success_survives_restart(monkeypatch, tmp_path):
    announcer = listener.announcer
    monkeypatch.setattr(announcer, "STATE_PATH", tmp_path / "announcement.json")
    monkeypatch.setattr(announcer, "main", lambda: None)
    monkeypatch.setattr(listener, "log", lambda text: None)
    announcer.save_state({"job_key": "stand", "pending_completion_message": "Print complete: Stand"})
    attempts = []
    results = iter([False, True])
    monkeypatch.setattr(listener, "post", lambda text: attempts.append(text) or next(results))
    listener.run_announcer("failure")
    assert announcer.load_state()["pending_completion_message"]
    listener.run_announcer("retry")
    assert not announcer.load_state().get("pending_completion_message")
    assert announcer.load_state()["announced_completion"] is True
    listener.run_announcer("restart")
    assert attempts == ["Print complete: Stand"] * 2


def test_video_success_acknowledges_pending_completion(monkeypatch, tmp_path):
    announcer = listener.announcer
    monkeypatch.setattr(announcer, "STATE_PATH", tmp_path / "announcement.json")
    announcer.save_state({"pending_completion_message": "Print complete: Stand"})
    monkeypatch.setattr(announcer, "archive_completed_timelapse", lambda key: "/archive/stand.mp4")
    monkeypatch.setattr(announcer, "materialize_archived_timelapse", lambda path: "/cache/stand.mp4")
    monkeypatch.setattr(listener, "discord_sized_video", lambda path: path)
    monkeypatch.setattr(listener, "post", lambda text: True)
    listener._timelapse_post("stand", "Print complete: Stand")
    assert not announcer.load_state().get("pending_completion_message")
    assert announcer.load_state()["announced_completion"] is True
