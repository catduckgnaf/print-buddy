"""A print-now failure is reported by whether the start was ever sent (launch_state submitting()).

Since #688 any failure without a REFUSED line read as "Start sent, do not send it again", including
slot, mesh, occupancy and upload failures that never asked the printer to start (2026-10-31 audit).
"""
from unittest import mock

import pytest

from print_handy.core import launch_state, model_job, prepared_intake


def run_cli(behaviour):
    with mock.patch.object(model_job, "print_now", side_effect=behaviour):
        with pytest.raises(SystemExit) as exc:
            model_job._print_now_cli("job.gcode")
    return str(exc.value)


def test_a_failure_before_submission_is_a_clean_refusal():
    line = run_cli(RuntimeError("T0 slot 2 occupancy is unknown or unconfirmed"))
    assert line == "REFUSED: T0 slot 2 occupancy is unknown or unconfirmed. Nothing started."
    assert prepared_intake._safe_preupload_refusal(line)
    assert prepared_intake.plain_start_failure(line).startswith("Didn\x27t start")


def test_a_failure_after_submission_stays_uncertain(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT_HANDY_LAUNCH_DB", str(tmp_path / "launch.db"))

    def submitted_then_failed(*a, **k):
        lease = launch_state.acquire("p1", job_json="j", gcode_sha256="s", remote="r.gcode")
        lease.submitting()
        raise RuntimeError("readback failed: 503")
    line = run_cli(submitted_then_failed)
    assert line.startswith("UNCERTAIN: the start was sent and then failed: readback failed: 503")
    assert not prepared_intake._safe_preupload_refusal(line)


def test_refusals_and_successes_pass_through_unchanged():
    assert run_cli(SystemExit("REFUSED: idle guard failed: busy. Nothing uploaded or started.")).startswith(
        "REFUSED: idle guard failed")
    with mock.patch.object(model_job, "print_now", return_value={"started": True}):
        assert model_job._print_now_cli("job.gcode") == {"started": True}


def test_each_run_starts_unsubmitted():
    launch_state._SUBMITTED = True  # left over from an earlier in-process run
    assert run_cli(RuntimeError("boom")).startswith("REFUSED: boom")
