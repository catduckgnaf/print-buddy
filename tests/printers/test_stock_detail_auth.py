import re
from pathlib import Path

import pytest

from print_handy.printers.flashforge.zmod import stock

ROOT = Path(__file__).resolve().parents[2]


def test_stock_detail_always_posts_auth_fields(monkeypatch):
    monkeypatch.setattr(stock, "_stock_credentials", lambda: ("serial", "code"))
    seen = {}

    def post(url, body):
        seen.update(url=url, body=body)
        return {"code": 0, "detail": {"status": "ready"}}

    assert stock.read_stock_detail({"moonraker_url": "http://printer:7125"}, post=post) == {"status": "ready"}
    assert seen["body"] == {"serialNumber": "serial", "checkCode": "code"}
    assert seen["url"].endswith("/detail")


def test_stock_detail_missing_credentials_never_posts(monkeypatch):
    def missing():
        raise RuntimeError("stock IFS credentials missing (AD5X_CHECK_CODE)")

    monkeypatch.setattr(stock, "_stock_credentials", missing)
    with pytest.raises(RuntimeError, match="credentials missing"):
        stock.read_stock_detail({"moonraker_url": "http://printer:7125"},
                                post=lambda *_: pytest.fail("POST attempted without credentials"))


@pytest.mark.parametrize("reply", [{"code": 400, "message": "bad request"}, None, {"code": 0}])
def test_stock_detail_refusal_raises_instead_of_reporting_state(monkeypatch, reply):
    monkeypatch.setattr(stock, "_stock_credentials", lambda: ("serial", "code"))
    with pytest.raises(RuntimeError):
        stock.read_stock_detail({"moonraker_url": "http://printer:7125"}, post=lambda *_: reply)


# The 3dprinting agent once ran a raw `curl -X POST http://<printer>:8898/detail`,
# got HTTP 400, and blocked a valid start. Shipped agent instructions must never
# show a direct stock API request and must route occupancy through filament-status.
RAW_REQUEST = re.compile(r"\b(curl|wget|requests\.(get|post)|urlopen)\b[^\n]*https?://[^\s`'\"]*(:8898|/detail)", re.I)


def test_agent_docs_never_show_raw_stock_api_requests():
    offenders = []
    for path in (ROOT / "hermes").rglob("*.md"):
        for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if RAW_REQUEST.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{n}")
    assert offenders == []


def test_agent_profile_forbids_direct_stock_requests_and_names_supported_command():
    text = (ROOT / "hermes/profile/AGENTS.md").read_text()
    assert "Never send it any request yourself" in text
    assert "`POST /detail`" in text and "never a printer fault or start blocker" in text
    assert "model_job filament-status" in text and "stock_detail_authoritative: true" in text
