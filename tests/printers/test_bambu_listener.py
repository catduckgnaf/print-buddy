"""Bambu Lab listener (#299 Stage B / #298 Stage 3): offline tests only — a fake MQTT
client and a fake clock, never a socket, never a real printer.

The disciplines pinned here are the #298 Stage 0 audit's corrected facts:
pushall on (re)connect with no periodic cadence, the ack-echo guard, merged
partial frames, 60 s staleness with a hard-reset reconnect (fresh client,
30 s cooldown), and a read-only session (only get_version / pushall are
ever published).
"""
import json

import pytest

from print_buddy import healthcheck, printers, settings
from print_buddy.printers.bambulab.client import BambuLanError
from print_buddy.printers.bambulab.listener import (RECONNECT_COOLDOWN_S,
                                                    STALE_AFTER_S,
                                                    BambuListener)

SERIAL = "00M00A000000000"
CODE = "12345678"
KNOWN_HMS = {"attr": 0x03000200, "code": 0x00010008}  # as in test_bambu_hms.py


class FakeMessage:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()


class FakeMqtt:
    """Scripted paho-shaped stand-in. `script` items are delivered one per loop() call;
    `tick` (optional) runs at the top of each loop() so tests can advance a fake clock."""

    def __init__(self, script=(), connect_rc=0, tick=None, stop_on_empty=False):
        self.script = list(script)
        self.connect_rc = connect_rc
        self.tick = tick
        self.stop_on_empty = stop_on_empty
        self.published = []
        self.subscribed = []
        self.connected_to = None
        self.connect_at = None
        self.disconnected = False
        self.on_connect = None
        self.on_message = None

    def connect(self, host, port, keepalive=0):
        self.connected_to = (host, port, keepalive)
        self.on_connect(self, None, None, self.connect_rc)

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def publish(self, topic, payload):
        self.published.append((topic, json.loads(payload)))
        return type("Result", (), {"rc": 0})()

    def loop(self, timeout=0):
        if self.tick:
            self.tick()
        if self.script:
            self.on_message(self, None, FakeMessage(self.script.pop(0)))
        elif self.stop_on_empty and self.on_empty is not None:
            self.on_empty()
        return 0

    def disconnect(self):
        self.disconnected = True

    on_empty = None


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def full(state="IDLE", **overrides):
    frame = {"command": "push_status", "msg": 0, "gcode_state": state,
             "mc_percent": 0, "mc_remaining_time": 0, "nozzle_temper": 24.0,
             "nozzle_target_temper": 0, "bed_temper": 23.0, "bed_target_temper": 0,
             "subtask_name": "", "layer_num": 0, "total_layer_num": 0,
             "fun": "3EC18FFF9CFF", "print_error": 0}
    frame.update(overrides)
    return {"print": frame}


def delta(**overrides):
    frame = {"command": "push_status", "msg": 1}
    frame.update(overrides)
    return {"print": frame}


VERSION = {"info": {"command": "get_version", "module": [{"name": "mc", "hw_ver": "N2S"}]}}


def lan_adapter(monkeypatch):
    monkeypatch.setenv("BAMBU_LAN_PASSWORD", CODE)
    cfg = settings.load(local=False, environ={
        "PRINT_BUDDY__PRINTER__MODEL": "bambulab.a1",
        "PRINT_BUDDY__BAMBU__LAN_HOST": "192.168.1.50",
        "PRINT_BUDDY__BAMBU__LAN_SERIAL": SERIAL.lower()})
    return printers.get("bambulab.a1", cfg)


def make_listener(monkeypatch, fakes):
    clock = FakeClock()
    queue = list(fakes)
    beats = []
    listener = BambuListener(
        lan_adapter(monkeypatch),
        mqtt_factory=lambda host, serial, code: queue.pop(0),
        clock=clock, sleep=clock.sleep,
        beat=lambda **details: beats.append(details))
    for fake in fakes:
        fake.on_empty = listener.stop
    return listener, clock, beats


def kinds(listener):
    return [(event["kind"], event.get("transition")) for event in listener.events]


# --------------------------------------------------------------------- session discipline

