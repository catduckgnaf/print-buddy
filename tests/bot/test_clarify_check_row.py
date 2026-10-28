"""bot check's clarify ui row (#524 stage 2): the renderer an install is
using, reported in both states of the [discord] clarify_ui switch."""
from print_handy.bot import __main__ as bot_main


def test_bot_check_clarify_row_reports_each_state(cfg, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x" * 20)
    rows = {label: detail for label, ok, detail in bot_main.checks(cfg)}
    assert rows["clarify ui"].startswith("host renderer")
    cfg["discord"]["clarify_ui"] = True
    rows = {label: detail for label, ok, detail in bot_main.checks(cfg)}
    assert rows["clarify ui"].startswith("own renderer")
