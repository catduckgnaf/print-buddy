"""slice_job's delivery-format record (#564 stage 1): with [delivery] format gcode_3mf,
a sliced ZMod job records its validated .gcode.3mf package; with the default the job
record is untouched. The inner G-code fixture passes the real verify_gcode_offline
against the neutral AD5X hardware record, so the package faces the same checks here
as a plain .gcode does in the slice paths.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from print_handy import printers, settings
from print_handy.core import delivery
from print_handy.core import model_job
from .test_delivery_zmod_3mf import finalized, orca_export

STATE = Path(__file__).parent / "fixtures" / "printer_hardware.json"
INNER = (
    "; nozzle_diameter = 0.4\n"
    "; filament_type = PLA\n"
    "M190 S60\nM104 S210 T0\n"
    "START_PRINT BED_TEMP=60 EXTRUDER_TEMP=210 MESH=auto\n"
    "G1 X10 Y10 Z0.2 E1.0\n"
    "END_PRINT\n"
)


def _adapter(fmt):
    config = copy.deepcopy(settings.load(local=False, environ={}))
    config["delivery"]["format"] = fmt
    return printers.get("flashforge.ad5x", config)


def _job(tmp_path, monkeypatch, fmt="gcode_3mf", *, derived=False, package=True, inner=INNER):
    """A sliced job folder: JOB.json + plate_1.gcode (+ its package), adapters stubbed."""
    monkeypatch.setattr(model_job, "_job_adapter", lambda job: _adapter(fmt))
    state = json.loads(STATE.read_text())
    monkeypatch.setattr(model_job.printer_state, "load", lambda *a, **k: copy.deepcopy(state))
    folder = tmp_path / "job"
    folder.mkdir()
    gcode = folder / "plate_1.gcode"
    gcode.write_text(inner)
    if package:
        pkg = delivery.zmod_package_target(gcode)
        orca_export(pkg, inner.encode())
        delivery.repack_zmod_package(pkg, gcode, printer_model_id="AD5X")
    job = {"printer_model": "flashforge.ad5x", "gcode": str(gcode), "gcode_verified": True}
    if derived:
        other = folder / "plate_2.gcode"
        other.write_text(inner)
        if package:
            pkg2 = delivery.zmod_package_target(other)
            orca_export(pkg2, inner.encode())
            delivery.repack_zmod_package(pkg2, other, printer_model_id="AD5X")
        job["derived_plates"] = [{"gcode": str(other), "plate_id": 2}]
    job_path = folder / "JOB.json"
    job_path.write_text(json.dumps(job))
    return job_path


def test_record_notes_the_package_and_its_sha(tmp_path, monkeypatch):
    job_path = _job(tmp_path, monkeypatch)
    model_job._record_delivery_format(job_path)
    job = json.loads(job_path.read_text())
    package = Path(job["delivery_file"])
    assert job["delivery_format"] == "gcode_3mf"
    assert package.name == "plate_1.gcode.3mf"
    assert package.is_file()
    assert job["delivery_file_sha256"] == delivery.sha256(package)


def test_record_covers_derived_plates(tmp_path, monkeypatch):
    job_path = _job(tmp_path, monkeypatch, derived=True)
    model_job._record_delivery_format(job_path)
    job = json.loads(job_path.read_text())
    row = job["derived_plates"][0]
    assert row["delivery_file"].endswith("plate_2.gcode.3mf")
    assert row["delivery_file_sha256"] == delivery.sha256(Path(row["delivery_file"]))


def test_default_format_leaves_the_job_record_untouched(tmp_path, monkeypatch):
    job_path = _job(tmp_path, monkeypatch, fmt="gcode")
    before = job_path.read_bytes()
    model_job._record_delivery_format(job_path)
    assert job_path.read_bytes() == before


def test_missing_package_refuses_the_slice(tmp_path, monkeypatch):
    job_path = _job(tmp_path, monkeypatch, package=False)
    with pytest.raises(RuntimeError, match="no sliced package was produced"):
        model_job._record_delivery_format(job_path)
    assert "delivery_format" not in json.loads(job_path.read_text())


def test_corrupt_package_refuses_the_slice(tmp_path, monkeypatch):
    job_path = _job(tmp_path, monkeypatch)
    package = Path(json.loads(job_path.read_text())["gcode"] + ".3mf")
    import zipfile
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("Metadata/plate_1.gcode.md5", b"0" * 32)
    with pytest.raises(RuntimeError, match="failed validation"):
        model_job._record_delivery_format(job_path)


def test_inner_gcode_failing_offline_verification_refuses_the_slice(tmp_path, monkeypatch):
    """The archive's inner file faces verify_gcode_offline itself: a START_PRINT whose
    temperatures disagree with the recorded ones is refused inside the package too."""
    bad = INNER.replace("EXTRUDER_TEMP=210", "EXTRUDER_TEMP=199")
    job_path = _job(tmp_path, monkeypatch, inner=bad)
    with pytest.raises(RuntimeError, match="offline G-code verification failed"):
        model_job._record_delivery_format(job_path)


def test_slice_job_wrapper_records_after_slicing(tmp_path, monkeypatch):
    job_path = _job(tmp_path, monkeypatch)
    monkeypatch.setattr(model_job, "_slice_job_impl", lambda path, **kw: Path(json.loads(Path(path).read_text())["gcode"]))
    out = model_job.slice_job(job_path)
    assert out.is_file()
    job = json.loads(job_path.read_text())
    assert job["delivery_format"] == "gcode_3mf"
    assert job["delivery_file"].endswith("plate_1.gcode.3mf")


def test_finalized_inner_bytes_are_what_gets_verified(tmp_path, monkeypatch):
    """A package repacked around the finalized file (MD5 header + colour data) verifies
    exactly like the .gcode path's finalized artifact."""
    job_path = _job(tmp_path, monkeypatch, inner=finalized(
        "; nozzle_diameter = 0.4\n; filament_type = PLA;PLA\n"
        "M190 S60\nM104 S210 T0\nSTART_PRINT BED_TEMP=60 EXTRUDER_TEMP=210 MESH=auto\n"
        "G1 X10 Y10 Z0.2 E1.0\nT1\nG1 X20 Y20 E2.0\nEND_PRINT\n"))
    model_job._record_delivery_format(job_path)
    job = json.loads(job_path.read_text())
    inner = delivery.extract_zmod_plate_gcode(Path(job["delivery_file"]))
    assert inner.startswith(b"; MD5:")
    assert hashlib.md5(inner.partition(b"\n")[2]).hexdigest().encode() in inner.split(b"\n", 1)[0]
