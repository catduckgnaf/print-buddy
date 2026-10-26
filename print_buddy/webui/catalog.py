"""The Web UI field catalog (#286, stage 1): one declarative entry per editable setting.

Every entry names a real ``[section] key`` the settings loader already
validates. The catalog is the single list a later stage renders as pickers,
so the Discord guided setup (``print_buddy/bot/guided.py``), the CLI setup
wizard and the Web UI cannot drift apart: the guided-setup fields are all
here, printer-model choices come from the printer registry, platform
choices from ``print_buddy.bot.platform``, and slicer/delivery choices
from the configured printer's vendor profile.

No secret ever appears here. A secret *value* is never a setting, and no
``*_env`` key (which only names the environment variable holding a secret)
is editable through the catalog either.

Per-printer fields are deliberately absent (#337, stage 2e decision): the
catalog addresses global fields only in v1 — a ``[[printers]]`` roster is
declared in the config file or through the setup surfaces, and the status
page shows it read-only. Per-printer catalog addressing is a future stage's
decision, not this one's; see docs/WEBUI.md.

Settings are read once at process start (``settings.current()`` is
cached), so every field is honestly marked ``restart_required``.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import printers, settings

# The kinds a later stage knows how to render.
KINDS = ("picker", "toggle", "number", "text", "url", "host", "id_list")

# Choices sources resolved by choices_for(): named, so a catalog entry
# stays declarative and new printer models appear without UI code changes.
SOURCE_PRINTER_REGISTRY = "printer_registry"
SOURCE_BOT_PLATFORMS = "bot_platforms"
SOURCE_VENDOR_SLICERS = "vendor_slicers"
SOURCE_VENDOR_DELIVERY = "vendor_delivery"
SOURCE_TIMEZONES = "timezones"


@dataclass(frozen=True)
class Field:
    """One editable setting, described for a picker UI."""

    section: str
    key: str
    label: str
    kind: str
    help: str = ""
    choices: tuple = ()
    choices_source: str | None = None
    validator: str = "settings.validate"
    restart_required: bool = True
    minimum: float | None = None
    maximum: float | None = None
    # The /config page group (stage 3); every field is in exactly one,
    # assigned from GROUP_OF below so the page order stays declarative.
    group: str = ""

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"field {self.section}.{self.key}: unknown kind {self.kind!r}")

    @property
    def id(self):
        return f"{self.section}.{self.key}"


# Page groups for the stage 3 /config page, keyed by field id. The page
# renders them in this order: printer, platform, services, timelapse,
# images, live, slicing, logging, webui (pages.GROUPS carries the titles).
GROUP_OF = {
    "printer.model": "printer",
    "printer.slicer": "slicing",
    "delivery.methods": "slicing",
    "bot.mode": "platform",
    "bot.platform": "platform",
    "discord.chat_id": "platform",
    "discord.allowed_user_ids": "platform",
    "discord.approval_user_id": "platform",
    "discord.timezone": "platform",
    "telegram.chat_id": "platform",
    "telegram.allowed_user_ids": "platform",
    "telegram.approval_user_id": "platform",
    "matrix.homeserver_url": "platform",
    "matrix.room_id": "platform",
    "matrix.allowed_user_ids": "platform",
    "matrix.approval_user_id": "platform",
    "services.moonraker_url": "services",
    "services.spoolman_url": "services",
    "services.camera_source": "images",
    "services.camera_snapshot_url": "images",
    "services.vision_chat_url": "images",
    "vision.model": "images",
    "vision.roast_model": "images",
    "vision.roast_enabled": "images",
    "visual_watch.enabled": "images",
    "visual_watch.sensitivity": "images",
    "timelapse.mode": "timelapse",
    "timelapse.render_wait_s": "timelapse",
    "timelapse.render_poll_s": "timelapse",
    "timelapse.max_bytes": "timelapse",
    "timelapse.local_retention_days": "timelapse",
    "timelapse.plan_clip_retention_days": "timelapse",
    "timelapse.archive_host": "timelapse",
    "timelapse.archive_dir": "timelapse",
    "timelapse.ssh_key": "timelapse",
    "logging.level": "logging",
    "logging.format": "logging",
    "webui.enabled": "webui",
    "webui.host": "webui",
    "webui.port": "webui",
    "live_stream.enabled": "live",
    "live_stream.voice_channel_id": "live",
    "live_stream.auto_start_on_print": "live",
    "live_stream.max_height": "live",
    "live_stream.fps": "live",
    "live_stream.max_bitrate_kbps": "live",
    "live_stream.encoder": "live",
    "live_stream.empty_timeout_s": "live",
    "live_stream.activity_origin": "live",
    "live_stream.port": "live",
}


def _field(section, key, label, kind, help, **kwargs):
    return Field(section, key, label, kind, help=help,
                 group=GROUP_OF[f"{section}.{key}"], **kwargs)


CATALOG = (
    # Printer (guided setup: model, plus the vendor-offered slicer/delivery sets).
    _field("printer", "model", "Printer model", "picker",
           "The printer model key; sets every model default for that printer.",
           choices_source=SOURCE_PRINTER_REGISTRY, validator="guided model / settings model check"),
    _field("printer", "slicer", "Slicer", "picker",
           "Slicer for this printer; only the ones its vendor profile offers.",
           choices_source=SOURCE_VENDOR_SLICERS, validator="settings vendor choices"),
    _field("delivery", "methods", "Delivery methods", "picker",
           "Post-slice options offered, as a list; only the ones the printer's vendor profile offers.",
           choices_source=SOURCE_VENDOR_DELIVERY, validator="settings vendor choices"),
    # Bot and chat platform (guided setup: mode, plus bot platform from #164).
    _field("bot", "mode", "Bot mode", "picker",
           "standalone runs Print Buddy's own bot; hermes runs it as a Hermes Agent profile.",
           choices=tuple(settings.BOT_MODES), validator="guided mode / settings bot check"),
    _field("bot", "platform", "Bot platform", "picker",
           "Chat platform the standalone bot talks to.",
           choices_source=SOURCE_BOT_PLATFORMS, validator="settings bot platform check"),
    _field("discord", "chat_id", "Discord print channel", "text",
           "Numeric ID of the print channel (Developer Mode > Copy Channel ID).",
           validator="guided chat ID"),
    _field("discord", "allowed_user_ids", "Discord allowed users", "id_list",
           "Numeric Discord user IDs allowed to use Print Buddy, separated by commas or spaces.",
           validator="guided user IDs / settings.user_ids"),
    _field("discord", "approval_user_id", "Discord approval user", "text",
           "Numeric Discord user ID allowed to approve prints; always allowed.",
           validator="settings approval user check"),
    _field("discord", "timezone", "Timezone", "picker",
           "IANA timezone name used for display and the daily reset.",
           choices_source=SOURCE_TIMEZONES),
    _field("telegram", "chat_id", "Telegram chat", "text",
           "Telegram chat (group) ID; group and channel IDs are negative.",
           validator="settings telegram check"),
    _field("telegram", "allowed_user_ids", "Telegram allowed users", "id_list",
           "Telegram user IDs allowed to use the standalone bot, separated by commas or spaces.",
           validator="settings.user_ids (telegram)"),
    _field("telegram", "approval_user_id", "Telegram approval user", "text",
           "Telegram user ID allowed to approve prints; always allowed.",
           validator="settings telegram check"),
    _field("matrix", "homeserver_url", "Matrix homeserver URL", "url",
           "Matrix homeserver base URL, for example https://matrix.org.",
           validator="settings matrix check"),
    _field("matrix", "room_id", "Matrix room", "text",
           "Matrix room ID of the print room (starts with '!'); the room must be unencrypted.",
           validator="settings matrix check"),
    _field("matrix", "allowed_user_ids", "Matrix allowed users", "id_list",
           "Matrix user IDs allowed to use the standalone bot, full @user:server form, "
           "separated by commas or spaces.",
           validator="settings.matrix_user_ids"),
    _field("matrix", "approval_user_id", "Matrix approval user", "text",
           "Matrix user ID allowed to approve prints, full @user:server form; always allowed.",
           validator="settings matrix check"),
    # Services (guided setup: Moonraker and Spoolman URLs).
    _field("services", "moonraker_url", "Moonraker URL", "url",
           "Klipper/Moonraker HTTP URL, for example http://printer.local:7125; empty if this "
           "printer has no Moonraker connection.",
           validator="guided service URL / settings services check"),
    _field("services", "spoolman_url", "Spoolman URL", "url",
           "Spoolman URL for filament inventory; empty when Spoolman is not used.",
           validator="guided Spoolman URL / settings services check"),
    # Images (the camera source type, the snapshot URL and the vision
    # endpoint the watchdog uses; visual_watch itself is the next group.
    # API keys stay in the environment: vision_chat_url names no secret,
    # and there is no key field.)
    _field("services", "camera_source", "Camera source", "picker",
           "Which camera still images come from (#294): auto follows the configured "
           "printer vendor's rule, or pin one source — the Moonraker webcam snapshot, "
           "the Bambu camera (LAN stills / RTSPS via go2rtc), a go2rtc stream — "
           "or none for no camera images.",
           choices=tuple(settings.CAMERA_SOURCES), validator="settings camera source check"),
    _field("services", "camera_snapshot_url", "Camera snapshot URL", "url",
           "Camera snapshot URL for status images and the camera watchdog; empty derives "
           "it from the Moonraker host.",
           validator="settings services check"),
    _field("services", "vision_chat_url", "Vision chat URL", "url",
           "OpenAI-compatible chat endpoint used for camera checks; empty disables them. "
           "Its API key stays in the environment, never here.",
           validator="settings services check"),
    _field("vision", "model", "Vision model", "text",
           "Model the vision endpoint uses for camera checks."),
    _field("vision", "roast_model", "Roast model", "text",
           "Model the vision endpoint uses for the one-line roast on print posts."),
    _field("vision", "roast_enabled", "Roast", "toggle",
           "The one-line roast on print-started and print-complete posts, on every "
           "platform (Telegram included). On by default: it runs whenever an "
           "LLM/vision endpoint is available; off turns roasts off without "
           "disabling camera checks.",
           validator="settings vision check"),
    # Camera watch.
    _field("visual_watch", "enabled", "Camera watch", "toggle",
           "Camera watchdog switch; the watchdog is alert-only and never controls the printer.",
           validator="settings visual_watch check"),
    _field("visual_watch", "sensitivity", "Camera watch sensitivity", "number",
           "Camera watchdog sensitivity, 1 (quietest) to 5 (most alerts).",
           validator="settings visual_watch check", minimum=1, maximum=5),
    # Timelapse (the mode type picker, render waiting, size cap, retention,
    # and the SSH archive target). ssh_key is a filesystem *path* — the
    # same plain string the YAML already stores — never key contents, so
    # it is a text field like any other path and no secret value is involved.
    _field("timelapse", "mode", "Timelapse mode", "picker",
           "How timelapses are made (#246/#295): rendered = the printer renders it "
           "(moonraker-timelapse); container = Print Buddy captures and encodes it "
           "in-container; off = no timelapses. A file value left empty derives "
           "rendered when a Moonraker URL is configured, else off.",
           choices=tuple(settings.TIMELAPSE_MODES), validator="settings timelapse check"),
    _field("timelapse", "render_wait_s", "Timelapse render wait", "number",
           "How long to wait for a printer-rendered timelapse to appear after a print "
           "finishes, in seconds.",
           validator="settings type check", minimum=1),
    _field("timelapse", "render_poll_s", "Timelapse render poll", "number",
           "How often to check for the rendered timelapse while waiting, in seconds.",
           validator="settings type check", minimum=1),
    _field("timelapse", "max_bytes", "Timelapse max size", "number",
           "Largest timelapse file kept or sent, in bytes.",
           validator="settings type check", minimum=1),
    _field("timelapse", "local_retention_days", "Timelapse local retention", "number",
           "Days a rendered timelapse is kept locally before cleanup.",
           validator="settings type check", minimum=0),
    _field("timelapse", "plan_clip_retention_days", "Plan clip retention", "number",
           "Days an unfinished plan's timelapse clip store is kept before cleanup.",
           validator="settings type check", minimum=0),
    _field("timelapse", "archive_host", "Timelapse archive host", "host",
           "SSH host finished timelapses are copied to for archiving; empty turns archiving off.",
           validator="settings type check"),
    _field("timelapse", "archive_dir", "Timelapse archive directory", "text",
           "Directory on the archive host that receives timelapse files.",
           validator="settings type check"),
    _field("timelapse", "ssh_key", "Timelapse archive SSH key path", "text",
           "Filesystem path of the SSH private key for the archive host; only the path "
           "is stored here, never the key contents.",
           validator="settings type check"),
    # Logging.
    _field("logging", "level", "Log level", "picker",
           "Log verbosity.",
           choices=tuple(settings.LOG_LEVELS)),
    _field("logging", "format", "Log format", "picker",
           "text is one readable line per event; json is one JSON object per line.",
           choices=tuple(settings.LOG_FORMATS)),
    # The Web UI itself. access_token_env is deliberately not editable here:
    # no *_env key is in the catalog (see the module docstring).
    _field("webui", "enabled", "Web UI", "toggle",
           "Optional Web UI switch; off by default, and nothing listens while disabled.",
           validator="settings webui check"),
    _field("webui", "host", "Web UI host", "host",
           "Host the Web UI binds to when enabled; a plain IP address or hostname.",
           validator="settings webui check"),
    _field("webui", "port", "Web UI port", "number",
           "Port the Web UI binds to when enabled; 0 means no port has been chosen yet.",
           validator="settings webui check", minimum=0, maximum=65535),
    # Live camera in Discord (#311): the [live_stream] section. No secret
    # is a field here — the Discord client secret and the Activity
    # session secret live only in the environment, and the tunnel token
    # belongs to the cloudflared sidecar; this group carries exactly the
    # settings the loader validates.
    _field("live_stream", "enabled", "Live camera in Discord", "toggle",
           "Live camera viewing in Discord (#311) switch; off by default, and "
           "/print-live only reports that while disabled.",
           validator="settings live_stream check"),
    _field("live_stream", "voice_channel_id", "Live voice channel", "text",
           "Numeric ID of the one private Discord voice channel the live "
           "Activity is launched in; the bot never names another channel.",
           validator="settings live_stream check"),
    _field("live_stream", "auto_start_on_print", "Auto-start on print", "toggle",
           "Start the live view automatically when a print starts and post "
           "the Activity pointer; off by default — /print-live start is the "
           "manual trigger. The session still ends itself after the empty "
           "timeout below.",
           validator="settings live_stream check"),
    _field("live_stream", "max_height", "Live feed height", "number",
           "Live feed height cap in pixels; width follows the camera's aspect.",
           validator="settings live_stream check", minimum=144, maximum=2160),
    _field("live_stream", "fps", "Live feed frame rate", "number",
           "Live feed frame-rate cap, in frames per second.",
           validator="settings live_stream check", minimum=1, maximum=60),
    _field("live_stream", "max_bitrate_kbps", "Live feed bitrate cap", "number",
           "Live feed bitrate cap in kbit/s.",
           validator="settings live_stream check", minimum=100, maximum=20000),
    _field("live_stream", "encoder", "Live feed encoder", "picker",
           "Encoder preference for the live feed (the plan in "
           "print_buddy/live_stream.py).",
           choices=tuple(settings.LIVE_STREAM_ENCODERS),
           validator="settings live_stream check"),
    _field("live_stream", "empty_timeout_s", "Live empty timeout", "number",
           "Seconds the live view may stay empty of viewers before the "
           "session ends itself.",
           validator="settings live_stream check", minimum=1),
    _field("live_stream", "activity_origin", "Live Activity origin", "url",
           "Public https origin the Discord Activity page is served from: "
           "the named Cloudflare Tunnel hostname mapped in the Developer "
           "Portal (see docs/DISCORD-BOT-SETUP.md).",
           validator="settings live_stream check"),
    _field("live_stream", "port", "Live Activity port", "number",
           "Loopback port the supervised Activity server binds inside the "
           "deployment; 0 means no port has been chosen yet, so the server "
           "does not start.",
           validator="settings live_stream check", minimum=0, maximum=65535),
)

_FIELDS = {field.id: field for field in CATALOG}


def field_by_id(field_id):
    """The catalog field for ``"section.key"`` (or a ``(section, key)`` pair), else None."""
    if isinstance(field_id, Field):
        return field_id
    if isinstance(field_id, tuple):
        field_id = f"{field_id[0]}.{field_id[1]}"
    return _FIELDS.get(str(field_id))


def choices_for(field, *, model_key=None, data=None):
    """The current choices for a picker field, resolved from its choices source.

    Vendor sources need the configured printer model: pass ``model_key``
    or a loaded settings mapping as ``data``.
    """
    field = field_by_id(field)
    if field is None:
        raise ValueError(f"unknown catalog field {field!r}")
    if field.choices_source is None:
        return tuple(field.choices)
    if field.choices_source == SOURCE_PRINTER_REGISTRY:
        return tuple(sorted(printers.MODELS))
    if field.choices_source == SOURCE_BOT_PLATFORMS:
        from ..bot.platform import KNOWN_PLATFORMS
        return tuple(KNOWN_PLATFORMS)
    if field.choices_source == SOURCE_TIMEZONES:
        from zoneinfo import available_timezones
        return tuple(sorted(available_timezones()))
    if field.choices_source in (SOURCE_VENDOR_SLICERS, SOURCE_VENDOR_DELIVERY):
        if model_key is None and data is not None:
            model_key = (data.get("printer") or {}).get("model")
        if not model_key:
            raise ValueError(f"{field.id}: choices need the configured printer model")
        vendor = printers.MODELS[settings._model_key(model_key)].vendor
        return tuple(vendor.slicers if field.choices_source == SOURCE_VENDOR_SLICERS
                     else vendor.delivery)
    raise ValueError(f"{field.id}: unknown choices source {field.choices_source!r}")  # pragma: no cover
