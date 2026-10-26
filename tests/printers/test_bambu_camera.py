"""Bambu Lab camera snapshots (#294 stage 1): offline tests only — a fake TCP transport, never a socket.

The fake implements the transport contract camera.py defines (sendall / recv_exact / close)
and serves scripted port-6000 framing: a 16-byte little-endian header whose first word is the
frame size, then the frame bytes. The authentication packet layout is the protocol behaviour
of the maintained clients cited in docs/BAMBU-CONNECTIVITY.md; nothing here is a real printer.
"""
import struct

import pytest

from print_buddy import printers
from print_buddy.printers.bambulab import camera
from print_buddy.printers.bambulab.client import BambuLanError

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


def test_adapter_snapshot_without_lan_configuration_is_a_plain_note(monkeypatch):
    adapter = _adapter("bambulab.a1", monkeypatch, lan=False)
    with pytest.raises(BambuLanError) as excinfo:
        adapter.camera_snapshot()
    assert "camera is not configured" in str(excinfo.value)


def test_adapter_snapshot_for_x1_names_the_pending_rtsp_path(monkeypatch):
    adapter = _adapter("bambulab.x1", monkeypatch)
    with pytest.raises(BambuLanError) as excinfo:
        adapter.camera_snapshot()
    assert "#246" in str(excinfo.value) and CODE not in str(excinfo.value)


def test_adapter_snapshot_for_an_unverified_model_says_so(monkeypatch):
    adapter = _adapter("bambulab.p2s", monkeypatch)
    with pytest.raises(BambuLanError) as excinfo:
        adapter.camera_snapshot()
    assert "has not verified a camera protocol" in str(excinfo.value)
