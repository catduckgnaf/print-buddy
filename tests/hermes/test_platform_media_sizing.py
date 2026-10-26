"""Issue #314: the listener sizes timelapse video to the configured platform's limit.

Offline throughout: configs come from the real settings loader (env
only), ffmpeg is a stub that writes a file of a chosen size, and the
Telegram/Matrix senders run against stubbed urlopen transports — no
network, no live platform. Discord's sizing and wording are pinned
byte-for-byte against what they were before the generalisation.
"""
import io
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from print_buddy import settings
from print_buddy.bot import matrix_rest
from print_buddy.hermes import moonraker_event_listener as mel

COMPLETE = "Print complete: Stand"


def _use_settings(monkeypatch, **environ):
    """Install a config built by the real settings loader as the listener's config."""
    data = settings.load(local=False, environ=environ)
    monkeypatch.setattr(mel._config, "_override", data)
    return data


def _video(tmp_path, size, name="stand.mp4"):
    path = tmp_path / name
    path.write_bytes(b"v" * size)
    return path


def _fake_ffmpeg(monkeypatch, out_size):
    """Stub the encode: each ffmpeg run writes out_size bytes to its target file."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"s" * out_size)
        return mel.subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(mel, "_video_duration", lambda path: 60.0)
    monkeypatch.setattr(mel.subprocess, "run", fake_run)
    return calls


def _no_ffmpeg(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("ffmpeg must not run for a video that already fits")

    monkeypatch.setattr(mel, "_video_duration", boom)
    monkeypatch.setattr(mel.subprocess, "run", boom)


def _matrix_helpers(monkeypatch, server_limit):
    monkeypatch.setattr(mel, "_matrix_token", lambda: "syt_test")
    monkeypatch.setattr(mel, "_matrix_homeserver", lambda: "https://matrix.example.org")
    monkeypatch.setattr(matrix_rest, "media_config", lambda hs, tok: server_limit)


MATRIX_ENV = {
    "PRINT_BUDDY__BOT__MODE": "standalone",
    "PRINT_BUDDY__BOT__PLATFORM": "matrix",
    "PRINT_BUDDY__MATRIX__HOMESERVER_URL": "https://matrix.example.org",
    "PRINT_BUDDY__MATRIX__ROOM_ID": "!prints:example.org",
}


# --------------------------------------------------------------- the resolution


def test_limit_resolution_discord_default_and_override(monkeypatch):
    _use_settings(monkeypatch)
    assert mel._media_upload_limit() == 9_500_000
    _use_settings(monkeypatch, PRINT_BUDDY__DISCORD__UPLOAD_MAX_BYTES="4000000")
    assert mel._media_upload_limit() == 4_000_000


def test_limit_resolution_telegram_default_and_configured(monkeypatch):
    _use_settings(monkeypatch, PRINT_BUDDY__BOT__PLATFORM="telegram")
    assert mel._media_upload_limit() == 50_000_000
    _use_settings(monkeypatch, PRINT_BUDDY__BOT__PLATFORM="telegram",
                  PRINT_BUDDY__TELEGRAM__UPLOAD_MAX_BYTES="5000000")
    assert mel._media_upload_limit() == 5_000_000


def test_limit_resolution_matrix_configured_without_server_value(monkeypatch):
    _use_settings(monkeypatch, **MATRIX_ENV, PRINT_BUDDY__MATRIX__UPLOAD_MAX_BYTES="6000000")
    _matrix_helpers(monkeypatch, None)  # the server reports no m.upload.size
    assert mel._media_upload_limit() == 6_000_000


def test_limit_resolution_matrix_server_clamps_below_configured(monkeypatch):
    _use_settings(monkeypatch, **MATRIX_ENV)  # configured default is 50 MB
    _matrix_helpers(monkeypatch, 5_000_000)
    assert mel._media_upload_limit() == 5_000_000


def test_limit_resolution_matrix_configured_wins_when_smaller(monkeypatch):
    _use_settings(monkeypatch, **MATRIX_ENV, PRINT_BUDDY__MATRIX__UPLOAD_MAX_BYTES="4000000")
    _matrix_helpers(monkeypatch, 5_000_000)
    assert mel._media_upload_limit() == 4_000_000


def test_limit_resolution_matrix_clamp_failure_degrades_to_configured(monkeypatch):
    _use_settings(monkeypatch, **MATRIX_ENV, PRINT_BUDDY__MATRIX__UPLOAD_MAX_BYTES="6000000")
    monkeypatch.setattr(mel, "_matrix_token", lambda: "syt_test")
    monkeypatch.setattr(mel, "_matrix_homeserver", lambda: "https://matrix.example.org")

    def boom(hs, tok):
        raise RuntimeError("homeserver unreachable")

    monkeypatch.setattr(matrix_rest, "media_config", boom)
    assert mel._media_upload_limit() == 6_000_000


# --------------------------------------------------------------- shrink behaviour


def test_telegram_sizing_passes_a_discord_oversized_video_through(monkeypatch, tmp_path):
    _use_settings(monkeypatch, PRINT_BUDDY__BOT__MODE="standalone", PRINT_BUDDY__BOT__PLATFORM="telegram")
    _no_ffmpeg(monkeypatch)
    source = _video(tmp_path, 20_000_000)  # over Discord's cap, under Telegram's 50 MB
    assert mel.platform_sized_video(source) == source


def test_telegram_sizing_uses_the_configured_telegram_value(monkeypatch, tmp_path):
    _use_settings(monkeypatch, PRINT_BUDDY__BOT__MODE="standalone", PRINT_BUDDY__BOT__PLATFORM="telegram",
                  PRINT_BUDDY__TELEGRAM__UPLOAD_MAX_BYTES="5000000")
    calls = _fake_ffmpeg(monkeypatch, 4_000_000)
    result = mel.platform_sized_video(_video(tmp_path, 20_000_000))
    assert result.name == "stand.sized.mp4" and result.stat().st_size == 4_000_000
    assert "600k" in calls[0]  # the bitrate budget came from the 5 MB Telegram value


def test_discord_sizing_is_unchanged(monkeypatch, tmp_path):
    _use_settings(monkeypatch)
    calls = _fake_ffmpeg(monkeypatch, 9_000_000)
    result = mel.platform_sized_video(_video(tmp_path, 20_000_000))
    assert result.name == "stand.sized.mp4" and result.stat().st_size == 9_000_000
    assert "1140k" in calls[0]  # 9.5 MB budget over 60 s, as before


def test_matrix_sizing_uses_the_configured_matrix_value(monkeypatch, tmp_path):
    _use_settings(monkeypatch, **MATRIX_ENV, PRINT_BUDDY__MATRIX__UPLOAD_MAX_BYTES="6000000")
    _matrix_helpers(monkeypatch, None)
    _fake_ffmpeg(monkeypatch, 5_500_000)
    result = mel.platform_sized_video(_video(tmp_path, 7_000_000))
    assert result.stat().st_size == 5_500_000


def test_matrix_sizing_shrinks_to_the_homeserver_limit_below_the_discord_cap(monkeypatch, tmp_path):
    _use_settings(monkeypatch, **MATRIX_ENV)
    _matrix_helpers(monkeypatch, 5_000_000)
    _fake_ffmpeg(monkeypatch, 4_900_000)
    source = _video(tmp_path, 8_000_000)  # fits the Discord cap: the old sizing passed it through
    result = mel.platform_sized_video(source)
    assert result != source and result.stat().st_size == 4_900_000


# --------------------------------------------------------------- encoder choice


def _fake_ffmpeg_unless(monkeypatch, out_size, fail_token):
    """Fake ffmpeg that fails any command containing fail_token, encodes otherwise."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if fail_token and fail_token in cmd:
            raise subprocess.CalledProcessError(1, cmd)
        Path(cmd[-1]).write_bytes(b"s" * out_size)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(mel, "_video_duration", lambda path: 60.0)
    monkeypatch.setattr(mel.subprocess, "run", fake_run)
    return calls


