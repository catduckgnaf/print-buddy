"""Every folder under tests/corpus/cases is a Discord flow regression test.

Mock tier (always): fake Discord, fake Orca CLI, modelled fit probe. Runs in the offline job on every PR.
Real tier (PRINT_BUDDY_REAL_SLICER=1): same cases, the real Orca CLI slices and probes.

To add a failing 3MF, see "Adding a failing 3MF" in the README.
"""
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from print_buddy import settings

from . import harness

REAL = os.environ.get("PRINT_BUDDY_REAL_SLICER") == "1"
CASES = [harness.load_case(folder) for folder in harness.case_dirs()]
IDS = [case.name for case in CASES]


def test_the_starting_cases_exist():
    assert {"parts-one-plate", "plates-multicolor", "needs-supports", "must-shrink", "split-plan", "single-part"} <= set(IDS)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_case_folder_is_complete(case):
    assert case.model.is_file() and case.model.stat().st_size < 1 << 20
    assert case.clicks and case.expect, "case.toml needs [[click]] rules and an [expect] table"
    for rule in case.clicks:
        assert rule.get("question") and rule.get("button"), rule
    # The repo is public: every model must say where it came from and that it may be redistributed.
    text = case.data.get("license", "")
    attribution = case.dir / "ATTRIBUTION"
    if attribution.is_file():
        text += attribution.read_text()
    assert re.search(r"CC0|public domain|CC[- ]BY|MIT|Apache", text, re.I), (
        "put license = \"...\" in case.toml (or an ATTRIBUTION file) naming a license that allows redistribution")


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_discord_flow(case, tmp_path):
    run = harness.run_case(case, tmp_path, real_slicer=REAL)
    try:
        harness.check_expectations(case, run)
    finally:
        if REAL:
            shutil.rmtree(run.archive, ignore_errors=True)


def test_checked_in_models_match_the_generator(tmp_path, monkeypatch):
    """make_models.py is the source of truth; a hand edited model.3mf would drift from it."""
    from . import make_models
    monkeypatch.setattr(make_models, "HERE", tmp_path)
    make_models.build()
    for fresh in sorted((tmp_path / "cases").glob("*/model.3mf")):
        committed = harness.CASES / fresh.parent.name / "model.3mf"
        assert committed.read_bytes() == fresh.read_bytes(), (
            f"{committed} differs from make_models.py output; rerun python3 tests/corpus/make_models.py")


def test_case_accepts_any_model_extension(tmp_path):
    """A folder with one .stl and no model.3mf is a case, not an error."""
    folder = tmp_path / "renamed"
    folder.mkdir()
    (folder / "bracket.stl").write_bytes(b"solid")
    (folder / "case.toml").write_text('description = "renamed"\n[expect]\nstatus = "STARTED"\n')
    assert harness.find_model(folder).name == "bracket.stl"
    loaded = harness.load_case(folder)
    assert loaded.model.name == "bracket.stl"


def test_case_prefers_model_3mf(tmp_path):
    """model.3mf stays the file under test when a folder also holds a source export."""
    folder = tmp_path / "both"
    folder.mkdir()
    (folder / "model.3mf").write_bytes(b"zip")
    (folder / "export.stl").write_bytes(b"solid")
    assert harness.find_model(folder).name == "model.3mf"


def test_case_rejects_a_folder_without_a_model(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    (folder / "notes.txt").write_text("not a model")
    with pytest.raises(FileNotFoundError):
        harness.find_model(folder)


def test_a_missing_click_rule_fails_with_the_question(tmp_path):
    case = harness.load_case(harness.CASES / "single-part")
    case.clicks[:] = [rule for rule in case.clicks if rule["button"] != "White"]
    run = harness.run_case(case, tmp_path)
    # The plugin turns the exception into a failed receipt, which is what a user would see.
    assert run.receipt["status"] == "FAILED"
    assert "no [[click]] rule" in run.receipt["error"] and "Choose the color" in run.receipt["error"]
    with pytest.raises(AssertionError, match="Choose the color"):
        harness.check_expectations(case, run)


# ----------------------------------------------------------------------------- runtime environment (#57)

@pytest.mark.parametrize("name", ["single-part", "plates-multicolor"])
def test_gateway_environment_keeps_state_in_the_profile(name, tmp_path):
    """The multiplexed gateway runs every profile with HERMES_HOME=~/.hermes. Print Buddy must still keep its
    state in its own profile (~/.hermes/profiles/3dprinting/state), and the intake must find the printer
    hardware record there. #57 moved state to ~/.hermes/state and the intake died on a missing record."""
    case = harness.load_case(harness.CASES / name)
    home = tmp_path / "home"
    gateway_home = home / ".hermes"
    profile_state = gateway_home / "profiles" / "3dprinting" / "state"
    profile_state.mkdir(parents=True)
    shutil.copy(harness.FIXTURE_STATE, profile_state / "printer_hardware.json")
    # Always the mock tier: this test is about where settings and state resolve. A moved HOME would also hide
    # the user's Flatpak install from a real Orca run, and the real tier already covers slicing.
    report = harness.run_in_gateway_env(case, tmp_path / "work", gateway_home, home)
    assert report["hermes_home_env"] == str(gateway_home)
    assert report["settings_home"] == str(gateway_home / "profiles" / "3dprinting")
    assert report["printer_state"] == str(profile_state / "printer_hardware.json")
    assert report["status"] == "STARTED", report
    assert report["receipts"] and all(Path(p).is_relative_to(profile_state) for p in report["receipts"])
    leaked = [p for p in gateway_home.rglob("*") if p.is_file() and not p.is_relative_to(gateway_home / "profiles")]
    assert not leaked, f"state written outside the profile: {leaked}"
    assert not (gateway_home / "state").exists()
