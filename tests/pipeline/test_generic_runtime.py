"""Runtime path for non-ZMod printer families: intake -> slice -> print-now -> Moonraker start, offline.

With [printer] family = generic_klipper nothing on the path may touch the ZMod/AD5X machinery:
no START_PRINT/SET_EXTRUDER_SLOT/CHANGE_ZCOLOR/LOAD_ZOFFSET/M8xx, no display_off, no stock /detail.
"""
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from print_buddy import printers, settings
from print_buddy.core import model_job, orca_adapter, printer_state
from print_buddy.printers.base import MultiColorUnsupported

ZMOD_STEPS = re.compile(r"SET_EXTRUDER_SLOT|\bSTART_PRINT\b|CHANGE_ZCOLOR|SET_ZCOLOR|LOAD_ZOFFSET|\bM8\d\d\b|"
                        r"zmod|display_off|save_variables|Adventurer5M|8898|/detail|\bIFS\b", re.I)

GCODE = """; nozzle_diameter = 0.4
; filament_type = PLA
; first_layer_height = 0.2
; estimated printing time (normal mode) = 1h 2m 0s
; total filament used [g] = 12.3
PRINT_START BED=60 HOTEND=215
G90
;LAYER_CHANGE
;TYPE:Outer wall
;WIDTH:0.42
G1 X10 Y10 Z0.2 E1
;LAYER_CHANGE
;WIDTH:0.42
G1 X20 Y20 Z0.4 E2
PRINT_END
"""

STATE = {"moonraker_url": "http://printer.test:7125", "printer": "Test Klipper",
         "nozzle": {"diameter_mm": 0.4, "type": "brass"}, "temps_c": {"nozzle": 215, "bed": 60},
         "spool": {"spoolman_id": 7, "name": "Black PLA", "material": "PLA"}}


def use_family(monkeypatch, family):
    data = settings.load(local=False, environ={})
    data["printer"]["family"] = family
    if family != "flashforge_zmod":
        data["printer"]["ifs_slots"] = 1
    adapter = printers.get(family, data)
    monkeypatch.setattr(printers, "current", lambda config=None: adapter)
    return adapter


class FakeMoonraker:
    """request_json stand-in that records every request and answers like an idle stock Klipper."""

    def __init__(self, print_state="standby"):
        self.requests = []
        self.print_state = print_state
        self.started = None

    def __call__(self, url, *, data=None, headers=None, timeout=25):
        path = url.split("7125", 1)[1]
        self.requests.append({"path": path, "body": data})
        if path == "/printer/print/start":
            self.started = data["filename"]
            return {"result": "ok"}
        if path.startswith("/printer/objects/query"):
            state = "printing" if self.started else self.print_state
            return {"result": {"status": {
                "print_stats": {"state": state, "filename": self.started or ""},
                "webhooks": {"state": "ready"}, "idle_timeout": {"state": "Printing" if self.started else "Idle"},
                "virtual_sdcard": {"is_active": bool(self.started), "file_path": ""},
                "extruder": {"temperature": 25.0, "target": 0.0}, "heater_bed": {"temperature": 24.0, "target": 0.0}}}}
        return {"result": {}}


def upload_run(cmd, *args, **kwargs):
    uploads.append(cmd)
    return mock.Mock(returncode=0, stdout=json.dumps({"result": {"item": {"root": "gcodes", "path": cmd[3]}}}), stderr="")


uploads = []


@pytest.fixture
def rig(monkeypatch, tmp_path):
    uploads.clear()
    fake = FakeMoonraker()
    monkeypatch.setattr(model_job, "request_json", fake)
    monkeypatch.setattr(printer_state, "load", lambda: dict(STATE))
    monkeypatch.setattr(printer_state, "check", lambda st=None: (True, [], {}))
    monkeypatch.setattr(model_job.subprocess, "run", upload_run)
    monkeypatch.setattr(model_job, "record_start", lambda *a, **k: str(tmp_path / "note.md"))
    monkeypatch.setattr(model_job.time, "sleep", lambda s: None)
    gcode = tmp_path / "plate_1.gcode"
    gcode.write_text(GCODE)
    return fake, gcode


def write_job(tmp_path, gcode, **extra):
    job = {"title": "Cube", "model_id": "m1", "gcode": str(gcode), **extra}
    path = tmp_path / "JOB.json"
    path.write_text(json.dumps(job))
    return path


