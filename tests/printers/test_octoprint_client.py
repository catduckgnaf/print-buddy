"""OctoPrint client timelapse surface (#373): listing + raw download.

The fake opener records requests and serves canned payloads; no network.
"""
import json

import pytest

from print_buddy.printers.octoprint.client import OctoPrintClient, OctoPrintError


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _client(payloads, seen):
    def opener(req, timeout=None):
        seen.append(req)
        return _Response(payloads.pop(0))
    return OctoPrintClient("http://octo.test:5000", "SECRETKEY", opener=opener)


def test_timelapse_movies_parses_the_listing():
    seen = []
    client = _client([json.dumps({"movies": [{"name": "a.mp4", "url": "/dl/a.mp4"}],
                                   "unrendered": []}).encode()], seen)
    assert client.timelapse_movies() == [{"name": "a.mp4", "url": "/dl/a.mp4"}]
    assert seen[0].full_url == "http://octo.test:5000/api/timelapse"
    assert seen[0].get_header("X-api-key") == "SECRETKEY"


def test_timelapse_movies_tolerates_a_missing_key():
    client = _client([b"{}"], [])
    assert client.timelapse_movies() == []


def test_download_returns_raw_bytes_with_auth():
    seen = []
    client = _client([b"\x00\x01video"], seen)
    assert client.download("/downloads/timelapse/a.mp4") == b"\x00\x01video"
    assert seen[0].full_url == "http://octo.test:5000/downloads/timelapse/a.mp4"
    assert seen[0].get_header("X-api-key") == "SECRETKEY"


@pytest.mark.parametrize("path", ["http://evil.test/x", "//evil.test/x", "relative.mp4", ""])
def test_download_refuses_non_relative_paths(path):
    client = _client([], [])
    with pytest.raises(OctoPrintError):
        client.download(path)


def test_download_failure_never_leaks_the_key():
    def opener(req, timeout=None):
        raise OSError("connection refused for SECRETKEY")
    client = OctoPrintClient("http://octo.test:5000", "SECRETKEY", opener=opener)
    with pytest.raises(OctoPrintError) as excinfo:
        client.download("/downloads/timelapse/a.mp4")
    assert "SECRETKEY" not in str(excinfo.value)
