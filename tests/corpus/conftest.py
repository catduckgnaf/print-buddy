"""Corpus tests never reach a live printer, a LAN service or the real hardware record.

Same guards as tests/pipeline/conftest.py, minus the pipeline's per test archive patches: the harness
sets up its own archive, claims and state under a temp dir (or .slicer-work for the real Orca tier).
"""
import pytest

from print_buddy.core import printer_state

from . import harness


@pytest.fixture(autouse=True)
def _never_write_live_printer_state(monkeypatch):
    monkeypatch.setattr(printer_state, "save", lambda state: None)


@pytest.fixture(autouse=True)
def _home_slicer_commands(monkeypatch):
    """A machine's YAML or TOML local config may point at another slicer; the corpus runs the home commands."""
    from print_buddy import settings
    from print_buddy.core import orca_adapter
    home = settings.load(local=False, environ={})
    monkeypatch.setattr(orca_adapter, "ORCA_COMMAND", list(home["orca"]["command"]))
    monkeypatch.setattr(orca_adapter, "BAMBU_COMMAND", list(home["bambu"]["command"]))


@pytest.fixture(scope="session", autouse=True)
def _clarify_gateway_stand_in():
    harness.install_clarify_stand_in()
    yield