def test_generic_print_now_runs_no_zmod_step(monkeypatch, rig, tmp_path):
    adapter = use_family(monkeypatch, "generic_klipper")
    fake, gcode = rig
    out = model_job.print_now(write_job(tmp_path, gcode, printer_family="generic_klipper"))
    assert out["started"] is True
    starts = [r for r in fake.requests if r["path"] == "/printer/print/start"]
    assert [r["body"]["filename"] for r in starts] == [fake.started]
    assert adapter.moonraker_start_commands(fake.started)[0]["body"] == starts[0]["body"]
    assert len(uploads) == 1
    for request in fake.requests:
        assert not ZMOD_STEPS.search(json.dumps(request)), request
    assert not ZMOD_STEPS.search(gcode.read_text())
    assert "Calibration:" not in out["details"]
    assert "Test Klipper" in out["details"]


def test_generic_readiness_comes_from_the_adapter(monkeypatch, rig, tmp_path):
    use_family(monkeypatch, "generic_klipper")
    fake, gcode = rig
    fake.print_state = "printing"
    with mock.patch.object(model_job, "_printer_phase", return_value=("standby", "", "Ready")):
        with pytest.raises(SystemExit, match=r"REFUSED: .*Generic Klipper readiness unavailable.*busy \(printing\).*Nothing uploaded"):
            model_job.print_now(gcode)
    assert not uploads
    assert not [r for r in fake.requests if r["path"] == "/printer/print/start"]


def test_generic_refuses_multicolor_gcode_cleanly(monkeypatch, rig, tmp_path):
    use_family(monkeypatch, "generic_klipper")
    fake, gcode = rig
    gcode.write_text(GCODE + "T1\nG1 X5\n")
    with pytest.raises(SystemExit, match=r"REFUSED: .*single extruder.*Nothing uploaded or started"):
        model_job.print_now(gcode)
    assert not uploads


def test_generic_verify_gcode_needs_its_own_start_macro(monkeypatch, rig):
    use_family(monkeypatch, "generic_klipper")
    fake, gcode = rig
    assert model_job.verify_gcode(gcode) is True
    gcode.write_text(GCODE.replace("PRINT_START BED=60", "PRINT_START BED=70"))
    with pytest.raises(RuntimeError, match="missing PRINT_START matching bed 60"):
        model_job.verify_gcode(gcode)
    assert not [r for r in fake.requests if ZMOD_STEPS.search(json.dumps(r))]


@pytest.mark.parametrize("configured,recorded", [("generic_klipper", "flashforge_zmod"),
                                                 ("generic_klipper", None),
                                                 ("flashforge_zmod", "generic_klipper"),
                                                 ("sovol_klipper", "generic_klipper")])
def test_family_mismatch_refuses_before_upload(monkeypatch, rig, tmp_path, configured, recorded):
    use_family(monkeypatch, configured)
    fake, gcode = rig
    extra = {"printer_family": recorded} if recorded else {}
    with pytest.raises(SystemExit, match=r"REFUSED: this job was prepared for .*configured printer family is "
                                         + configured + r".*nothing uploaded"):
        model_job.print_now(write_job(tmp_path, gcode, **extra))
    assert not uploads and not fake.requests


def test_job_without_the_field_is_a_flashforge_job(monkeypatch):
    assert printers.job_family({"title": "old"}) == "flashforge_zmod"
    assert printers.job_family(None) == "flashforge_zmod"
    use_family(monkeypatch, "flashforge_zmod")
    printers.check_job_family({"title": "old"})
    use_family(monkeypatch, "generic_klipper")
    with pytest.raises(printers.JobFamilyMismatch):
        printers.check_job_family({"title": "old"})


def test_printer_override_is_recorded_on_the_job(monkeypatch, tmp_path):
    use_family(monkeypatch, "flashforge_zmod")
    job = write_job(tmp_path, tmp_path / "x.gcode")
    argv = ["model_job.py", "slice", str(job), "--approved", "--printer", "sovol_klipper"]
    with mock.patch.object(sys, "argv", argv), \
         mock.patch.object(model_job.printer_state, "load", return_value=dict(STATE)), \
         mock.patch.object(model_job, "intake_color_choices", return_value=True), \
         mock.patch.object(model_job, "slice_job", return_value="x.gcode") as sliced:
        model_job.main()
    assert json.loads(job.read_text())["printer_family"] == "sovol_klipper"
    sliced.assert_called_once()
    with mock.patch.object(sys, "argv", argv[:-1] + ["prusa"]), pytest.raises(SystemExit) as bad:
        model_job.main()
    assert bad.value.code == 2


