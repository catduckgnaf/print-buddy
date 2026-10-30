"""Bambu Lab camera snapshots (#294 stage 1): offline tests only — a fake TCP transport, never a socket.

The fake implements the transport contract camera.py defines (sendall / recv_exact / close)
and serves scripted port-6000 framing: a 16-byte little-endian header whose first word is the
frame size, then the frame bytes. The authentication packet layout is the protocol behaviour
of the maintained clients cited in docs/BAMBU-CONNECTIVITY.md; nothing here is a real printer.
"""
import struct

import pytest

from print_handy import printers
from print_handy.printers.bambulab import camera
from print_handy.printers.bambulab.client import BambuLanError

CODE = "12345678"
HOST = "192.168.1.50"
JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body" + b"\xff\xd9"


def frame(payload):
    return struct.pack("<IIII", len(payload), 0, 0, 0) + payload


class FakeTransport:
    """recv_exact raises ConnectionError at end of stream, like the real socket transport."""

    def __init__(self, incoming=b""):
        self._incoming = bytearray(incoming)
        self.sent = b""
        self.closed = False

    def sendall(self, data):
        self.sent += data

    def recv_exact(self, count):
        if len(self._incoming) < count:
            raise ConnectionError("the camera closed the connection")
        out = bytes(self._incoming[:count])
        del self._incoming[:count]
        return out

    def close(self):
        self.closed = True


def factory_for(transport):
    return lambda host, port, timeout_s: transport


def client_for(transport):
    return camera.BambuCameraClient(HOST, CODE, transport_factory=factory_for(transport))


def test_auth_packet_layout():
    packet = camera.auth_packet(CODE)
    assert len(packet) == 80
    assert struct.unpack_from("<II", packet, 0) == (0x40, 0x3000)
    assert packet[16:20] == b"bblp"
    assert packet[48:48 + len(CODE)] == CODE.encode()


def test_snapshot_returns_the_first_usable_jpeg_frame():
    transport = FakeTransport(frame(b"not-a-jpeg") + frame(JPEG))
    assert client_for(transport).snapshot() == JPEG
    assert transport.sent == camera.auth_packet(CODE)
    assert transport.closed


def test_snapshot_trims_padding_after_the_jpeg_end_marker():
    transport = FakeTransport(frame(JPEG + b"\x00\x00\x00"))
    assert client_for(transport).snapshot() == JPEG


def test_oversized_frame_is_refused_without_leaking_the_code():
    transport = FakeTransport(struct.pack("<IIII", camera.MAX_SNAPSHOT_BYTES + 1, 0, 0, 0))
    with pytest.raises(BambuLanError) as excinfo:
        client_for(transport).snapshot()
    assert CODE not in str(excinfo.value)


def test_non_jpeg_frames_fail_plainly_with_no_payload_or_code_in_the_error():
    payload = b"garbage-frame-that-is-not-a-jpeg"
    transport = FakeTransport(frame(payload) * camera._MAX_FRAMES)
    with pytest.raises(BambuLanError) as excinfo:
        client_for(transport).snapshot()
    message = str(excinfo.value)
    assert CODE not in message and "garbage-frame" not in message


def test_auth_refusal_looks_like_a_closed_connection_and_fails_plainly():
    transport = FakeTransport(b"")  # the printer closes instead of streaming: auth refused
    with pytest.raises(BambuLanError) as excinfo:
        client_for(transport).snapshot()
    message = str(excinfo.value)
    assert CODE not in message and "access code may be wrong" in message


def test_unreachable_camera_fails_plainly():
    def factory(host, port, timeout_s):
        raise OSError("no route to host")
    client = camera.BambuCameraClient(HOST, CODE, transport_factory=factory)
    with pytest.raises(BambuLanError) as excinfo:
        client.snapshot()
    assert "could not be reached" in str(excinfo.value) and CODE not in str(excinfo.value)


def test_validate_snapshot_bytes_contract():
    assert camera.validate_snapshot_bytes(JPEG) == JPEG
    assert camera.validate_snapshot_bytes(JPEG + b"pad") == JPEG
    for bad in (b"", b"\x89PNG....\xff\xd9", b"\xff\xd8no-end-marker",
                b"\xff\xd8" + b"x" * camera.MAX_SNAPSHOT_BYTES + b"\xff\xd9"):
        with pytest.raises(BambuLanError):
            camera.validate_snapshot_bytes(bad)