def test_shrink_is_an_ffmpeg_cpu_encode_by_default(monkeypatch, tmp_path):
    _use_settings(monkeypatch)
    calls = _fake_ffmpeg(monkeypatch, 9_000_000)
    mel.platform_sized_video(_video(tmp_path, 20_000_000))
    argv = calls[0]
    assert argv[0] == mel.FFMPEG_BIN  # the compressor is ffmpeg itself
    assert "libx264" in argv
    assert not {"h264_vaapi", "h264_qsv", "h264_nvenc", "-vaapi_device"} & set(argv)


def test_shrink_uses_the_configured_nvenc_encoder(monkeypatch, tmp_path):
    _use_settings(monkeypatch, PRINT_BUDDY__TIMELAPSE__ENCODER="nvenc")
    calls = _fake_ffmpeg(monkeypatch, 9_000_000)
    mel.platform_sized_video(_video(tmp_path, 20_000_000))
    assert "h264_nvenc" in calls[0] and "libx264" not in calls[0]


def test_shrink_uses_the_configured_vaapi_encoder_with_device_and_upload(monkeypatch, tmp_path):
    _use_settings(monkeypatch, PRINT_BUDDY__TIMELAPSE__ENCODER="vaapi")
    calls = _fake_ffmpeg(monkeypatch, 9_000_000)
    mel.platform_sized_video(_video(tmp_path, 20_000_000))
    argv = calls[0]
    assert "h264_vaapi" in argv
    assert argv[argv.index("-vaapi_device") + 1] == "/dev/dri/renderD128"
    assert "hwupload" in argv[argv.index("-vf") + 1]


