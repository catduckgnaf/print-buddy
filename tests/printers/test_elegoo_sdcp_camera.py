"""Elegoo SDCP camera seam (#295): the unverified-source posture, pinned.

No SDCP camera endpoint is verified in this codebase (the audit lives
in printers/elegoo_sdcp/camera.py's docstring), so the seam resolves
to "no source" for any client. These tests pin that contract: if a
source is ever verified and wired, they fail on purpose and must be
replaced by fixture tests for the real endpoint — they must never be
quietly relaxed to bless an invented URL.
"""
from print_buddy.printers.elegoo_sdcp import camera


class FakeClient:
    """Stands in for SdcpClient; the seam must not need anything from it."""

    host = "192.0.2.30"


def test_camera_source_resolves_to_no_source():
    assert camera.camera_source(FakeClient()) == ("", None)


def test_camera_source_needs_no_client_at_all():
    # The seam's answer does not depend on reaching the printer: an
    # unreachable or half-configured client still yields the honest
    # "no source", so the monitor's once-per-print diagnostic is the
    # unverified camera, never a transport error.
    assert camera.camera_source(None) == ("", None)