def test_camera_kind_mapping_is_the_documented_one():
    for key in ("bambulab.a1", "bambulab.a1mini", "bambulab.p1p", "bambulab.p1s"):
        assert camera.camera_kind(key) == "tcp6000"
    for key in ("bambulab.x1", "bambulab.x1c", "bambulab.x1e"):
        assert camera.camera_kind(key) == "rtsps"
    # Not in the research doc's camera row: unverified, stated as None rather than guessed.
    assert camera.camera_kind("bambulab.p2s") is None
    assert camera.camera_kind("bambulab.h2s") is None
    assert camera.camera_kind(None) is None


def _adapter(key, monkeypatch, lan=True):
    config = {"bambu": {"lan_host": HOST, "lan_serial": "00M00A000000000"} if lan else {}}
    monkeypatch.setenv("BAMBU_LAN_PASSWORD", CODE)
    return printers.get(key, config)


def test_adapter_snapshot_uses_the_tcp6000_client(monkeypatch):
    adapter = _adapter("bambulab.a1", monkeypatch)
    transport = FakeTransport(frame(JPEG))
    assert adapter.camera_snapshot(transport_factory=factory_for(transport)) == JPEG


def _pinned_adapter(key, monkeypatch, pin):
    config = {"bambu": {"lan_host": HOST, "lan_serial": "00M00A000000000"},
              "services": {"camera_source": pin}}
    monkeypatch.setenv("BAMBU_LAN_PASSWORD", CODE)
    return printers.get(key, config)


def test_adapter_camera_pin_none_and_moonraker_refuse_before_any_lan_work(monkeypatch):
    # 2.2.2 wiring: [services] camera_source was a dead option for the
    # Bambu paths too — "none" did not turn the printer's camera off and
    # a moonraker pin changed nothing. Both now refuse by name, ahead of
    # the model/LAN checks, and no frame source is handed out either.
    for pin, needle in (("none", "camera_source is none"),
                        ("moonraker", "camera_source is moonraker")):
        adapter = _pinned_adapter("bambulab.a1", monkeypatch, pin)
        with pytest.raises(BambuLanError) as excinfo:
            adapter.camera_snapshot()
        assert needle in str(excinfo.value)
        with pytest.raises(BambuLanError) as excinfo:
            adapter.camera_frame_source()
        assert needle in str(excinfo.value)


def test_adapter_camera_pin_bambu_go2rtc_and_auto_leave_the_vendor_path(monkeypatch):
    for pin in ("bambu", "go2rtc", "auto"):
        adapter = _pinned_adapter("bambulab.a1", monkeypatch, pin)
        transport = FakeTransport(frame(JPEG))
        assert adapter.camera_snapshot(transport_factory=factory_for(transport)) == JPEG


def test_adapter_snapshot_without_lan_configuration_is_a_plain_note(monkeypatch):
    adapter = _adapter("bambulab.a1", monkeypatch, lan=False)
    with pytest.raises(BambuLanError) as excinfo:
        adapter.camera_snapshot()
    assert "camera is not configured" in str(excinfo.value)


def test_adapter_snapshot_for_x1_names_the_deferred_rtsp_path(monkeypatch):
    # Superseded by the go2rtc stills test below: X1 stills are no longer
    # deferred, they route through the fan-out; with go2rtc not running the
    # error names exactly what to enable instead.
    adapter = _adapter("bambulab.x1", monkeypatch)
    with pytest.raises(BambuLanError) as excinfo:
        adapter.camera_snapshot(fanout=lambda: None, resolved=lambda: None)
    message = str(excinfo.value)
    assert "go2rtc is not running" in message and "capture_source_url" in message
    assert CODE not in message


# -- X1 family: stills through the go2rtc fan-out -----------------------------

FRAME_URL = "http://127.0.0.1:1984/api/frame.jpeg?src=printer"


def test_rtsp_url_is_the_documented_stream():
    url = camera.rtsp_url(HOST, CODE)
    assert url == f"rtsps://bblp:{CODE}@192.168.1.50:322/streaming/live/1"


def test_fanout_frame_url_matches_this_printers_stream():
    seams = dict(fanout=lambda: FRAME_URL, resolved=lambda: camera.rtsp_url(HOST, CODE))
    assert camera.fanout_frame_url(HOST, CODE, **seams) == FRAME_URL
    # An rtsp:// spelling of the same stream (operator's hand) still matches.
    seams["resolved"] = lambda: f"rtsp://bblp:{CODE}@192.168.1.50:322/streaming/live/1"
    assert camera.fanout_frame_url(HOST, CODE, **seams) == FRAME_URL


