"""Offline contract tests for the #458 complex corpus manifest.

These pin the catalogue, not the models: the model files are fetched (see
fetch_complex_corpus.py) and never committed, so what CI can check is that
the manifest is complete, licence-gated, measured, and domain-covering.
Flow runs against the fetched files are run_complex_corpus.py's job and are
reported there, not faked here.
"""
import hashlib
import http.client
import json
import os
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from . import fetch_complex_corpus

MANIFEST = Path(__file__).resolve().parent / "complex_cases.toml"
CASES = tomllib.loads(MANIFEST.read_text())["case"]
PUBLIC = [c for c in CASES if c["tier"] == "public"]
PRIVATE = [c for c in CASES if c["tier"] == "private"]
READY = [c for c in CASES if c["status"] == "ready"]

# Licence names recorded at download time that permit redistribution in the
# public corpus: Printables GraphQL licence names and the NASA wording.
PUBLIC_LICENSES = {
    "Creative Commons — Public Domain",
    "Creative Commons — Attribution",
    "Creative Commons — Attribution — Share Alike",
    "Creative Commons — Attribution  — Share Alike",
}
DOMAINS = {"moonraker", "bambulab_lan", "prusalink", "elegoo_sdcp",
           "octoprint", "flashforge_stock", "offline"}


def test_manifest_covers_all_twelve_catalogue_cases_and_three_private():
    assert len(PUBLIC) == 12, [c["slug"] for c in PUBLIC]
    assert len(PRIVATE) == 3, [c["slug"] for c in PRIVATE]
    assert len({c["slug"] for c in CASES}) == 15


def test_every_domain_has_a_case():
    covered = {c["target_domain"] for c in PUBLIC}
    assert DOMAINS <= covered, f"domains without a public case: {DOMAINS - covered}"


def test_public_cases_are_redistributable_and_private_cases_are_flagged():
    for case in PUBLIC:
        if case["site"] == "nasa":
            assert case["license"].startswith("Public domain"), case["slug"]
        elif case["site"] == "smithsonian":
            assert case["license"].startswith("Public domain"), case["slug"]
        else:
            assert case["license"] in PUBLIC_LICENSES, (case["slug"], case["license"])
    for case in PRIVATE:
        assert case["license"] not in PUBLIC_LICENSES, case["slug"]
        assert "PRIVATE" in case.get("notes", "") or case["status"] != "ready", case["slug"]


def test_ready_cases_carry_measured_stats():
    for case in READY:
        assert re.fullmatch(r"[0-9a-f]{64}", case["sha256"]), case["slug"]
        assert case["bytes"] > 0 and case["triangles"] > 0, case["slug"]
        assert len(case["dims_mm"]) == 3 and all(d > 0 for d in case["dims_mm"]), case["slug"]
        assert case["file"].endswith((".stl", ".3mf")), case["slug"]
        for extra in case.get("extra_file", []):
            assert re.fullmatch(r"[0-9a-f]{64}", extra["sha256"]), (case["slug"], extra["name"])
            assert extra["triangles"] > 0 and len(extra["dims_mm"]) == 3


def test_blocked_cases_say_why_and_claim_no_file():
    for case in CASES:
        if case["status"] != "ready":
            assert case.get("blocked_reason"), case["slug"]
            assert "sha256" not in case and "file" not in case, case["slug"]


def test_complex_cases_are_actually_complex():
    """The set, as a whole, must clear the bars #458 set - not 15 variations
    of one small model."""
    triangles = [c["triangles"] for c in READY]
    assert max(triangles) >= 1_000_000, triangles
    assert sum(t >= 100_000 for t in triangles) >= 6, triangles
    assert any(c["bytes"] >= 30_000_000 for c in READY)
    assert any(max(c["dims_mm"]) >= 290 for c in READY), "no near-300mm case"
    assert any("painted" in c.get("colors", "") or "paint" in c.get("colors", "")
               for c in READY), "no painted-colour case"


def test_targets_exist_in_the_printer_registry():
    registry = (Path(__file__).resolve().parents[2] / "printers" / "registry.toml").read_text()
    keys = set(re.findall(r'^key = "([^"]+)"', registry, re.M))
    for case in CASES:
        assert case["target_printer"] in keys, (case["slug"], case["target_printer"])


class _FakeResponse:
    """A stand-in for the _open_direct response: read() either returns the
    canned body or raises the canned error (e.g. a truncated read)."""

    def __init__(self, body=None, error=None):
        self._body = body
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        if self._error is not None:
            raise self._error
        return self._body


_GOOD_LINK_BODY = json.dumps({"data": {"getDownloadLink": {
    "ok": True, "output": {"link": "https://example.test/model.stl"},
    "errors": None}}}).encode()


def _stub_open_direct(monkeypatch, responses):
    calls = []

    def fake_open(url, data=None, headers=None):
        calls.append(url)
        return responses[len(calls) - 1]

    monkeypatch.setattr(fetch_complex_corpus, "_open_direct", fake_open)
    monkeypatch.setattr(fetch_complex_corpus, "time",
                        SimpleNamespace(sleep=lambda *_args: None))
    return calls


def test_printables_link_retries_a_truncated_read(monkeypatch):
    """A response truncated mid-read (http.client.IncompleteRead, seen once
    in the real fetch smoke run) is retried, not a crash."""
    calls = _stub_open_direct(monkeypatch, [
        _FakeResponse(error=http.client.IncompleteRead(b"partial", 123)),
        _FakeResponse(body=_GOOD_LINK_BODY),
    ])
    assert fetch_complex_corpus.printables_link("11", "22") == \
        "https://example.test/model.stl"
    assert len(calls) == 2


def test_printables_link_gives_up_after_bounded_retries(monkeypatch):
    calls = _stub_open_direct(monkeypatch, [
        _FakeResponse(error=http.client.IncompleteRead(b"partial"))
        for _ in range(3)
    ])
    with pytest.raises(http.client.IncompleteRead):
        fetch_complex_corpus.printables_link("11", "22")
    assert len(calls) == 3


@pytest.mark.skipif(not os.environ.get("COMPLEX_CORPUS_ROOT"),
                    reason="complex corpus not fetched here - run fetch_complex_corpus.py; "
                           "the manifest contract above is what CI pins")
def test_fetched_files_match_the_manifest():
    root = Path(os.environ["COMPLEX_CORPUS_ROOT"])
    for case in CASES:
        if case["tier"] != "public" or case["status"] != "ready":
            continue
        path = root / case["slug"] / case["file"]
        assert path.is_file(), f"{case['slug']}: run fetch_complex_corpus.py"
        assert path.stat().st_size == case["bytes"], case["slug"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == case["sha256"], case["slug"]
