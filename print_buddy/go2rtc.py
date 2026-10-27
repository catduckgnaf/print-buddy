"""go2rtc supervision gate and generated configuration (#246, Stage 1).

Stage 1 is container plumbing only: the full image bundles a pinned go2rtc
binary (docker/go2rtc-prebuilt.sh), and docker/supervise.sh runs it as a
supervised child exactly when a feature needs the camera fan-out.
go2rtc's only job is stream normalisation — it ingests the configured
camera source and restreams it on loopback; nothing in this module
captures frames or encodes video.

Two features share the one upstream camera pull (the #311 contention
rule: go2rtc holds the single connection to the camera and fans out):

- in-container timelapse capture (#246), when ``[timelapse]
  capture_enabled`` is set;
- live camera viewing in Discord (#311), when ``[live_stream] enabled``
  is set — the Activity page plays the restreamed feed, so live viewing
  must not require timelapse capture to be on.

This module is the shell-facing gate, mirroring print_buddy.listener_gate:

    python3 -m print_buddy.go2rtc              # gate: exit 0 / 3 / 2
    python3 -m print_buddy.go2rtc --write-config

Exit codes: 0 = a feature needs go2rtc and a camera source resolved,
start go2rtc; 3 = not started (no feature needs it, or one does but no
camera source is configured — the feature degrades off, the container
is unaffected); 2 = the configuration could not be resolved (settings
error; the supervisor stops rather than guessing, like the listener
gate).

The generated configuration binds go2rtc's API (1984) and RTSP (8554) to
loopback only, and renders the one stream under
:data:`print_buddy.live_stream.GO2RTC_STREAM_NAME` — the name the
timelapse capture polls and the #311 Activity page requests. It contains
the camera source URL, which may carry credentials, so it is written
with 0600 permissions, lives under the cache path with the other runtime
files, and is never logged unredacted: every message this module prints
passes URLs through print_buddy.live_stream.redact_url.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

from . import settings
from .live_stream import (GO2RTC_STREAM_NAME, CameraSource, LiveStreamError,
                          derive_from_snapshot_url, redact_url)

API_URL = "http://127.0.0.1:1984/api"
#: Where go2rtc serves a JPEG still of the one published stream, on its
#: loopback API. Every stills consumer (timelapse capture, the camera
#: watchdog) reads from this one URL while go2rtc is running, so no
#: consumer ever opens a second direct connection to the camera.
FRAME_URL = f"http://127.0.0.1:1984/api/frame.jpeg?src={GO2RTC_STREAM_NAME}"
DEFAULT_BINARY = "/usr/local/bin/go2rtc"


def binary_path(environ=None) -> str:
    """Where the bundled go2rtc binary lives (GO2RTC_BIN overrides, for tests)."""
    return (environ or os.environ).get("GO2RTC_BIN", DEFAULT_BINARY)


def binary_present(environ=None) -> bool:
    """True when this image bundles go2rtc (a WITH_GO2RTC=false build does not)."""
    return os.access(binary_path(environ), os.X_OK)


def capture_enabled(data=None) -> bool:
    """True when [timelapse] capture_enabled is set in the resolved settings."""
    data = settings.current() if data is None else data
    return bool(data.get("timelapse", {}).get("capture_enabled", False))


def live_enabled(data=None) -> bool:
    """True when [live_stream] enabled is set in the resolved settings (#311)."""
    data = settings.current() if data is None else data
    return bool(data.get("live_stream", {}).get("enabled", False))


def needed_by(data=None) -> tuple:
    """The features that need the go2rtc fan-out, in report order.

    Timelapse capture (#246) and live viewing (#311) share the one
    upstream camera pull, so either one needing go2rtc starts the same
    single child with the same generated config.
    """
    data = settings.current() if data is None else data
    needed = []
    if capture_enabled(data):
        needed.append("timelapse capture")
    if live_enabled(data):
        needed.append("live viewing")
    return tuple(needed)


def fanout_frame_url(data=None, environ=None) -> str | None:
    """The go2rtc stills URL when go2rtc should be running, else None.

    go2rtc should be running exactly when a feature needs the fan-out
    (:func:`needed_by`), the bundled binary is present, and a camera
    source resolves — the same conditions the supervisor's gate starts
    it under. Consumers that need a still (the camera watchdog) use this
    URL in that case, so the camera keeps exactly one upstream pull;
    when it returns None go2rtc is not expected to be running and the
    consumer's own direct snapshot URL is the sole pull, as before.
    Any resolution failure reads as None: a stills consumer must never
    be broken by the fan-out's configuration.
    """
    try:
        data = settings.current() if data is None else data
        if not needed_by(data) or not binary_present(environ):
            return None
        if resolve_source(data) is None:
            return None
    except Exception:
        return None
    return FRAME_URL


def resolve_source(data=None) -> CameraSource | None:
    """The camera source go2rtc should ingest, or None when none is configured.

    An explicit [timelapse] capture_source_url wins; otherwise the source
    derives from services.camera_snapshot_url (which settings validation
    already derives from the Moonraker host for the standard Moonraker
    webcam case) via print_buddy.live_stream's snapshot derivation.
    A go2rtc ``ffmpeg:`` source is passed through verbatim as the stream
    URL — go2rtc, not this module, interprets it.
    """
    data = settings.current() if data is None else data
    override = (data.get("timelapse", {}).get("capture_source_url") or "").strip()
    if override.startswith("ffmpeg:"):
        return CameraSource(stream_url=override, snapshot_url=None,
                            kind="mjpeg", name=GO2RTC_STREAM_NAME)
    if override.startswith(("rtsp://", "rtsps://")):
        return CameraSource(stream_url=override, snapshot_url=None,
                            kind="rtsp", name=GO2RTC_STREAM_NAME)
    url = override or (data.get("services", {}).get("camera_snapshot_url") or "").strip()
    if not url:
        return None
    return derive_from_snapshot_url(url, name=GO2RTC_STREAM_NAME)


def source_url(source: CameraSource) -> str:
    """The single URL go2rtc ingests: the stream, or the snapshot for a
    snapshot-only source (go2rtc serves stills/MJPEG from it)."""
    return source.stream_url or source.snapshot_url or ""


def render_config(source: CameraSource) -> str:
    """go2rtc YAML for one camera source; API and RTSP bind loopback only.

    The URL is emitted as a JSON string scalar, which is valid YAML and
    needs no hand-rolled escaping. The file holds the raw URL (go2rtc
    needs it), so callers must treat the file as a secret.
    """
    lines = [
        "# Generated by Print Buddy (print_buddy.go2rtc) from settings; do not edit.",
        "# Holds the camera source URL, which may carry credentials: keep private.",
        "api:",
        '  listen: "127.0.0.1:1984"',
        "rtsp:",
        '  listen: "127.0.0.1:8554"',
        "log:",
        "  level: info",
        "streams:",
        f"  {GO2RTC_STREAM_NAME}: {json.dumps(source_url(source))}",
        "",
    ]
    return "\n".join(lines)


def config_path(data=None, environ=None) -> Path:
    """Where the generated config is written (GO2RTC_CONFIG overrides, for tests)."""
    override = (environ or os.environ).get("GO2RTC_CONFIG")
    if override:
        return Path(override)
    data = settings.current() if data is None else data
    return Path(data["paths"]["cache"]) / "go2rtc" / "go2rtc.yaml"


def write_config(path=None, data=None) -> Path:
    """Generate the go2rtc config from settings and write it 0600."""
    data = settings.current() if data is None else data
    source = resolve_source(data)
    if source is None:
        raise LiveStreamError("no camera source is configured for go2rtc")
    path = Path(path) if path is not None else config_path(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(render_config(source))
    os.chmod(path, 0o600)
    return path


def gate(data=None) -> int:
    """The supervisor/healthcheck decision: 0 start, 3 not started, 2 unresolved."""
    try:
        data = settings.current() if data is None else data
        needed = needed_by(data)
        if not needed:
            print("go2rtc gate: timelapse capture and live viewing are both "
                  "disabled; not starting go2rtc")
            return 3
        source = resolve_source(data)
    except settings.SettingsError as exc:
        print(f"go2rtc gate: configuration unresolved: {exc}", file=sys.stderr)
        return 2
    except LiveStreamError as exc:
        print(f"go2rtc gate: camera source unresolved: {exc}; not starting go2rtc")
        return 3
    if source is None:
        print(f"go2rtc gate: {' and '.join(needed)} enabled but no camera source "
              "is configured; not starting go2rtc")
        return 3
    print(f"go2rtc gate: {' and '.join(needed)} enabled, "
          f"source {redact_url(source_url(source))}")
    return 0


def check(url=API_URL, timeout=3) -> tuple[bool, str]:
    """Health probe for the docker healthcheck: go2rtc's API on loopback."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200, f"HTTP {response.status}"
    except Exception as exc:  # the healthcheck reports, never raises
        return False, str(exc)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--write-config"]:
        # stdout carries ONLY the written path: docker/supervise.sh captures it.
        try:
            print(write_config())
        except (settings.SettingsError, LiveStreamError) as exc:
            print(f"go2rtc: could not write config: {exc}", file=sys.stderr)
            return 2
        return 0
    if argv:
        print("usage: python3 -m print_buddy.go2rtc [--write-config]", file=sys.stderr)
        return 2
    return gate()


if __name__ == "__main__":
    sys.exit(main())
