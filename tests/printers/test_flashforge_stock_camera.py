"""Stock Flashforge camera source (#373), offline.

The transport is a fake; nothing opens a socket. The protocol facts under
test are the ones printers/flashforge_stock/camera.py documents from the
public Flashforge API docs: /detail advertises cameraStreamUrl (empty =
no camera), and streamCtrl_cmd rides /control in a payload wrapper.
"""
import pytest

from print_handy.printers.flashforge_stock import camera
from print_handy.printers.flashforge_stock.client import StockClient, StockLanError

HOST = "192.0.2.10"
STREAM = "http://192.0.2.10:8080/?action=stream"


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("AD5X_SERIAL", "SN-TEST")
    monkeypatch.setenv("AD5X_CHECK_CODE", "code-test")


def scripted(replies):
    seen = []

    def post(url, body, content_type):
        seen.append((url, body, content_type))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return post, seen


# -- /control transport -------------------------------------------------------


def test_control_posts_the_payload_wrapper(creds):
    post, seen = scripted([{"code": 0}])
    StockClient(HOST, post=post).control("streamCtrl_cmd", {"action": "open"})
    url, body, _content_type = seen[0]
    assert url == f"http://{HOST}:8898/control"
    assert body == {"serialNumber": "SN-TEST", "checkCode": "code-test",
                    "payload": {"cmd": "streamCtrl_cmd", "args": {"action": "open"}}}


def test_control_refusal_raises_without_leaking_the_code(creds):
    post, _seen = scripted([{"code": 2, "message": "busy"}])
    with pytest.raises(StockLanError) as excinfo:
        StockClient(HOST, post=post).control("streamCtrl_cmd", {"action": "open"})
    assert "code-test" not in str(excinfo.value)


# -- the advertised stream URL ---------------------------------------------------


def test_advertised_url_is_the_printers_own_stream():
    assert camera.advertised_stream_url({"cameraStreamUrl": STREAM}, HOST) == STREAM


def test_advertised_url_empty_means_no_camera():
    assert camera.advertised_stream_url({"cameraStreamUrl": ""}, HOST) == ""
    assert camera.advertised_stream_url({}, HOST) == ""
    assert camera.advertised_stream_url(None, HOST) == ""


def test_advertised_url_must_point_at_the_configured_printer():
    assert camera.advertised_stream_url(
        {"cameraStreamUrl": "http://192.0.2.99:8080/?action=stream"}, HOST) == ""


def test_advertised_url_rejects_credentials_and_https():
    assert camera.advertised_stream_url(
        {"cameraStreamUrl": "http://user:pw@192.0.2.10:8080/?action=stream"}, HOST) == ""
    assert camera.advertised_stream_url(
        {"cameraStreamUrl": "https://192.0.2.10:8080/?action=stream"}, HOST) == ""


def test_stream_url_for_reads_detail_once():
    class FakeClient:
        def __init__(self):
            self.reads = 0

        def detail(self):
            self.reads += 1
            return {"cameraStreamUrl": STREAM}

    client = FakeClient()
    assert camera.stream_url_for(client, HOST) == STREAM
    assert client.reads == 1


# -- stream control ----------------------------------------------------------------


def test_set_stream_sends_open_and_close():
    calls = []

    class FakeClient:
        def control(self, cmd, args):
            calls.append((cmd, args))

    camera.set_stream(FakeClient(), "open")
    camera.set_stream(FakeClient(), "close")
    assert calls == [("streamCtrl_cmd", {"action": "open"}),
                     ("streamCtrl_cmd", {"action": "close"})]


def test_set_stream_refuses_an_unknown_action_before_any_request():
    class FakeClient:
        def control(self, cmd, args):
            raise AssertionError("must not be called")

    with pytest.raises(StockLanError):
        camera.set_stream(FakeClient(), "blink")
