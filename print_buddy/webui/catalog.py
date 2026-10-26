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

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"field {self.section}.{self.key}: unknown kind {self.kind!r}")

    @property
    def id(self):
        return f"{self.section}.{self.key}"


def _field(section, key, label, kind, help, **kwargs):
    return Field(section, key, label, kind, help=help, **kwargs)


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
    # Camera watch.
    _field("visual_watch", "enabled", "Camera watch", "toggle",
           "Camera watchdog switch; the watchdog is alert-only and never controls the printer.",
           validator="settings visual_watch check"),
    _field("visual_watch", "sensitivity", "Camera watch sensitivity", "number",
           "Camera watchdog sensitivity, 1 (quietest) to 5 (most alerts).",
           validator="settings visual_watch check", minimum=1, maximum=5),
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
