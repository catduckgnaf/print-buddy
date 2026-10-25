"""Bambu Lab print start (#187 stage d): offline tests only — fake MQTT/FTPS, stubbed seams.

Two layers: the client's command payloads are pinned exactly against a fake MQTT client,
and model_job._print_bambu is driven with the guard seams stubbed (G-code verification,
packaging, lease, approval, start record — all covered by their own suites) to prove the
orchestration: clean gates refuse before anything is sent, the approval is consumed inside
the lease before the upload, and acceptance is confirmed from telemetry, never assumed.
"""
import json
import zipfile

import pytest

from print_buddy import printers, settings
from print_buddy.core import delivery, launch_state, model_job
from print_buddy.printers.bambulab.client import (BambuLanClient, BambuLanError,
                                                  project_file_payload)

SERIAL = "00M00A000000000"
CODE = "12345678"
DEV_ON = "3EC18FFF9CFF"   # fun bitfield with the signature bit clear (Developer Mode on)
DEV_OFF = "3EC1AFFF9CFF"  # signature bit set (Developer Mode off): every write is blocked


class FakeMessage:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()


class FakeMqtt:
    def __init__(self, script=(), connect_rc=0):
        self.script = list(script)
        self.connect_rc = connect_rc
        self.published = []
        self.on_connect = None
        self.on_message = None

    def connect(self, host, port, keepalive=0):
        self.on_connect(self, None, None, self.connect_rc)

    def subscribe(self, topic):
        pass

    def publish(self, topic, payload):
        self.published.append((topic, json.loads(payload)))
        return type("Result", (), {"rc": 0})()

    def loop(self, timeout=0):
        if self.script:
            self.on_message(self, None, FakeMessage(self.script.pop(0)))
        return 0

    def disconnect(self):
        pass


class FakeFTP:
    def __init__(self, fail_store=False):
        self.stored = {}
        self.fail_store = fail_store

    def storbinary(self, cmd, fp):
        if self.fail_store:
            raise OSError("connection reset by printer")
        self.stored[cmd.split(" ", 1)[1]] = fp.read()
        return "226 Transfer complete"

    def size(self, name):
        data = self.stored.get(name)
        return None if data is None else len(data)

    def quit(self):
        pass


def snapshot_script(state="IDLE", fun=DEV_ON, filename=""):
    version = {"info": {"command": "get_version", "module": [{"name": "ota", "sw_ver": "01.05.00.00"}]}}
    full = {"print": {"command": "push_status", "msg": 0, "gcode_state": state, "mc_percent": 0,
                      "subtask_name": filename, "fun": fun, "print_error": 0}}
    return [version, full]


def lan_adapter(monkeypatch):
    monkeypatch.setenv("BAMBU_LAN_PASSWORD", CODE)
    cfg = settings.load(local=False, environ={
        "PRINT_BUDDY__PRINTER__MODEL": "bambulab.a1",
        "PRINT_BUDDY__BAMBU__LAN_HOST": "192.168.1.50", "PRINT_BUDDY__BAMBU__LAN_SERIAL": SERIAL})
    return printers.get("bambulab.a1", cfg)


RECORD = {"bed_mm": [256, 256], "max_print_height_mm": 256,
          "nozzle": {"diameter_mm": 0.4, "type": "stainless_steel"}}


# --------------------------------------------------------------------- client commands

def test_start_print_publishes_the_project_file_payload():
    fake = FakeMqtt()
    client = BambuLanClient("192.168.1.50", SERIAL, CODE, mqtt_factory=lambda h, s, c: fake, timeout_s=5)
    client.start_print("benchy.gcode.3mf")
    [(topic, payload)] = fake.published
    assert topic == f"device/{SERIAL}/request"
    assert payload == project_file_payload("benchy.gcode.3mf")
    body = payload["print"]
    assert body["param"] == "Metadata/plate_1.gcode" and body["file"] == "benchy.gcode.3mf"
    assert body["url"] == "ftp:///benchy.gcode.3mf"
    # Print Buddy never asks for calibration passes it did not slice for, and never uses an AMS.
    assert not any(body[k] for k in ("bed_leveling", "flow_cali", "vibration_cali", "layer_inspect", "use_ams", "timelapse"))


def test_control_payloads_and_validation():
    fake = FakeMqtt()
    client = BambuLanClient("192.168.1.50", SERIAL, CODE, mqtt_factory=lambda h, s, c: fake, timeout_s=5)
    client.control("pause")
    assert fake.published[0][1] == {"print": {"sequence_id": "0", "command": "pause"}}
    calls = []
    guarded = BambuLanClient("192.168.1.50", SERIAL, CODE,
                             mqtt_factory=lambda h, s, c: calls.append(h) or fake, timeout_s=5)
    with pytest.raises(BambuLanError, match="unsupported Bambu Lab print control"):
        guarded.control("estop")
    with pytest.raises(BambuLanError, match="invalid plate path"):
        guarded.start_print("benchy.gcode.3mf", plate="plate_1.gcode")
    assert calls == []  # both refused before any connection


def test_command_access_denied_sends_nothing():
    fake = FakeMqtt(connect_rc=5)
    client = BambuLanClient("192.168.1.50", SERIAL, CODE, mqtt_factory=lambda h, s, c: fake, timeout_s=5)
    with pytest.raises(BambuLanError, match="access denied.*nothing was sent"):
        client.start_print("benchy.gcode.3mf")
    assert fake.published == []


# --------------------------------------------------------------------- _print_bambu orchestration

