"""#622: MQTT is off by default, and a publish carries the event. Failures do not raise."""
from print_handy.notify import emit, event_for


class _Sock:
    def __init__(self):
        self.sent = b""

    def sendall(self, data):
        self.sent += data

    def close(self):
        pass


def test_events_map_and_stay_off_without_a_host(monkeypatch):
    assert event_for("started") == "print_started"
    assert event_for("paused", "filament runout on slot 2") == "runout"
    assert event_for("complete") == "complete"
    assert event_for("slice") == ""
    monkeypatch.setattr("print_handy.notify._settings", lambda: {"mqtt_enabled": False, "mqtt_host": "broker"})
    assert emit("print_started", "duck", connector=lambda *_: (_ for _ in ()).throw(AssertionError("connected"))) is False


def test_enabled_publish_names_the_topic_and_a_refused_broker_does_not_raise(monkeypatch):
    sock = _Sock()
    monkeypatch.setattr("print_handy.notify._settings", lambda: {
        "mqtt_enabled": True, "mqtt_host": "broker.local", "mqtt_port": 1883, "mqtt_topic": "print-handy",
    })
    assert emit("complete", "plate 1 finished", printer_id="ad5x", connector=lambda host, port: sock) is True
    assert b"print-handy/complete" in sock.sent
    assert b"ad5x: plate 1 finished" in sock.sent

    def refuse(host, port):
        raise OSError("refused")

    assert emit("failed", "stopped", connector=refuse) is False


def test_password_is_env_only_and_absent_from_settings_and_diagnostics(monkeypatch, tmp_path):
    """The token is read from the environment. It is not a settings key and not in a bundle."""
    import yaml
    from print_handy.diagnostics_bundle import build_bundle
    from print_handy.settings import OPTIONAL_KEYS, SettingsError, _check_keys

    secret = "mqtt-secret-not-for-yaml-9f3c"
    monkeypatch.setenv("MQTT_PASSWORD", secret)
    assert ("notify", "mqtt_password") not in OPTIONAL_KEYS
    notify = {"mqtt_enabled": True, "mqtt_host": "broker.local", "mqtt_port": 1883,
              "mqtt_topic": "print-handy", "mqtt_username": "ha"}
    written = tmp_path / "home.yaml"
    written.write_text(yaml.safe_dump({"notify": notify}), encoding="utf-8")
    assert secret not in written.read_text(encoding="utf-8")
    try:
        _check_keys({}, {"notify": {**notify, "mqtt_password": secret}}, "home.yaml")
    except SettingsError as exc:
        assert "notify" in str(exc)
    else:
        raise AssertionError("a password key was accepted as a setting")

    sock = _Sock()
    monkeypatch.setattr("print_handy.notify._settings", lambda: dict(notify))
    assert emit("paused", "Print paused: duck", connector=lambda host, port: sock) is True
    assert secret.encode() in sock.sent
    assert secret not in written.read_text(encoding="utf-8")

    bundle = build_bundle({
        "notify": notify,
        "logging": {},
        "printers": [],
        "paths": {"hermes_home": tmp_path},
    }, include_doctor=False)
    assert secret not in bundle
    leaky = build_bundle({
        "notify": {**notify, "mqtt_password": secret},
        "logging": {},
        "printers": [],
        "paths": {"hermes_home": tmp_path},
    }, include_doctor=False)
    assert secret not in leaky


def test_recorded_pause_notifies_once_and_the_chat_post_still_returns(monkeypatch):
    import print_handy.hermes.discord_print_summary as summary
    monkeypatch.setattr(summary, "find_job", lambda *args, **kwargs: (None, None))
    calls = []

    def capture(kind, text, **kwargs):
        calls.append((kind, text))
        return True

    class _Now:
        """Runs the publish where the test can see it; production starts a daemon thread."""
        def __init__(self, target, args=(), daemon=None):
            self.run = lambda: target(*args)

        def start(self):
            self.run()

    monkeypatch.setattr(summary.threading, "Thread", _Now)
    monkeypatch.setattr("print_handy.notify.emit", capture)
    message = summary.format_event("paused", "plate.gcode")
    assert message.startswith("Print paused")
    assert calls == [("paused", message)]

    def refuse(*args, **kwargs):
        raise OSError("refused")

    monkeypatch.setattr("print_handy.notify.emit", refuse)
    again = summary.format_event("paused", "plate.gcode")
    assert again.startswith("Print paused")


def test_name_lookup_never_publishes_and_a_publish_never_blocks_the_caller(monkeypatch):
    import threading
    import print_handy.hermes.discord_print_summary as summary
    monkeypatch.setattr(summary, "find_job", lambda *args, **kwargs: (None, None))
    gate = threading.Event()
    calls = []

    def slow(kind, text, **kwargs):
        gate.wait(5)
        calls.append(kind)
        return True

    monkeypatch.setattr("print_handy.notify.emit", slow)
    summary.format_event("started", "plate.gcode", emit=False)
    summary.format_event("started", "plate.gcode")  # returns while the publish is still waiting
    assert calls == []
    gate.set()
    for thread in threading.enumerate():
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(2)
    assert calls == ["print_started"]


def test_connack_refusal_is_reported_and_client_ids_differ(monkeypatch):
    class Broker(_Sock):
        def __init__(self, reply):
            super().__init__()
            self.reply = reply

        def recv(self, n):
            return self.reply

    monkeypatch.setattr("print_handy.notify._settings", lambda: {
        "mqtt_enabled": True, "mqtt_host": "broker.local", "mqtt_topic": "print-handy"})
    ok, refused, silent = Broker(b"\x20\x02\x00\x00"), Broker(b"\x20\x02\x00\x05"), Broker(b"")
    assert emit("complete", "done", connector=lambda *_: ok) is True
    assert emit("complete", "done", connector=lambda *_: refused) is False
    assert emit("complete", "done", connector=lambda *_: silent) is False
    other = Broker(b"\x20\x02\x00\x00")
    emit("complete", "done", connector=lambda *_: other)
    assert ok.sent[:30] != other.sent[:30]