def test_fanout_frame_url_names_the_limitation_when_go2rtc_is_down():
    with pytest.raises(BambuLanError) as excinfo:
        camera.fanout_frame_url(HOST, CODE, fanout=lambda: None, resolved=lambda: None)
    message = str(excinfo.value)
    assert "go2rtc is not running" in message and "no snapshot was taken" in message
    assert CODE not in message


def test_fanout_frame_url_refuses_a_different_camera_source():
    for other in (f"rtsps://bblp:{CODE}@192.168.1.99:322/streaming/live/1",
                  "http://192.168.1.50:8080/?action=snapshot",
                  f"rtsps://bblp:{CODE}@192.168.1.50:322/other/path",
                  None):
        with pytest.raises(BambuLanError) as excinfo:
            camera.fanout_frame_url(HOST, CODE, fanout=lambda: FRAME_URL,
                                    resolved=lambda other=other: other)
        assert "not this printer's stream" in str(excinfo.value)
        assert CODE not in str(excinfo.value)


def test_fanout_snapshot_fetches_the_still_from_the_fanout():
    seen = []
    image = camera.fanout_snapshot(
        HOST, CODE, fanout=lambda: FRAME_URL,
        resolved=lambda: camera.rtsp_url(HOST, CODE),
        fetch=lambda url: seen.append(url) or JPEG)
    assert image == JPEG and seen == [FRAME_URL]


def test_fetch_url_jpeg_validates_like_a_port6000_snapshot(monkeypatch):
    class Response:
        def __init__(self, body):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _count):
            return self._body

    monkeypatch.setattr(camera.urllib.request, "urlopen",
                        lambda request, timeout=None: Response(JPEG + b"pad"))
    assert camera.fetch_url_jpeg(FRAME_URL) == JPEG
    monkeypatch.setattr(camera.urllib.request, "urlopen",
                        lambda request, timeout=None: Response(b"not-a-jpeg"))
    with pytest.raises(BambuLanError):
        camera.fetch_url_jpeg(FRAME_URL)


def test_adapter_snapshot_for_x1_comes_through_go2rtc(monkeypatch):
    adapter = _adapter("bambulab.x1c", monkeypatch)
    image = adapter.camera_snapshot(
        fanout=lambda: FRAME_URL, resolved=lambda: camera.rtsp_url(HOST, CODE),
        fetch=lambda url: JPEG)
    assert image == JPEG


def test_adapter_snapshot_for_an_unverified_model_says_so(monkeypatch):
    adapter = _adapter("bambulab.p2s", monkeypatch)
    with pytest.raises(BambuLanError) as excinfo:
        adapter.camera_snapshot()
    assert "has not verified a camera protocol" in str(excinfo.value)


# -- the timelapse frame source (#295) -----------------------------------------

def test_frame_source_for_a1_is_the_tcp6000_snapshot(monkeypatch):
    adapter = _adapter("bambulab.a1", monkeypatch)

    class FakeClient:
        def __init__(self, host, code, **kwargs):
            pass

        def snapshot(self):
            return JPEG

    monkeypatch.setattr(camera, "BambuCameraClient", FakeClient)
    url, fetch = adapter.camera_frame_source()
    assert url == f"bambu-tcp6000://{HOST}"
    assert fetch("ignored") == JPEG


def test_frame_source_for_x1_is_the_go2rtc_still(monkeypatch):
    adapter = _adapter("bambulab.x1", monkeypatch)
    monkeypatch.setattr(camera, "_default_fanout_url", lambda: FRAME_URL)
    monkeypatch.setattr(camera, "_default_resolved_source",
                        lambda: camera.rtsp_url(HOST, CODE))
    url, fetch = adapter.camera_frame_source()
    assert url == FRAME_URL and fetch is camera.fetch_url_jpeg


def test_frame_source_for_x1_names_the_go2rtc_limitation(monkeypatch):
    adapter = _adapter("bambulab.x1", monkeypatch)
    monkeypatch.setattr(camera, "_default_fanout_url", lambda: None)
    with pytest.raises(BambuLanError) as excinfo:
        adapter.camera_frame_source()
    assert "go2rtc is not running" in str(excinfo.value)
    assert CODE not in str(excinfo.value)


def test_frame_source_for_an_unverified_model_says_so(monkeypatch):
    adapter = _adapter("bambulab.p2s", monkeypatch)
    with pytest.raises(BambuLanError) as excinfo:
        adapter.camera_frame_source()
    assert "has not verified a camera protocol" in str(excinfo.value)
