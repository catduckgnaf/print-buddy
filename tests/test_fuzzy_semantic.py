"""PRINT_FUZZY_URL endpoint contract tests (#468 stage 4).

semantic_matches() speaks the spike's small contract to an operator's
semantic-search endpoint — POST {query, candidates}, answer {matches,
degraded} — consulted only when a /print-lookup query matched nothing
locally. These tests pin the contract against a loopback stub (the same
stub an operator's Worker would implement), the opt-in gate, and the
degradation rules from docs/SETTINGS.md: every failure returns [] and the
local behaviour stands. Loopback only; nothing leaves this machine.
"""
import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from print_handy import knowledge
from print_handy.core import fuzzy_semantic

CANDIDATES = [
    {"id": "symptom:first-layer-not-sticking", "text": "First layer not sticking (bed adhesion)"},
    {"id": "flow:clog", "text": "Nozzle clog"},
]


class _Stub:
    """A loopback endpoint speaking the contract, recording what it was sent.

    status/payload/raw/sleep are read at request time, so a test can change
    the stub's answer between calls.
    """

    def __init__(self, status=200, payload=None, raw=None, sleep=0):
        self.status = status
        self.payload = payload
        self.raw = raw
        self.sleep = sleep
        self.requests = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                stub.requests.append({
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type"),
                    "authorization": self.headers.get("Authorization"),
                    "body": self.rfile.read(length),
                })
                if stub.sleep:
                    time.sleep(stub.sleep)
                body = stub.raw
                if body is None:
                    body = json.dumps(stub.payload if stub.payload is not None else {}).encode()
                self.send_response(stub.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        # The secret lives in the URL path, like PRINT_VISION_URL endpoints.
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/sekrit/fuzzy"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def stub_factory():
    stubs = []

    def make(**kwargs):
        stub = _Stub(**kwargs)
        stubs.append(stub)
        return stub

    yield make
    for stub in stubs:
        stub.stop()


@pytest.fixture(scope="module")
def registry():
    return knowledge.load_registry()


def _refused_url():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/fuzzy"


def test_unset_url_is_not_configured_and_never_networks(monkeypatch):
    monkeypatch.delenv("PRINT_FUZZY_URL", raising=False)
    assert fuzzy_semantic.configured() is False
    with monkeypatch.context() as m:
        m.setattr(fuzzy_semantic.urllib.request, "urlopen",
                  lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
        assert fuzzy_semantic.semantic_matches("bed wont stick", CANDIDATES) == []


def test_request_shape_and_matches(stub_factory, monkeypatch):
    stub = stub_factory(payload={"matches": [{"id": "symptom:first-layer-not-sticking",
                                              "text": "First layer not sticking (bed adhesion)",
                                              "score": 0.83}], "degraded": False})
    monkeypatch.setenv("PRINT_FUZZY_URL", stub.url)
    assert fuzzy_semantic.configured() is True
    out = fuzzy_semantic.semantic_matches("bed wont stick", CANDIDATES)
    assert out == [{"id": "symptom:first-layer-not-sticking",
                    "text": "First layer not sticking (bed adhesion)", "score": 0.83}]
    assert len(stub.requests) == 1
    request = stub.requests[0]
    assert request["path"] == "/sekrit/fuzzy"
    assert request["content_type"] == "application/json"
    assert request["authorization"] is None  # the secret is in the path; no key is sent
    assert json.loads(request["body"]) == {"query": "bed wont stick", "candidates": CANDIDATES,
                                            "threshold": 0.55, "limit": 5}


def test_degraded_answer_returns_empty(stub_factory, monkeypatch, caplog):
    stub = stub_factory(payload={"matches": [], "degraded": True, "reason": "binding missing"})
    monkeypatch.setenv("PRINT_FUZZY_URL", stub.url)
    with caplog.at_level(logging.WARNING, logger="print_handy.core.fuzzy_semantic"):
        assert fuzzy_semantic.semantic_matches("bed wont stick", CANDIDATES) == []
    assert "degraded" in caplog.text


def test_http_error_and_malformed_body_degrade_and_log(stub_factory, monkeypatch, caplog):
    stub = stub_factory(status=500, payload={"matches": [{"id": "flow:clog", "text": "x", "score": 0.9}]})
    monkeypatch.setenv("PRINT_FUZZY_URL", stub.url)
    with caplog.at_level(logging.WARNING, logger="print_handy.core.fuzzy_semantic"):
        assert fuzzy_semantic.semantic_matches("bed wont stick", CANDIDATES) == []
    stub.status, stub.raw = 200, b"not json"
    assert fuzzy_semantic.semantic_matches("bed wont stick", CANDIDATES) == []
    assert "PRINT_FUZZY_URL" in caplog.text


def test_unreachable_and_slow_endpoints_degrade(stub_factory, monkeypatch):
    monkeypatch.setenv("PRINT_FUZZY_URL", _refused_url())
    assert fuzzy_semantic.semantic_matches("bed wont stick", CANDIDATES) == []
    stub = stub_factory(sleep=2, payload={"matches": [], "degraded": False})
    monkeypatch.setenv("PRINT_FUZZY_URL", stub.url)
    monkeypatch.setattr(fuzzy_semantic, "TIMEOUT_S", 0.2)
    assert fuzzy_semantic.semantic_matches("bed wont stick", CANDIDATES) == []


# ------------------------------------------------------- lookup integration

def test_lookup_text_semantic_suggestions_only_on_a_local_miss(stub_factory, monkeypatch, registry):
    stub = stub_factory(payload={"matches": [{"id": "symptom:first-layer-not-sticking",
                                              "text": "First layer not sticking (bed adhesion)",
                                              "score": 0.83}], "degraded": False})
    monkeypatch.setenv("PRINT_FUZZY_URL", stub.url)
    text = knowledge.lookup_text("bed wont stick", registry=registry)
    assert "Closest by meaning" in text and "First layer will not stick" in text
    assert text.endswith(knowledge.ADVISORY_NOTE)
    assert len(stub.requests) == 1
    sent = json.loads(stub.requests[0]["body"])
    assert sent["query"] == "bed wont stick"
    # Candidates are the registries' public entries only — ids and display
    # names, nothing from this install.
    ids = {c["id"] for c in sent["candidates"]}
    assert "symptom:first-layer-not-sticking" in ids and "flow:clog" in ids
    assert all(set(c) == {"id", "text"} for c in sent["candidates"])


def test_lookup_text_local_hit_never_calls_the_endpoint(stub_factory, monkeypatch, registry):
    stub = stub_factory(payload={"matches": [], "degraded": False})
    monkeypatch.setenv("PRINT_FUZZY_URL", stub.url)
    text = knowledge.lookup_text("clog", registry=registry)
    assert "Nothing in the registries matches" not in text
    assert stub.requests == []


def test_lookup_text_endpoint_failure_keeps_the_plain_no_match_reply(stub_factory, monkeypatch, registry):
    stub = stub_factory(status=500, payload={})
    monkeypatch.setenv("PRINT_FUZZY_URL", stub.url)
    text = knowledge.lookup_text("bed wont stick", registry=registry)
    assert "Nothing in the registries matches 'bed wont stick'" in text


def test_lookup_text_ignores_match_ids_that_were_not_candidates(stub_factory, monkeypatch, registry):
    stub = stub_factory(payload={"matches": [{"id": "symptom:made-up", "text": "Nope", "score": 0.99}],
                                 "degraded": False})
    monkeypatch.setenv("PRINT_FUZZY_URL", stub.url)
    text = knowledge.lookup_text("bed wont stick", registry=registry)
    assert "Nothing in the registries matches 'bed wont stick'" in text
    assert "Nope" not in text


def test_lookup_text_without_the_url_set_is_unchanged(monkeypatch, registry):
    monkeypatch.delenv("PRINT_FUZZY_URL", raising=False)
    text = knowledge.lookup_text("bed wont stick", registry=registry)
    assert "Nothing in the registries matches 'bed wont stick'" in text
