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
