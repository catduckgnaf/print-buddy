"""Live camera source resolution and encoder planning (issue #311, stages 1-2).

Stage 1 — camera source core. This module resolves one normalised
:class:`CameraSource` from the payloads Print Buddy already knows how to
obtain, without performing any network I/O itself: callers fetch a payload
through their existing client/transport and pass the parsed result in, so
every resolver here is pure, stdlib-only and offline-testable, following
the precedent of :mod:`print_buddy.macros`.

- **Moonraker** (which also covers Fluidd and Mainsail households — both
  are frontends over the same Moonraker webcam registry, so there is no
  separate Fluidd integration): a webcams-API payload of the shape
  ``{"webcams": [...]}`` whose entries carry ``stream_url`` /
  ``snapshot_url`` / ``service`` / ``name``. Relative URLs are resolved
  against the Moonraker base URL; the configured (preferred) name wins,
  otherwise the first usable webcam.
- **Fallback derivation**: when there is no usable webcams payload, a
  stream URL is derived from the existing snapshot-URL convention
  (``?action=snapshot`` becomes ``?action=stream``). A snapshot URL with
  no ``action`` parameter does not imply a stream, so the source stays
  snapshot-kind.
- **OctoPrint**: a settings payload carrying the classic webcam fields
  (``streamUrl`` / ``snapshotUrl``, usually under a ``webcam`` key).
  Relative URLs resolve against the OctoPrint base. A multi-webcam style
  payload (a ``webcams`` list under the payload or under ``webcam``) is
  handled the same way when present; otherwise the legacy single-webcam
  shape is the supported one.
- **Snapshot-only**: a source with only a snapshot URL is a valid
  :class:`CameraSource` of kind ``snapshot`` (a later stage can turn it
  into an image sequence; it is labelled honestly, not as a stream).

Credentials: camera URLs may carry userinfo or secret query values in the
wild. The resolved :class:`CameraSource` keeps the real URLs as fields
(the encoder needs them), but its ``repr`` — and every error message this
module raises — passes URLs through :func:`redact_url`, so a password or
secret query value never appears in a repr, a log-facing string or an
error.

Stage 2 — codec-aware encoder plan. Discord voice video targets H.264 or
VP8, so encoder selection is codec-aware:

- H.264 default order: VAAPI, NVENC, QSV, CPU (``libx264``).
- VP8 default order: VAAPI (``vp8_vaapi``), CPU (``libvpx``). NVENC has
  no VP8 encoder and QSV is not a VP8 target here, so neither ever
  appears for VP8.
- An explicit preference (``vaapi`` / ``qsv`` / ``nvenc`` / ``cpu``)
  moves that vendor first when it is given *and* available; otherwise
  the default order stands.

Availability comes from an injected probe (:class:`EncoderProbe`: the set
of encoder names ffmpeg reports, whether ``/dev/dri`` is present, and
whether an NVIDIA device is present). VAAPI and QSV candidates require
``dri_present``; NVENC requires ``nvidia_present``; every candidate also
requires its encoder name to be in the probed set. No probing, process
execution or hardware access happens in this module.

:func:`build_ffmpeg_args` is a pure argv builder for one chosen
candidate. Its output decision is deliberate and narrow: the argv ends
with exactly the caller-supplied ``output`` argument and the builder
adds no muxer, RTP or Discord-specific flags. A later transport stage
supplies that output target (for example a pipe target it owns) and any
muxer flags its transport needs; this module does not invent a Discord
transport.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

__all__ = [
    "CAMERA_KINDS",
    "ENCODER_PREFERENCES",
    "TARGET_CODECS",
    "VAAPI_DEVICE",
    "CameraSource",
    "EncoderCandidate",
    "EncoderProbe",
    "LiveStreamError",
    "build_ffmpeg_args",
    "build_ffmpeg_command",
    "camera_source_from_moonraker",
    "camera_source_from_octoprint",
    "derive_from_snapshot_url",
    "encoder_candidates",
    "plan_encoders",
    "redact_url",
    "resolve_moonraker_camera_source",
    "resolve_octoprint_camera_source",
]

CAMERA_KINDS = ("mjpeg", "rtsp", "webrtc", "snapshot")
TARGET_CODECS = ("h264", "vp8")
ENCODER_PREFERENCES = ("auto", "vaapi", "qsv", "nvenc", "cpu")
VAAPI_DEVICE = "/dev/dri/renderD128"

_SENSITIVE_QUERY_KEYS = frozenset({
    "token", "api_key", "apikey", "api-key", "access_token", "access-token",
    "password", "passwd", "secret", "key", "auth", "authorization",
    "signature", "sig", "credential", "credentials",
})


class LiveStreamError(RuntimeError):
    """A camera source could not be resolved, or an encoder plan is invalid.

    Messages never contain URL userinfo, passwords or secret query values;
    any URL included in a message has passed through :func:`redact_url`.
    """


# --------------------------------------------------------------------- redaction

def redact_url(url) -> str:
    """Return `url` with userinfo and secret query values replaced by ``***``.

    Safe to call on any value: non-strings and unparseable values return a
    fixed placeholder rather than the raw input, so a malformed
    credential-bearing string cannot leak through an error message.
    """
    if not url or not isinstance(url, str):
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "***"
    if not parts.netloc and not parts.query:
        # A relative path carries no userinfo; still scrub a query if present.
        return url.strip()
    host = parts.hostname or ""
    if parts.username or parts.password:
        netloc = f"***@{host}"
    else:
        netloc = host
    try:
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
    except ValueError:
        netloc = f"{netloc}:***"
    query = ""
    if parts.query:
        pairs = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            lowered = key.casefold()
            if lowered in _SENSITIVE_QUERY_KEYS or any(
                    word in lowered for word in ("token", "secret", "password", "passwd")):
                pairs.append((key, "***"))
            else:
                pairs.append((key, value))
        query = urlencode(pairs)
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def _is_sensitive_key(key: str) -> bool:
    lowered = key.casefold()
    return lowered in _SENSITIVE_QUERY_KEYS or any(
        word in lowered for word in ("token", "secret", "password", "passwd"))


# --------------------------------------------------------------------- helpers

def _clean(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _resolve_url(base_url, raw_url, *, context: str):
    """Resolve `raw_url` against `base_url`; absolute URLs pass through."""
    url = _clean(raw_url)
    if url is None:
        return None
    parts = urlsplit(url)
    if parts.scheme:
        if parts.scheme not in ("http", "https", "rtsp", "rtsps", "webrtc"):
            raise LiveStreamError(
                f"{context}: unsupported camera URL scheme in {redact_url(url)!r}")
        return url
    base = _clean(base_url)
    if not base:
        raise LiveStreamError(
            f"{context}: relative camera URL {redact_url(url)!r} has no base URL to resolve against")
    if urlsplit(base).scheme not in ("http", "https"):
        raise LiveStreamError(f"{context}: base URL {redact_url(base)!r} is not an http(s) URL")
    return urljoin(base.rstrip("/") + "/", url)


def _infer_kind(stream_url, snapshot_url, service=None) -> str:
    if stream_url:
        service_text = (service or "").casefold()
        stream_text = stream_url.casefold()
        if urlsplit(stream_url).scheme in ("rtsp", "rtsps"):
            return "rtsp"
        if "webrtc" in service_text or "webrtc" in stream_text:
            return "webrtc"
        return "mjpeg"
    if snapshot_url:
        return "snapshot"
    raise LiveStreamError("camera source has neither a stream URL nor a snapshot URL")


def _make_source(*, stream_url, snapshot_url, name="", service=None) -> "CameraSource":
    """Build a source, deriving the stream from the snapshot when needed."""
    if stream_url:
        kind = _infer_kind(stream_url, snapshot_url, service)
        return CameraSource(stream_url=stream_url, snapshot_url=snapshot_url,
                            kind=kind, name=name or "", service=service)
    if snapshot_url:
        derived = derive_from_snapshot_url(snapshot_url, name=name or "", service=service)
        return derived
    raise LiveStreamError("camera source has neither a stream URL nor a snapshot URL")


# --------------------------------------------------------------------- CameraSource

@dataclass(frozen=True)
class CameraSource:
    """One normalised camera source.

    `stream_url` is ``None`` for a snapshot-only source (`kind` is then
    ``"snapshot"``). The fields hold the real URLs; ``repr`` redacts them,
    so logging a source never logs a credential.
    """

    stream_url: str | None
    snapshot_url: str | None
    kind: str
    name: str = ""
    service: str | None = None

    def __post_init__(self):
        if self.kind not in CAMERA_KINDS:
            raise LiveStreamError(f"unknown camera source kind {self.kind!r}")
        if self.kind == "snapshot" and self.stream_url is not None:
            raise LiveStreamError("a snapshot-kind camera source must not carry a stream URL")
        if self.kind != "snapshot" and not self.stream_url:
            raise LiveStreamError(f"a {self.kind} camera source needs a stream URL")
        if not self.stream_url and not self.snapshot_url:
            raise LiveStreamError("a camera source needs a stream URL or a snapshot URL")

    def __repr__(self):
        return (f"CameraSource(name={self.name!r}, kind={self.kind!r}, "
                f"stream_url={redact_url(self.stream_url)!r}, "
                f"snapshot_url={redact_url(self.snapshot_url)!r}, "
                f"service={self.service!r})")

    @property
    def redacted_stream_url(self) -> str:
        return redact_url(self.stream_url)

    @property
    def redacted_snapshot_url(self) -> str:
        return redact_url(self.snapshot_url)


def derive_from_snapshot_url(snapshot_url, *, name="", service=None) -> CameraSource:
    """Resolve a source from a snapshot URL alone (the fallback derivation).

    ``?action=snapshot`` becomes ``?action=stream`` (kind ``mjpeg``). A
    snapshot URL with no ``action`` parameter yields a snapshot-only
    source (kind ``snapshot``, no stream URL).
    """
    snapshot = _clean(snapshot_url)
    if not snapshot:
        raise LiveStreamError("no snapshot URL was provided to derive a camera source from")
    if urlsplit(snapshot).scheme not in ("http", "https", "rtsp", "rtsps"):
        raise LiveStreamError(
            f"snapshot URL {redact_url(snapshot)!r} is not an http(s) or rtsp URL")
    pairs = parse_qsl(urlsplit(snapshot).query, keep_blank_values=True)
    action_values = [value for key, value in pairs if key == "action"]
    if "snapshot" in action_values:
        new_pairs = [(key, "stream" if (key == "action" and value == "snapshot") else value)
                     for key, value in pairs]
        parts = urlsplit(snapshot)
        stream_url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                                 urlencode(new_pairs), ""))
        return CameraSource(stream_url=stream_url, snapshot_url=snapshot,
                            kind=_infer_kind(stream_url, snapshot, service),
                            name=name or "", service=service)
    return CameraSource(stream_url=None, snapshot_url=snapshot, kind="snapshot",
                        name=name or "", service=service)


# --------------------------------------------------------------------- Moonraker

def _webcam_entries(payload):
    """The webcam entry dicts from a Moonraker-shaped payload, or ``None``.

    Accepts ``{"webcams": [...]}``, ``{"result": {"webcams": [...]}}`` and
    a bare list, so recorded responses replay unchanged. Returns ``None``
    when the payload carries no webcams list at all.
    """
    data = payload
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
        data = data["result"]
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict) and isinstance(data.get("webcams"), list):
        entries = data["webcams"]
    else:
        return None
    return [entry for entry in entries if isinstance(entry, dict)]


def _pick_entry(entries, preferred_name):
    usable = []
    for entry in entries:
        if entry.get("enabled") is False:
            continue
        stream = _clean(entry.get("stream_url") or entry.get("streamUrl"))
        snapshot = _clean(entry.get("snapshot_url") or entry.get("snapshotUrl"))
        if stream or snapshot:
            usable.append(entry)
    if not usable:
        return None
    if preferred_name:
        wanted = str(preferred_name).casefold()
        for entry in usable:
            entry_name = entry.get("name")
            if isinstance(entry_name, str) and entry_name.casefold() == wanted:
                return entry
    return usable[0]


def camera_source_from_moonraker(payload, *, base_url=None, preferred_name=None,
                                 fallback_snapshot_url=None) -> CameraSource:
    """Resolve one camera source from a Moonraker webcams-API payload.

    Fluidd and Mainsail households are covered by this same path: both are
    frontends over Moonraker's webcam registry, whose entries this payload
    lists. When the payload is missing, empty or holds no usable webcam,
    `fallback_snapshot_url` (the existing snapshot-URL convention) is used
    via :func:`derive_from_snapshot_url`; without a fallback that case
    raises :class:`LiveStreamError`.
    """
    entries = _webcam_entries(payload)
    if entries:
        entry = _pick_entry(entries, preferred_name)
        if entry is not None:
            stream = _resolve_url(base_url, entry.get("stream_url") or entry.get("streamUrl"),
                                   context="Moonraker webcam")
            snapshot = _resolve_url(base_url, entry.get("snapshot_url") or entry.get("snapshotUrl"),
                                     context="Moonraker webcam")
            name = entry.get("name") if isinstance(entry.get("name"), str) else ""
            service = entry.get("service") if isinstance(entry.get("service"), str) else None
            return _make_source(stream_url=stream, snapshot_url=snapshot,
                                name=name, service=service)
    if fallback_snapshot_url:
        return derive_from_snapshot_url(fallback_snapshot_url)
    raise LiveStreamError(
        "Moonraker's webcams payload had no usable webcam and no fallback snapshot URL was provided")


def resolve_moonraker_camera_source(*args, **kwargs) -> CameraSource:
    """Alias for :func:`camera_source_from_moonraker`."""
    return camera_source_from_moonraker(*args, **kwargs)


# --------------------------------------------------------------------- OctoPrint

def _octoprint_single_and_entries(payload):
    """Return ``(single_dict_or_None, entries_or_None)`` for an OctoPrint payload."""
    if not isinstance(payload, dict):
        return None, None
    if isinstance(payload.get("webcams"), list):
        return None, [e for e in payload["webcams"] if isinstance(e, dict)]
    webcam = payload.get("webcam")
    if isinstance(webcam, dict):
        if isinstance(webcam.get("webcams"), list):
            return None, [e for e in webcam["webcams"] if isinstance(e, dict)]
        return webcam, None
    if any(key in payload for key in ("streamUrl", "snapshotUrl", "stream_url", "snapshot_url")):
        return payload, None
    return None, None


def camera_source_from_octoprint(payload, *, base_url=None, preferred_name=None,
                                 fallback_snapshot_url=None) -> CameraSource:
    """Resolve one camera source from an OctoPrint settings payload.

    Supports the classic single-webcam shape (``webcam`` with
    ``streamUrl`` / ``snapshotUrl``, or those fields at the top level)
    and, when present, a multi-webcam style ``webcams`` list (at the top
    level or under ``webcam``) whose entries use the same field names.
    Relative URLs resolve against the OctoPrint base. When only a
    snapshot URL is present, the classic derivation applies
    (``?action=snapshot`` -> ``?action=stream``); a snapshot URL with no
    ``action`` parameter yields a snapshot-only source.
    """
    single, entries = _octoprint_single_and_entries(payload)
    entry = None
    if entries:
        # OctoPrint entries use the same name/enabled conventions; reuse the picker.
        normalised = []
        for item in entries:
            copy = dict(item)
            if "enabled" not in copy and "webcamEnabled" in copy:
                copy["enabled"] = copy["webcamEnabled"]
            normalised.append(copy)
        entry = _pick_entry(normalised, preferred_name)
    elif single is not None:
        if single.get("webcamEnabled") is False or single.get("enabled") is False:
            entry = None
        else:
            entry = single
    if entry is not None:
        stream = _resolve_url(base_url, entry.get("streamUrl") or entry.get("stream_url"),
                               context="OctoPrint webcam")
        snapshot = _resolve_url(base_url, entry.get("snapshotUrl") or entry.get("snapshot_url"),
                                 context="OctoPrint webcam")
        if stream or snapshot:
            name = entry.get("name") if isinstance(entry.get("name"), str) else ""
            return _make_source(stream_url=stream, snapshot_url=snapshot, name=name)
    if fallback_snapshot_url:
        return derive_from_snapshot_url(fallback_snapshot_url)
    raise LiveStreamError(
        "OctoPrint's settings payload had no usable webcam and no fallback snapshot URL was provided")


def resolve_octoprint_camera_source(*args, **kwargs) -> CameraSource:
    """Alias for :func:`camera_source_from_octoprint`."""
    return camera_source_from_octoprint(*args, **kwargs)


# --------------------------------------------------------------------- encoder plan

@dataclass(frozen=True)
class EncoderProbe:
    """An injected ffmpeg/hardware probe result (no probing happens here)."""

    encoders: frozenset = frozenset()
    dri_present: bool = False
    nvidia_present: bool = False

    def __post_init__(self):
        object.__setattr__(self, "encoders", frozenset(self.encoders or ()))


@dataclass(frozen=True)
class EncoderCandidate:
    """One encoder choice: ffmpeg encoder name, vendor and target codec."""

    encoder: str
    vendor: str  # "vaapi" | "nvenc" | "qsv" | "cpu"
    codec: str   # "h264" | "vp8"
    hardware: bool = False

    @property
    def name(self) -> str:
        return self.encoder


# Default order per codec: (vendor, ffmpeg encoder name, device requirement).
# "dri" = requires dri_present, "nvidia" = requires nvidia_present,
# None = requires only the encoder name in the probed set.
_DEFAULT_ORDER = {
    "h264": (
        ("vaapi", "h264_vaapi", "dri"),
        ("nvenc", "h264_nvenc", "nvidia"),
        ("qsv", "h264_qsv", "dri"),
        ("cpu", "libx264", None),
    ),
    "vp8": (
        # NVENC has no VP8 encoder and QSV is not a VP8 target here: neither
        # is ever a VP8 candidate, whatever the probe or preference says.
        ("vaapi", "vp8_vaapi", "dri"),
        ("cpu", "libvpx", None),
    ),
}


def _coerce_probe(probe, dri_present, nvidia_present):
    """Normalise the accepted probe shapes into (encoders, dri, nvidia)."""
    if isinstance(probe, EncoderProbe):
        encoders = set(probe.encoders)
        dri = probe.dri_present if dri_present is None else dri_present
        nvidia = probe.nvidia_present if nvidia_present is None else nvidia_present
        return encoders, bool(dri), bool(nvidia)
    if isinstance(probe, dict):
        encoders = set(probe.get("encoders") or probe.get("available_encoders") or ())
        dri = probe.get("dri_present", False) if dri_present is None else dri_present
        nvidia = probe.get("nvidia_present", False) if nvidia_present is None else nvidia_present
        return encoders, bool(dri), bool(nvidia)
    if isinstance(probe, (set, frozenset, list, tuple)):
        encoders = set(probe)
        dri = ("h264_vaapi" in encoders or "vp8_vaapi" in encoders or "h264_qsv" in encoders) \
            if dri_present is None else dri_present
        nvidia = ("h264_nvenc" in encoders) if nvidia_present is None else nvidia_present
        return encoders, bool(dri), bool(nvidia)
    raise LiveStreamError("encoder probe must be an EncoderProbe, a mapping, or a set of encoder names")


def encoder_candidates(probe, *, dri_present=None, nvidia_present=None,
                       preference="auto", target_codec="h264", codec=None) -> tuple:
    """Ordered encoder candidates for `target_codec` from an injected probe.

    `probe` is an :class:`EncoderProbe`, a mapping with ``encoders`` /
    ``dri_present`` / ``nvidia_present``, or a bare set of ffmpeg encoder
    names (device presence then defaults from the hardware encoders in
    the set, unless `dri_present` / `nvidia_present` are passed). A given
    `preference` moves its vendor first when that candidate is available;
    an unavailable or codec-inapplicable preference (for example ``nvenc``
    for VP8) leaves the default order unchanged.
    """
    effective_codec = codec or target_codec
    if effective_codec not in TARGET_CODECS:
        raise LiveStreamError(f"unsupported target codec {effective_codec!r}; expected one of {TARGET_CODECS}")
    if preference not in ENCODER_PREFERENCES:
        raise LiveStreamError(
            f"unsupported encoder preference {preference!r}; expected one of {ENCODER_PREFERENCES}")
    encoders, dri, nvidia = _coerce_probe(probe, dri_present, nvidia_present)
    candidates = []
    for vendor, encoder_name, requirement in _DEFAULT_ORDER[effective_codec]:
        if encoder_name not in encoders:
            continue
        if requirement == "dri" and not dri:
            continue
        if requirement == "nvidia" and not nvidia:
            continue
        candidates.append(EncoderCandidate(encoder=encoder_name, vendor=vendor,
                                           codec=effective_codec, hardware=(vendor != "cpu")))
    if preference != "auto":
        for index, candidate in enumerate(candidates):
            if candidate.vendor == preference:
                if index:
                    candidates.insert(0, candidates.pop(index))
                break
    return tuple(candidates)


def plan_encoders(*args, **kwargs) -> tuple:
    """Alias for :func:`encoder_candidates`."""
    return encoder_candidates(*args, **kwargs)


_ENCODER_INFO = {
    "h264_vaapi": ("vaapi", "h264"),
    "vp8_vaapi": ("vaapi", "vp8"),
    "h264_nvenc": ("nvenc", "h264"),
    "h264_qsv": ("qsv", "h264"),
    "libx264": ("cpu", "h264"),
    "libvpx": ("cpu", "vp8"),
    "libvpx-vp8": ("cpu", "vp8"),
}


def _coerce_candidate(candidate, target_codec):
    if isinstance(candidate, EncoderCandidate):
        if target_codec is not None and target_codec != candidate.codec:
            raise LiveStreamError(
                f"encoder {candidate.encoder!r} is for codec {candidate.codec!r}, not {target_codec!r}")
        return candidate
    if isinstance(candidate, str) and candidate in _ENCODER_INFO:
        vendor, codec_name = _ENCODER_INFO[candidate]
        if target_codec is not None and target_codec != codec_name:
            raise LiveStreamError(
                f"encoder {candidate!r} is for codec {codec_name!r}, not {target_codec!r}")
        encoder_name = "libvpx" if candidate == "libvpx-vp8" else candidate
        return EncoderCandidate(encoder=encoder_name, vendor=vendor, codec=codec_name,
                                hardware=(vendor != "cpu"))
    raise LiveStreamError(f"unknown encoder candidate {candidate!r}")


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LiveStreamError(f"{name} must be a positive integer, got {value!r}")
    return value


def build_ffmpeg_args(candidate, *, input_url, target_codec=None, max_height=720,
                      fps=15, bitrate_kbps=2500, output="-") -> list:
    """Pure ffmpeg argv for one chosen encoder candidate.

    Scales to `max_height` keeping aspect (width ``-2``, so it stays even),
    caps at `fps` and `bitrate_kbps`, and encodes with the candidate's
    encoder. VAAPI candidates initialise ``-vaapi_device
    /dev/dri/renderD128`` before the input and use the
    ``format=nv12,hwupload`` tail on the scale filter (the analogous form
    for ``vp8_vaapi``); CPU H.264 uses ``libx264 -preset ultrafast`` and
    CPU VP8 uses ``libvpx -deadline realtime``.

    Output decision: the argv ends with exactly the caller-supplied
    `output` argument and adds no muxer, RTP or transport flags — the
    caller (a later transport stage) owns that target and its format.
    The input URL is placed in the argv verbatim because ffmpeg needs it;
    callers must not log the argv without redacting that element.
    """
    chosen = _coerce_candidate(candidate, target_codec)
    if target_codec is not None and target_codec not in TARGET_CODECS:
        raise LiveStreamError(f"unsupported target codec {target_codec!r}; expected one of {TARGET_CODECS}")
    if not isinstance(input_url, str) or not input_url.strip():
        raise LiveStreamError("an input URL is required to build ffmpeg arguments")
    if not isinstance(output, str) or not output.strip():
        raise LiveStreamError("an output target is required to build ffmpeg arguments")
    max_height = _positive_int(max_height, "max_height")
    fps = _positive_int(fps, "fps")
    bitrate_kbps = _positive_int(bitrate_kbps, "bitrate_kbps")

    argv = ["ffmpeg", "-hide_banner", "-nostdin"]
    if chosen.vendor == "vaapi":
        argv += ["-vaapi_device", VAAPI_DEVICE]
    argv += ["-i", input_url, "-an"]
    if chosen.vendor == "vaapi":
        video_filter = f"scale=-2:{max_height},format=nv12,hwupload"
    else:
        video_filter = f"scale=-2:{max_height}"
    argv += ["-vf", video_filter, "-r", str(fps),
             "-b:v", f"{bitrate_kbps}k", "-c:v", chosen.encoder]
    if chosen.encoder == "libx264":
        argv += ["-preset", "ultrafast"]
    elif chosen.encoder == "libvpx":
        argv += ["-deadline", "realtime"]
    argv.append(output)
    return argv


def build_ffmpeg_command(*args, **kwargs) -> list:
    """Alias for :func:`build_ffmpeg_args`."""
    return build_ffmpeg_args(*args, **kwargs)