def test_connect_requests_version_then_pushall_and_merges(monkeypatch):
    fake = FakeMqtt([VERSION, full("RUNNING", mc_percent=42, subtask_name="benchy.gcode.3mf",
                                   layer_num=12, total_layer_num=40)], stop_on_empty=True)
    listener, _clock, _beats = make_listener(monkeypatch, [fake])
    assert listener.run_forever() == 0
    assert fake.connected_to == ("192.168.1.50", 8883, 30)
    assert fake.subscribed == [f"device/{SERIAL}/report"]
    assert [body for _topic, body in fake.published] == [
        {"info": {"sequence_id": "0", "command": "get_version"}},
        {"pushing": {"sequence_id": "0", "command": "pushall"}}]
    assert listener._print["mc_percent"] == 42 and listener._complete is True
    assert fake.disconnected


def test_ack_frames_are_not_telemetry(monkeypatch):
    fake = FakeMqtt([
        full("RUNNING", mc_percent=10, subtask_name="a.gcode.3mf", layer_num=1, total_layer_num=9),
        {"print": {"command": "project_file", "result": "success", "gcode_state": "IDLE"}},
        {"print": {"command": "print_option", "gcode_state": "PAUSE"}},
    ], stop_on_empty=True)
    listener, _clock, _beats = make_listener(monkeypatch, [fake])
    listener.run_forever()
    assert listener._print["gcode_state"] == "RUNNING"  # acks did not move state
    assert ("status", "paused") not in kinds(listener)
    assert listener._status["state"] == "printing"


def test_partial_frames_merge_into_persistent_state(monkeypatch):
    fake = FakeMqtt([
        delta(gcode_state="RUNNING", mc_percent=10, subtask_name="a.gcode.3mf",
              nozzle_temper=200.0, layer_num=3, total_layer_num=9),
        delta(mc_percent=25),
        delta(mc_percent=30),
    ], stop_on_empty=True)
    listener, _clock, _beats = make_listener(monkeypatch, [fake])
    listener.run_forever()
    status = listener._status
    assert status["progress"] == 0.30 and status["filename"] == "a.gcode.3mf"
    assert status["hotend_c"] == 200.0 and status["layer"] == 3


def test_access_denied_is_a_plain_error_and_nothing_is_published(monkeypatch):
    fake = FakeMqtt(connect_rc=5)
    listener, _clock, _beats = make_listener(monkeypatch, [fake])
    with pytest.raises(BambuLanError, match="rejected the LAN access code"):
        listener._session()
    assert fake.published == [] and CODE not in "rejected the LAN access code"


def test_stale_session_hard_resets_with_cooldown_and_a_fresh_client(monkeypatch):
    clock_holder = {}

    def tick():
        clock_holder["clock"].t += 10.0

    fake1 = FakeMqtt([full("IDLE")], tick=tick)
    fake2 = FakeMqtt([full("IDLE")], stop_on_empty=True)
    listener, clock, _beats = make_listener(monkeypatch, [fake1, fake2])
    clock_holder["clock"] = clock
    connect_times = []
    for fake in (fake1, fake2):
        original = fake.connect

        def recording_connect(host, port, keepalive=0, _fake=fake, _orig=original):
            connect_times.append(clock.t)
            return _orig(host, port, keepalive)

        fake.connect = recording_connect
    listener.run_forever()
    assert fake1.disconnected and fake1 is not fake2
    assert len(connect_times) == 2
    assert connect_times[1] - connect_times[0] >= STALE_AFTER_S + RECONNECT_COOLDOWN_S - 10
    # The fresh client re-runs the full connect discipline: version, then pushall.
    assert [body for _t, body in fake2.published] == [
        {"info": {"sequence_id": "0", "command": "get_version"}},
        {"pushing": {"sequence_id": "0", "command": "pushall"}}]


def test_layer1_pushall_once_when_total_unknown_and_never_periodically(monkeypatch):
    frame = full("RUNNING", mc_percent=1, subtask_name="a.gcode.3mf", layer_num=1)
    del frame["print"]["total_layer_num"]
    fake = FakeMqtt([frame, dict(frame), dict(frame)], stop_on_empty=True)
    listener, _clock, _beats = make_listener(monkeypatch, [fake])
    listener.run_forever()
    pushalls = [b for _t, b in fake.published if b.get("pushing", {}).get("command") == "pushall"]
    assert len(pushalls) == 2  # the connect pushall + the single layer-1 refresh
    assert all(set(body) <= {"info", "pushing"} for _t, body in fake.published)  # read-only


