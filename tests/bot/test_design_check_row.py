"""Bot check's design row after the #524 Stage 3 transport flip.

The row must name the lane the plugin's transport selection would
actually use: the [design]/[llm] HTTP endpoint whenever one resolves
(every mode, Hermes included), and the Hermes print_design auxiliary
task only when no endpoint resolves in Hermes mode — the fallback lane.
"""
import shutil

from print_handy.bot import __main__ as bot_main


def _rows(cfg, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x" * 20)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/openscad")
    return {label: (ok, detail) for label, ok, detail in bot_main.checks(cfg)}


def test_design_row_hermes_mode_reports_the_http_endpoint(cfg, monkeypatch):
    cfg["bot"]["mode"] = "hermes"
    cfg["design"].update(chat_url="http://design.invalid/v1", model="sol")
    ok, detail = _rows(cfg, monkeypatch)["design"]
    assert ok is True
    assert "sol at http://design.invalid/v1" in detail
    assert "auxiliary" not in detail


def test_design_row_hermes_mode_without_endpoint_names_the_auxiliary_task(cfg, monkeypatch):
    cfg["bot"]["mode"] = "hermes"
    ok, detail = _rows(cfg, monkeypatch)["design"]
    assert ok is True
    assert "Hermes print_design auxiliary task" in detail


def test_design_row_standalone_reports_the_http_endpoint(cfg, monkeypatch):
    cfg["design"].update(chat_url="http://design.invalid/v1", model="sol")
    ok, detail = _rows(cfg, monkeypatch)["design"]
    assert ok is True
    assert "sol at http://design.invalid/v1" in detail
