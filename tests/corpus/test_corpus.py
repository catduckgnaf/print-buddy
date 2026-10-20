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


def test_private_corpus_is_explicitly_opt_in(tmp_path, monkeypatch):
    private_root = tmp_path / "private-cases"
    case_dir = private_root / "personal-model"
    case_dir.mkdir(parents=True)
    (case_dir / "case.toml").write_text('description = "private"\n')
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PRINT_BUDDY_PRIVATE_CORPUS", raising=False)
    assert case_dir.resolve() not in harness.case_dirs()
    monkeypatch.setenv("PRINT_BUDDY_PRIVATE_CORPUS", str(private_root))
    assert case_dir.resolve() in harness.case_dirs()
    assert harness.is_private_case(case_dir)


def test_private_corpus_is_refused_in_ci(tmp_path, monkeypatch):
    private_root = tmp_path / "private-cases"
    private_root.mkdir()
    monkeypatch.setenv("PRINT_BUDDY_PRIVATE_CORPUS", str(private_root))
    monkeypatch.setenv("CI", "true")
    with pytest.raises(RuntimeError, match="local-only"):
        harness.case_dirs()


def test_private_corpus_must_be_outside_repository(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("PRINT_BUDDY_PRIVATE_CORPUS", str(settings.ROOT))
    with pytest.raises(ValueError, match="outside the repository"):
        harness.case_dirs()


def test_private_case_does_not_need_redistribution_license(tmp_path, monkeypatch):
    private_root = tmp_path / "private-cases"
    case_dir = private_root / "personal-model"
    case_dir.mkdir(parents=True)
    (case_dir / "model.3mf").write_bytes(b"local test model")
    (case_dir / "case.toml").write_text(
        'description = "private"\n'
        '[[click]]\nquestion = "Choose the color"\nbutton = "White"\n'
        '[expect]\nstatus = "STARTED"\n')
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("PRINT_BUDDY_PRIVATE_CORPUS", str(private_root))
    case = harness.load_case(case_dir)
    _assert_case_license(case)


def test_public_case_still_needs_redistribution_license(tmp_path, monkeypatch):
    public_case = tmp_path / "public-case"
    public_case.mkdir()
    (public_case / "model.3mf").write_bytes(b"public test model")
    (public_case / "case.toml").write_text('description = "public"\n')
    monkeypatch.delenv("PRINT_BUDDY_PRIVATE_CORPUS", raising=False)
    case = harness.load_case(public_case)
    with pytest.raises(AssertionError, match="allows redistribution"):
        _assert_case_license(case)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_case_folder_is_complete(case):
    assert case.model.is_file() and case.model.stat().st_size < 1 << 20
    assert case.clicks and case.expect, "case.toml needs [[click]] rules and an [expect] table"
    for rule in case.clicks:
        assert rule.get("question") and rule.get("button"), rule
    _assert_case_license(case)


def _assert_case_license(case):
    if harness.is_private_case(case.dir):
        return
    # Public fixtures must name a license that permits redistribution.
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