# --------------------------------------------------------------------- events

def test_transitions_emit_contract_events_deduped(monkeypatch):
    fake = FakeMqtt([
        full("RUNNING", subtask_name="a.gcode.3mf", layer_num=1, total_layer_num=9),
        full("RUNNING", subtask_name="a.gcode.3mf", layer_num=1, total_layer_num=9),
        delta(gcode_state="PAUSE"),
        delta(gcode_state="RUNNING"),
        delta(gcode_state="FINISH", mc_percent=100),
        delta(gcode_state="FINISH", mc_percent=100),
        full("RUNNING", subtask_name="b.gcode.3mf", layer_num=1, total_layer_num=4),
        delta(gcode_state="IDLE"),
    ], stop_on_empty=True)
    listener, _clock, _beats = make_listener(monkeypatch, [fake])
    listener.run_forever()
    assert kinds(listener) == [
        ("status", "started"), ("snapshot_available", None),
        ("status", "paused"), ("status", "resumed"),
        ("status", None), ("completion", "finished"),
        ("status", "started"), ("status", "cancelled"),
    ]


def test_error_event_carries_decoded_hms(monkeypatch):
    fake = FakeMqtt([
        full("RUNNING", subtask_name="a.gcode.3mf", layer_num=1, total_layer_num=9),
        delta(gcode_state="FAILED", hms=[KNOWN_HMS]),
        delta(gcode_state="FAILED", hms=[KNOWN_HMS]),
    ], stop_on_empty=True)
    listener, _clock, _beats = make_listener(monkeypatch, [fake])
    listener.run_forever()
    errors = [event for event in listener.events if event["kind"] == "error"]
    assert len(errors) == 1  # repeated FAILED frame does not re-emit
    assert errors[0]["hms_errors"] and errors[0]["hms_errors"][0]["code"]


def test_status_events_validate_against_the_contract(monkeypatch):
    from print_buddy import listeners
    fake = FakeMqtt([full("RUNNING", subtask_name="a.gcode.3mf", mc_percent=5,
                          layer_num=2, total_layer_num=9)], stop_on_empty=True)
    listener, _clock, _beats = make_listener(monkeypatch, [fake])
    listener.run_forever()
    assert listener.events  # at least the started status event
    for event in listener.events:
        assert listeners.validate_status(event["status"]) == []


# --------------------------------------------------------------------- liveness / configuration

def test_unconfigured_listener_idles_beats_and_never_touches_the_network(monkeypatch):
    cfg = settings.load(local=False, environ={"PRINT_BUDDY__PRINTER__MODEL": "bambulab.a1"})
    adapter = printers.get("bambulab.a1", cfg)
    beats = []
    calls = {"sleeps": 0}

    def factory(*_args):
        raise AssertionError("an unconfigured listener must not build an MQTT client")

    def sleep(seconds):
        calls["sleeps"] += 1
        if calls["sleeps"] >= 3:
            listener.stop()

    listener = BambuListener(adapter, mqtt_factory=factory, sleep=sleep,
                             beat=lambda **details: beats.append(details))
    assert listener.active is False
    assert listener.run_forever() == 0
    assert beats and all(b["printer_connected"] is False for b in beats)


def test_heartbeat_uses_the_bambu_runtime_and_satisfies_the_healthcheck(monkeypatch, tmp_path):
    path = tmp_path / "listener_health.json"
    monkeypatch.setattr(healthcheck, "heartbeat_path", lambda data=None: path)
    listener, _clock, _beats = make_listener(monkeypatch, [FakeMqtt()])
    listener._beat_fn = lambda **details: healthcheck.beat(runtime="bambu_event_listener",
                                                            **details)
    listener._beat_now()
    record = json.loads(path.read_text())
    assert record["runtime"] == "bambu_event_listener"
    ok, _reason = healthcheck.check({"printer": {"model": "bambulab.a1"}})
    assert ok
