"""Channel → printer routing for the standalone bot (#335, design §2.3).

One bot serves every configured printer. Each roster entry claims one chat
on the platform the bot runs: the entry's own ``chat_id`` when it sets one,
else the platform's home chat (``[discord] chat_id``, ``[telegram] chat_id``
or ``[matrix] room_id``) — the fallback the config model already validates
for Discord in ``settings._check_chat_claims``. A message or interaction in
a claimed chat is handled for that chat's printer; a chat nobody claimed is
dropped silently, exactly as a foreign channel is dropped today.

Two entries claiming one chat is a startup error, never a silent choice:
an approval button carries no typed target, so the channel *is* the target
and a shared channel would make approvals ambiguous. Settings refuse the
Discord case at load; this module re-checks per platform at bot startup so
a Telegram or Matrix home chat colliding with an entry's claim also fails
loudly instead of misrouting a print approval.
"""
from __future__ import annotations


class RoutingError(ValueError):
    """The roster's channel claims cannot route safely; the bot must not start."""


def home_chat_id(cfg, platform_name):
    """The platform's global chat: where the default printer is reached when its entry sets no chat_id."""
    if not isinstance(cfg, dict):
        return ""
    if platform_name == "matrix":
        return str((cfg.get("matrix") or {}).get("room_id") or "")
    section = cfg.get(platform_name)
    if not isinstance(section, dict):
        return ""
    return str(section.get("chat_id") or "")


def roster(cfg):
    """The [[printers]] entries of a settings-shaped dict (empty when it carries none)."""
    if not isinstance(cfg, dict):
        return []
    raw = cfg.get("printers")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict) and entry.get("id")]


def channel_map(cfg, platform_name):
    """{chat_id: printer_id} for one platform. {} when the config names no roster.

    An entry with no claimable chat (no chat_id of its own and no platform
    home chat configured) is simply unreachable by chat and claims nothing.
    """
    entries = roster(cfg)
    if not entries:
        return {}
    home = home_chat_id(cfg, platform_name)
    claims: dict[str, str] = {}
    for entry in entries:
        claim = str(entry.get("chat_id") or "") or home
        if not claim:
            continue
        other = claims.get(claim)
        if other is not None:
            raise RoutingError(
                f"printers {other!r} and {entry['id']!r} both claim {platform_name} chat {claim}: "
                "give each printer its own chat_id — a channel is one printer's approval channel "
                "(design §2.3)")
        claims[claim] = str(entry["id"])
    return claims


def printer_for_chat(cfg, platform_name, chat_id):
    """The roster printer id a chat routes to, or None when the chat is unmapped."""
    return channel_map(cfg, platform_name).get(str(chat_id))


def chat_for_printer(cfg, platform_name, printer_id):
    """The chat a printer is reached in on this platform, or None when it claims none."""
    for chat, pid in channel_map(cfg, platform_name).items():
        if pid == str(printer_id):
            return chat
    return None


def default_printer_id(cfg):
    """The roster's first entry id (the default printer), or None without a roster."""
    entries = roster(cfg)
    return str(entries[0]["id"]) if entries else None


def printer_name(cfg, printer_id):
    """An entry's display name for user-facing text; the id itself when unknown."""
    for entry in roster(cfg):
        if str(entry["id"]) == str(printer_id):
            return str(entry.get("name") or entry["id"])
    return str(printer_id)