def test_hardware_encode_failure_falls_back_to_cpu(monkeypatch, tmp_path):
    _use_settings(monkeypatch, PRINT_BUDDY__TIMELAPSE__ENCODER="nvenc")
    calls = _fake_ffmpeg_unless(monkeypatch, 9_000_000, "h264_nvenc")
    result = mel.platform_sized_video(_video(tmp_path, 20_000_000))
    assert result.stat().st_size == 9_000_000  # the shrink still succeeded...
    assert "h264_nvenc" in calls[0] and "libx264" in calls[1]  # ...via the CPU retry


def test_cpu_encode_failure_still_raises_for_the_callers_fallback(monkeypatch, tmp_path):
    _use_settings(monkeypatch)
    _fake_ffmpeg_unless(monkeypatch, 9_000_000, "libx264")
    with pytest.raises(subprocess.CalledProcessError):
        mel.platform_sized_video(_video(tmp_path, 20_000_000))


def test_settings_reject_an_unknown_timelapse_encoder():
    with pytest.raises(settings.SettingsError):
        settings.load(local=False, environ={"PRINT_BUDDY__TIMELAPSE__ENCODER": "bogus"})


# --------------------------------------------------------------- failure wording


def test_too_big_wording_discord_is_byte_for_byte_the_old_text(monkeypatch):
    _use_settings(monkeypatch, PRINT_BUDDY__BOT__MODE="standalone", PRINT_BUDDY__BOT__PLATFORM="discord")
    assert mel._timelapse_too_big_text("stand.mp4") == "Timelapse archived but too big for Discord: stand.mp4"
    assert mel._timelapse_too_big_text(combined=True) == "Combined timelapse too big for Discord."


def test_too_big_wording_matrix_names_the_server_limit(monkeypatch):
    _use_settings(monkeypatch, **MATRIX_ENV)
    assert mel._timelapse_too_big_text("stand.mp4") == \
        "Timelapse was recorded but is too large for this Matrix server's upload limit."
    assert mel._timelapse_too_big_text(combined=True) == \
        "Combined timelapse was recorded but is too large for this Matrix server's upload limit."


def test_too_big_wording_telegram(monkeypatch):
    _use_settings(monkeypatch, PRINT_BUDDY__BOT__MODE="standalone", PRINT_BUDDY__BOT__PLATFORM="telegram")
    assert mel._timelapse_too_big_text("stand.mp4") == \
        "Timelapse was recorded but is too large for Telegram's upload limit."
    assert mel._timelapse_too_big_text(combined=True) == \
        "Combined timelapse was recorded but is too large for Telegram's upload limit."


def test_discord_fallback_post_is_byte_for_byte_unchanged(monkeypatch, tmp_path):
    _use_settings(monkeypatch, PRINT_BUDDY__BOT__MODE="standalone", PRINT_BUDDY__BOT__PLATFORM="discord")
    posted, results = [], [False, True]
    monkeypatch.setattr(mel, "log", lambda line: None)
    monkeypatch.setattr(mel, "post", lambda message: posted.append(message) or results.pop(0))
    monkeypatch.setattr(mel.announcer, "archive_completed_timelapse", lambda key: "/volume1/x/stand.mp4")
    monkeypatch.setattr(mel.announcer, "materialize_archived_timelapse", lambda path: "/cache/stand.mp4")
    monkeypatch.setattr(mel, "platform_sized_video", lambda path, max_bytes=None: path)
    mel._timelapse_post("stand.gcode", COMPLETE)
    assert posted[0] == f"{COMPLETE}\nMEDIA:/cache/stand.mp4"
    assert posted[1] == f"{COMPLETE}\nTimelapse archived but too big for Discord: stand.mp4"


# --------------------------------------------------------------- offline end-to-end


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _wire_completion(monkeypatch, tmp_path, video):
    """Point the announcer at a finished print whose timelapse is `video`."""
    monkeypatch.setattr(mel, "log", lambda line: None)
    monkeypatch.setattr(mel.announcer, "STATE_PATH", tmp_path / "announcement.json")
    mel.announcer.save_state({"pending_completion_message": COMPLETE})
    monkeypatch.setattr(mel.announcer, "archive_completed_timelapse", lambda key: "/archive/stand.mp4")
    monkeypatch.setattr(mel.announcer, "materialize_archived_timelapse", lambda path: str(video))