def stl(path):
    path.write_text("solid x\nendsolid x\n")
    return path


def slice_job_rig(monkeypatch, tmp_path, family):
    use_family(monkeypatch, family)
    src = stl(tmp_path / "cube.stl")
    job = write_job(tmp_path, tmp_path / "none.gcode", downloaded_file=str(src),
                    audit={"plates": 1, "size_x": "20", "size_y": "20", "size_z": "20"})
    state = dict(STATE, bed_mm=[220, 220], max_print_height_mm=250)
    out = tmp_path / "sliced" / "plate_1.gcode"
    out.parent.mkdir()
    out.write_text(GCODE)
    monkeypatch.setattr(printer_state, "load", lambda: dict(state))
    return job, out


def test_generic_slice_records_family_and_skips_zmod_finalize(monkeypatch, tmp_path):
    job, out = slice_job_rig(monkeypatch, tmp_path, "generic_klipper")
    forbid = mock.Mock(side_effect=AssertionError("ZMod finalization ran"))
    with mock.patch("print_buddy.core.multicolor_contract.finalize", forbid), \
         mock.patch.object(orca_adapter, "slice_model", return_value=(out, {}, [])) as sliced, \
         mock.patch.object(model_job, "verify_gcode") as verify:
        assert model_job.slice_job(job) == out
    recorded = json.loads(job.read_text())
    assert recorded["printer_family"] == "generic_klipper"
    assert "filament_slot" not in sliced.call_args.kwargs
    verify.assert_called_once_with(out)
    forbid.assert_not_called()


def test_generic_slice_refuses_multicolor_source(monkeypatch, tmp_path):
    job, out = slice_job_rig(monkeypatch, tmp_path, "generic_klipper")
    manifest = {"requires_choices": True, "source_sha256": "abc"}
    with mock.patch("print_buddy.core.source_colors.inventory", return_value=manifest), \
         mock.patch.object(orca_adapter, "slice_model") as sliced:
        with pytest.raises(MultiColorUnsupported, match="single extruder"):
            model_job.slice_job(job)
        sliced.assert_not_called()
    with mock.patch("print_buddy.core.source_colors.inventory", return_value=manifest):
        with pytest.raises(MultiColorUnsupported, match="single extruder"):
            model_job.intake_color_choices(job, dict(STATE))
    argv = ["model_job.py", "slice", str(job), "--approved"]
    with mock.patch.object(sys, "argv", argv), \
         mock.patch.object(model_job, "intake_color_choices", side_effect=MultiColorUnsupported("one extruder only")):
        with pytest.raises(SystemExit, match="REFUSED: one extruder only"):
            model_job.main()


def test_orca_adapter_skips_zmod_md5_for_generic(monkeypatch):
    adapter = use_family(monkeypatch, "generic_klipper")
    assert adapter.has_native_screen is False
    assert printers.get("flashforge_zmod").has_native_screen is True


def test_listener_skips_screen_machinery_for_generic(monkeypatch):
    from print_buddy.hermes import moonraker_event_listener as listener
    use_family(monkeypatch, "generic_klipper")
    boom = mock.AsyncMock(side_effect=AssertionError("stock detail read"))
    obj = listener.Listener()
    with mock.patch.object(listener.Listener, "read_slots", boom):
        asyncio.run(obj.poll_native_presence())
        assert asyncio.run(obj.classify_runout()) == (False, None)
    assert obj.start_screen_cancel_reboot("test") is False
    boom.assert_not_called()


def test_printer_state_check_skips_calibration_authority_for_generic(monkeypatch):
    use_family(monkeypatch, "generic_klipper")
    urls = []

    def get(url, data=None, method=None, timeout=6):
        urls.append(url)
        if "configfile" in url:
            return {"result": {"status": {"configfile": {"settings": {"extruder": {"nozzle_diameter": "0.4"}}}}}}
        if "spool_id" in url:
            return {"result": {"spool_id": 7}}
        return {"id": 7, "filament": {"name": "Black PLA", "material": "PLA"}}

    with mock.patch.object(printer_state, "_get", get):
        ok, problems, _ = printer_state.check(dict(STATE, spoolman_url="http://spoolman.test", spool=dict(STATE["spool"])))
    assert ok, problems
    assert not [u for u in urls if "save_variables" in u or "Adventurer5M" in u]
