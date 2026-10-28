"""PrusaLink camera source (#295): client endpoints + the camera seam, offline.

The client runs against a fake opener serving the published PrusaLink
camera API shapes; the transcoder runs against real PNG stills made
with Pillow. No socket and no printer is ever touched, and nothing here
claims live-hardware verification (the whole Prusa vendor is
offline-verified only).
"""
import io
import json

import pytest
from PIL import Image

from print_handy.printers.prusa import camera
from print_handy.printers.prusa.client import PrusaLinkClient, PrusaLinkError

CAMERAS = [
    {"camera_id": "usb-cam", "connected": True, "config": {"name": "USB camera"}},
    {"camera_id": "detached", "connected": False, "config": {"name": "Old camera"}},
]


def png_bytes(colour="red"):
    out = io.BytesIO()
    Image.new("RGB", (64, 48), colour).save(out, format="PNG")
    return out.getvalue()


class _Raw:
    def __init__(self, status, body=b""):
        self.status = status
        self.headers = {}
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePrusaLinkCameras:
    """An in-memory PrusaLink camera API: records requests, serves canned answers."""

    def __init__(self, cameras=None, *, snap_status=200, snap_body=None, cameras_status=200):
        self.requests = []
        self.cameras = CAMERAS if cameras is None else cameras
        self.snap_status = snap_status
        self.snap_body = png_bytes() if snap_body is None else snap_body
        self.cameras_status = cameras_status

    def __call__(self, req, timeout=None):
        url, method = req.full_url, req.get_method()
        self.requests.append((method, url))
        path = url[url.index("/api"):]
        if path == "/api/v1/cameras":
            if self.cameras_status != 200:
                return _Raw(self.cameras_status, {"title": "Not Found", "text": "no camera API"})
            return _Raw(200, self.cameras)
        if path.startswith("/api/v1/cameras/") and path.endswith("/snap"):
            return _Raw(self.snap_status, self.snap_body if self.snap_status == 200 else b"")
        if path == "/api/v1/cameras/snap":
            return _Raw(self.snap_status, self.snap_body if self.snap_status == 200 else b"")
        return _Raw(404, {"title": "Not Found", "text": "unknown path"})


def client_for(fake):
    return PrusaLinkClient("printer.local", "test-key", opener=fake)


# --------------------------------------------------------------------------- client


def test_client_cameras_parses_the_bare_list():
    client = client_for(FakePrusaLinkCameras())
    cameras = client.cameras()
    assert [c["camera_id"] for c in cameras] == ["usb-cam", "detached"]


def test_client_cameras_parses_a_wrapped_list():
    fake = FakePrusaLinkCameras()
    fake.cameras = {"camera_list": CAMERAS}
    assert client_for(fake).cameras() == CAMERAS


def test_client_cameras_404_raises_like_any_refusal():
    client = client_for(FakePrusaLinkCameras(cameras_status=404))
    with pytest.raises(PrusaLinkError, match="answered 404"):
        client.cameras()


def test_client_camera_snapshot_returns_png_bytes():
    fake = FakePrusaLinkCameras()
    client = client_for(fake)
    body = client.camera_snapshot("usb-cam")
    assert body == fake.snap_body and body.startswith(camera.PNG_MAGIC)
    assert fake.requests[0][1].endswith("/api/v1/cameras/usb-cam/snap")


def test_client_camera_snapshot_default_camera_path():
    fake = FakePrusaLinkCameras()
    client_for(fake).camera_snapshot()
    assert fake.requests[0][1].endswith("/api/v1/cameras/snap")


@pytest.mark.parametrize("status", [204, 304])
def test_client_camera_snapshot_no_image_is_none_not_an_error(status):
    client = client_for(FakePrusaLinkCameras(snap_status=status))
    assert client.camera_snapshot("usb-cam") is None


# --------------------------------------------------------------------------- the seam


def test_default_camera_id_picks_the_first_connected():
    assert camera.default_camera_id(client_for(FakePrusaLinkCameras())) == "usb-cam"


def test_default_camera_id_empty_when_nothing_connected():
    fake = FakePrusaLinkCameras(cameras=[{"camera_id": "x", "connected": False}])
    assert camera.default_camera_id(client_for(fake)) == ""


def test_default_camera_id_empty_list_means_no_camera():
    assert camera.default_camera_id(client_for(FakePrusaLinkCameras(cameras=[]))) == ""


def test_default_camera_id_raises_when_the_printer_cannot_be_read():
    def dead_opener(req, timeout=None):
        raise OSError("no route to host")

    client = PrusaLinkClient("printer.local", "test-key", opener=dead_opener)
    with pytest.raises(PrusaLinkError):
        camera.default_camera_id(client)


def test_snapshot_url_names_the_endpoint_without_any_credential():
    client = client_for(FakePrusaLinkCameras())
    assert camera.snapshot_url(client, "usb-cam") == \
        "http://printer.local/api/v1/cameras/usb-cam/snap"
    assert camera.snapshot_url(client, "") == "http://printer.local/api/v1/cameras/snap"
    assert "test-key" not in camera.snapshot_url(client, "usb-cam")


def test_snapshot_jpeg_transcodes_the_png_still_to_jpeg():
    client = client_for(FakePrusaLinkCameras())
    image = camera.snapshot_jpeg(client, "usb-cam")
    assert image.startswith(b"\xff\xd8")  # JPEG magic: the capture pipeline's frame shape
    with Image.open(io.BytesIO(image)) as decoded:
        assert decoded.format == "JPEG" and decoded.size == (64, 48)


def test_snapshot_jpeg_raises_when_no_image_yet():
    client = client_for(FakePrusaLinkCameras(snap_status=204))
    with pytest.raises(PrusaLinkError, match="no snapshot image"):
        camera.snapshot_jpeg(client, "usb-cam")


def test_snapshot_jpeg_refuses_a_non_png_answer():
    client = client_for(FakePrusaLinkCameras(snap_body=b"\xff\xd8\xff\xe0jpeg-not-png"))
    with pytest.raises(PrusaLinkError, match="not a bounded PNG"):
        camera.snapshot_jpeg(client, "usb-cam")