class FakeHomeserver:
    """A Matrix homeserver behind urllib: config, media upload, room sends."""

    def __init__(self, upload_size):
        self.upload_size = upload_size
        self.uploads = []   # (filename, byte count) accepted uploads
        self.events = []    # every m.room.message body posted

    def __call__(self, req, timeout=None):
        split = urllib.parse.urlsplit(req.full_url)
        if split.path.endswith("/media/v3/config"):
            return _Response(json.dumps({"m.upload.size": self.upload_size}).encode())
        if split.path.endswith("/media/v3/upload"):
            data = req.data or b""
            if len(data) > self.upload_size:
                raise urllib.error.HTTPError(req.full_url, 413, "Payload Too Large",
                                             None, io.BytesIO(b"too large"))
            filename = dict(urllib.parse.parse_qsl(split.query)).get("filename")
            self.uploads.append((filename, len(data)))
            return _Response(json.dumps({"content_uri": "mxc://example.org/media123"}).encode())
        if "/send/m.room.message/" in split.path:
            self.events.append(json.loads(req.data) if req.data else {})
            return _Response(json.dumps({"event_id": "$evt1"}).encode())
        raise AssertionError(f"unexpected homeserver call: {req.method} {req.full_url}")

    @property
    def texts(self):
        return [event.get("body", "") for event in self.events if event.get("msgtype") == "m.text"]


def test_matrix_completion_delivers_a_video_sized_to_the_homeserver(monkeypatch, tmp_path):
    _use_settings(monkeypatch, **MATRIX_ENV)
    monkeypatch.setattr(mel, "_matrix_token", lambda: "syt_test")
    server = FakeHomeserver(5_000_000)
    monkeypatch.setattr(urllib.request, "urlopen", server)
    _wire_completion(monkeypatch, tmp_path, _video(tmp_path, 8_000_000))
    _fake_ffmpeg(monkeypatch, 4_900_000)  # the shrink lands just under the server limit
    mel._timelapse_post("stand.gcode", COMPLETE)
    # The 8 MB timelapse (which the old Discord sizing would have passed
    # through untouched) was shrunk to fit this server and delivered.
    assert server.uploads == [("stand.sized.mp4", 4_900_000)]
    assert any(event.get("msgtype") == "m.video" and event["info"]["size"] == 4_900_000
               for event in server.events)
    assert server.texts == [COMPLETE]
    state = mel.announcer.load_state()
    assert "pending_completion_message" not in state and state.get("announced_completion") is True


def test_matrix_completion_below_the_floor_explains_instead_of_dropping(monkeypatch, tmp_path):
    _use_settings(monkeypatch, **MATRIX_ENV)
    monkeypatch.setattr(mel, "_matrix_token", lambda: "syt_test")
    server = FakeHomeserver(100_000)  # below the smallest video the shrink can produce
    monkeypatch.setattr(urllib.request, "urlopen", server)
    _wire_completion(monkeypatch, tmp_path, _video(tmp_path, 8_000_000))
    _fake_ffmpeg(monkeypatch, 200_000)  # both bitrate attempts still exceed the limit
    mel._timelapse_post("stand.gcode", COMPLETE)
    assert server.uploads == []  # nothing was delivered...
    assert server.texts == [COMPLETE,  # ...the completion itself still posted...
                            f"{COMPLETE}\nTimelapse was recorded but is too large for "
                            "this Matrix server's upload limit."]  # ...and says why, plainly
    assert all(event.get("msgtype") == "m.text" for event in server.events)  # no delivery claimed
    state = mel.announcer.load_state()
    assert "pending_completion_message" not in state and state.get("announced_completion") is True


class FakeTelegram:
    """The Bot API behind urllib: records every method call and its raw payload."""

    def __init__(self):
        self.calls = []  # (method, payload bytes)

    def __call__(self, req, timeout=None):
        method = urllib.parse.urlsplit(req.full_url).path.rsplit("/", 1)[-1]
        self.calls.append((method, req.data or b""))
        return _Response(json.dumps({"ok": True, "result": {"message_id": 7}}).encode())


def test_telegram_completion_delivers_the_full_size_timelapse(monkeypatch, tmp_path):
    _use_settings(monkeypatch, PRINT_BUDDY__BOT__MODE="standalone", PRINT_BUDDY__BOT__PLATFORM="telegram",
                  PRINT_BUDDY__TELEGRAM__CHAT_ID="-100123")
    monkeypatch.setattr(mel, "_telegram_token", lambda: "123456:TEST")
    api = FakeTelegram()
    monkeypatch.setattr(urllib.request, "urlopen", api)
    _wire_completion(monkeypatch, tmp_path, _video(tmp_path, 12_000_000))
    _no_ffmpeg(monkeypatch)  # 12 MB is over Discord's cap but well under Telegram's: no shrink
    mel._timelapse_post("stand.gcode", COMPLETE)
    methods = [method for method, _ in api.calls]
    assert methods == ["sendMessage", "sendVideo"]
    video_payload = api.calls[1][1]
    assert len(video_payload) > 12_000_000 and b"stand.mp4" in video_payload
    state = mel.announcer.load_state()
    assert "pending_completion_message" not in state and state.get("announced_completion") is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