class FakeLease:
    def __init__(self, events):
        self.events = events

    def submitting(self):
        self.events.append("submitting")

    def uncertain(self, detail):
        self.events.append(f"uncertain:{detail[:20]}")

    def release(self):
        self.events.append("release")


@pytest.fixture
def rig(monkeypatch, tmp_path):
    """_print_bambu with every guard seam stubbed and an event log to prove the order."""
    events = []
    adapter = lan_adapter(monkeypatch)
    package = tmp_path / "plate_1.gcode.3mf"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", "G1 X1\n")
    gcode = tmp_path / "plate_1.gcode"
    gcode.write_text("G1 X1\n")
    ftp = FakeFTP()
    monkeypatch.setattr(model_job, "verify_gcode", lambda path: {"offline": True})
    monkeypatch.setattr(delivery, "bambu_handoff", lambda job, gcodes, config=None: [package])
    monkeypatch.setattr(launch_state, "acquire",
                        lambda *a, **kw: events.append("acquire") or FakeLease(events))
    monkeypatch.setattr(model_job, "_consume_approval",
                        lambda *a, **kw: events.append("consume_approval"))
    monkeypatch.setattr(model_job, "record_start", lambda g, remote: events.append("record") or "/records/1")
    return {"adapter": adapter, "package": package, "gcode": gcode, "ftp": ftp, "events": events,
            "job": {"printer_model": "bambulab.a1", "gcode": str(gcode)},
            "job_path": tmp_path / "JOB.json"}


def wire_client(monkeypatch, rig, scripts, ftp=None):
    """Point the adapter's client at scripted fakes: one FakeMqtt per MQTT connection, in order."""
    queue = iter(FakeMqtt(script) for script in scripts)
    client = BambuLanClient("192.168.1.50", SERIAL, CODE,
                            mqtt_factory=lambda h, s, c: next(queue),
                            ftp_factory=lambda h, c: ftp or rig["ftp"], timeout_s=5)
    monkeypatch.setattr(rig["adapter"], "client", lambda **kw: client)
    return client


def test_print_bambu_happy_path_order_and_confirmation(monkeypatch, rig):
    remote = rig["package"].name
    wire_client(monkeypatch, rig, [snapshot_script(), snapshot_script(), [],
                                   snapshot_script("RUNNING", filename=remote)])
    out = model_job._print_bambu(rig["adapter"], RECORD, rig["gcode"], rig["job"], rig["job_path"], 25, False)
    assert out["started"] is True and out["outcome"] == "printing" and out["file"] == remote
    assert rig["events"] == ["acquire", "consume_approval", "submitting", "release", "record"]
    assert rig["ftp"].stored[remote] == rig["package"].read_bytes()


def test_print_bambu_refuses_a_busy_printer_before_any_gate(monkeypatch, rig):
    wire_client(monkeypatch, rig, [snapshot_script("RUNNING")])
    with pytest.raises(SystemExit, match="REFUSED:.*busy"):
        model_job._print_bambu(rig["adapter"], RECORD, rig["gcode"], rig["job"], rig["job_path"], 25, False)
    assert rig["events"] == [] and rig["ftp"].stored == {}


def test_print_bambu_refuses_when_developer_mode_is_off(monkeypatch, rig):
    wire_client(monkeypatch, rig, [snapshot_script(fun=DEV_OFF)])
    with pytest.raises(SystemExit, match="REFUSED:.*Developer Mode is off"):
        model_job._print_bambu(rig["adapter"], RECORD, rig["gcode"], rig["job"], rig["job_path"], 25, False)
    assert rig["events"] == [] and rig["ftp"].stored == {}


def test_print_bambu_unconfirmed_start_is_uncertain_not_a_resubmit(monkeypatch, rig):
    wire_client(monkeypatch, rig, [snapshot_script(), snapshot_script(), [], snapshot_script()])
    out = model_job._print_bambu(rig["adapter"], RECORD, rig["gcode"], rig["job"], rig["job_path"], 25, False)
    assert out["started"] is False and out["phase"] == "awaiting_confirmation"
    assert rig["events"][:3] == ["acquire", "consume_approval", "submitting"]
    assert any(e.startswith("uncertain:") for e in rig["events"]) and "record" not in rig["events"]


def test_print_bambu_upload_failure_is_uncertain(monkeypatch, rig):
    wire_client(monkeypatch, rig, [snapshot_script(), snapshot_script()], ftp=FakeFTP(fail_store=True))
    with pytest.raises(SystemExit, match="submission failed or uncertain"):
        model_job._print_bambu(rig["adapter"], RECORD, rig["gcode"], rig["job"], rig["job_path"], 25, False)
    assert any(e.startswith("uncertain:") for e in rig["events"])


def test_print_bambu_refuses_a_multi_plate_package(monkeypatch, tmp_path, rig):
    package = tmp_path / "multi.gcode.3mf"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", "G1 X1\n")
        archive.writestr("Metadata/plate_2.gcode", "G1 X2\n")
    monkeypatch.setattr(delivery, "bambu_handoff", lambda job, gcodes, config=None: [package])
    wire_client(monkeypatch, rig, [snapshot_script()])
    with pytest.raises(SystemExit, match="REFUSED:.*single-plate package"):
        model_job._print_bambu(rig["adapter"], RECORD, rig["gcode"], rig["job"], rig["job_path"], 25, False)
    assert rig["events"] == []


def test_adapter_control_requires_configuration(monkeypatch):
    plain = printers.get("bambulab.a1", settings.load(
        local=False, environ={"PRINT_BUDDY__PRINTER__MODEL": "bambulab.a1"}))
    with pytest.raises(BambuLanError, match="not configured"):
        plain.control("pause")
