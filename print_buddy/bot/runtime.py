"""The standalone bot's message flow, independent of any chat client so tests can drive it.

A message from a user the platform's access policy allows in the print channel, on whichever platform
``[bot] platform`` names, becomes the same event the Hermes
gateway hands the plugin: ``source`` (who and where), ``text``, ``media_urls`` (dropped model files,
saved locally) and ``message_id``. The router runs the plugin's handlers on it. What no handler takes
answers an open button question of the same person, or else gets the optional LLM or the command list.
A user a list refuses is never dropped silently (#386): the refusal is logged at INFO with the reason
and answered in channel once per user per hour.

The core talks to the chat service only through the platform interface in
``print_buddy.bot.platform``; the Discord entry point passes exactly the
values it always used, so Discord sessions, sources and replies are unchanged.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from .. import settings
from ..core import prompts
from ..hermes import _config
from . import commands, llm, platform, routing
from .router import Router

logger = logging.getLogger(__name__)

PROFILE = "3dprinting"  # the plugin's handlers only answer events of the print profile
# A refused user hears why at most once per period (#386): often enough that
# a household member who was never told about a list learns it exists, never
# often enough to spam the channel while they keep posting.
REFUSAL_NOTICE_PERIOD_S = 3600
REFUSAL_NOTICE = "You are not on this bot's allowed list."
MODEL_FILE_EXTS = {".3mf", ".stl"}
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
# The intake copies a dropped file into the job archive, so the cached upload is only needed briefly.
UPLOAD_KEEP_S = 7 * 24 * 3600
HELP_WORDS = {"/print-help", "/help", "help"}


def listed_users(cfg, section="discord"):
    """The raw allow list of a platform's settings section, without the approver."""
    if section == "matrix":  # Matrix IDs are @user:server strings, not numbers (#164 stage 3)
        return settings.matrix_user_ids(cfg[section].get("allowed_user_ids"))
    return settings.user_ids(cfg[section].get("allowed_user_ids"))


def allowed_users(cfg, section="discord"):
    """Allowed user IDs from a platform's settings section, plus its approver."""
    ids = listed_users(cfg, section)
    approver = str(cfg[section].get("approval_user_id") or "").strip()
    if approver and approver not in ids:
        ids.append(approver)
    return ids


def denied_users(cfg, section="discord"):
    """The opt-in deny list of a platform's settings section (#386)."""
    if section == "matrix":
        return settings.matrix_user_ids(cfg[section].get("denied_user_ids"))
    return settings.user_ids(cfg[section].get("denied_user_ids"), key="denied_user_ids")


def platform_name_of(source):
    """The platform name a source came from ('discord' for sources that do not say)."""
    value = getattr(getattr(source, "platform", None), "value", None) or getattr(source, "platform", None)
    return str(value or "discord")


def session_key(source):
    """One live session per person per channel or thread, like the gateway's group sessions."""
    return f"{platform_name_of(source)}:{source.chat_id}:{source.thread_id or ''}:{source.user_id}"


def make_source(user_id, chat_id, thread_id=None, is_bot=False, platform_name="discord",
                printer_id=None):
    # printer_id is the roster printer this source's channel routes to (#335);
    # None means the configured single/default printer, as before routing existed.
    return SimpleNamespace(platform=SimpleNamespace(value=str(platform_name)), profile=PROFILE,
                           user_id=str(user_id),
                           chat_id=str(chat_id), thread_id=str(thread_id) if thread_id else None,
                           is_bot=bool(is_bot), profile_route_rejected=False,
                           printer_id=str(printer_id) if printer_id else None)


def make_event(source, text, message_id, media_urls=(), metadata=None):
    return SimpleNamespace(source=source, text=str(text or ""), media_urls=list(media_urls),
                           message_id=str(message_id), metadata=dict(metadata or {}), internal=False)


def channel_scope(channel):
    """(chat_id, thread_id) for a channel or a thread in one."""
    parent = getattr(channel, "parent_id", None)
    if parent:
        return str(parent), str(channel.id)
    return str(getattr(channel, "id", "")), None


def safe_name(name):
    name = Path(str(name or "model")).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "model"


class Gateway:
    """The gateway calls the handlers make: may this person act, where do replies go, which session.

    Channel scope is the routing map (#335): a source is in scope when its
    chat is one a roster printer claims. With no roster map (a config that
    carries no [[printers]] list) the legacy single-chat check applies.
    """

    def __init__(self, adapter, chat_id, channel_printers=None):
        self.adapter = adapter
        self.chat_id = str(chat_id)
        self.channel_printers = dict(channel_printers or {})

    def _is_user_authorized_for_source(self, source):
        chat = str(getattr(source, "chat_id", ""))
        routed = chat in self.channel_printers if self.channel_printers else chat == self.chat_id
        return routed and self.adapter.is_allowed_id(getattr(source, "user_id", None))

    def printer_id_for(self, source):
        """The roster printer a source's channel routes to (#335), else None (the default printer)."""
        pid = self.channel_printers.get(str(getattr(source, "chat_id", "")))
        if pid:
            return pid
        pid = getattr(source, "printer_id", None)
        return str(pid) if pid else None

    def _delivery_adapter_for(self, source):
        return self.adapter

    def _session_key_for_source(self, source):
        return session_key(source)


class BotCore:
    def __init__(self, client, cfg=None, *, router=None, llm_opener=None, platform_name=None,
                 adapter=None, chat_id=None, use_llm=None):
        """Run the handlers against one platform adapter.

        With no ``adapter`` the adapter is built for ``platform_name`` (or
        ``[bot] platform``, default Discord) from that platform's settings
        section — for Discord exactly the values used before the interface
        existed. Tests and later platform stages pass their own adapter
        implementing ``print_buddy.bot.platform``; the core then never
        touches a platform library.
        """
        self.cfg = cfg if cfg is not None else _config.cfg()
        prompts.activate()  # our buttons resolve the core registry, even if Hermes is importable
        self.client = client
        self.platform_name = str(platform_name or (self.cfg.get("bot") or {}).get("platform")
                                 or getattr(adapter, "name", None) or "discord")
        section = self.cfg.get(self.platform_name) if isinstance(self.cfg.get(self.platform_name), dict) else {}
        discord = self.cfg.get("discord") or {}
        if adapter is not None:
            self.adapter = adapter
        else:
            module = platform.platform_module(self.platform_name)
            if module is None:
                raise ValueError(f"platform {self.platform_name!r} is not implemented yet (#164)")
            access_section = self.platform_name if section else "discord"
            # The adapter gets the raw list and the approver separately:
            # the access mode latches on the list alone, so setting only
            # an approval user does not opt into a whitelist (#386).
            self.adapter = module.StandaloneAdapter(
                client, listed_users(self.cfg, access_section),
                denied=denied_users(self.cfg, access_section),
                approver=str(section.get("approval_user_id") or "").strip() or None,
                upload_max_bytes=section.get("upload_max_bytes") or discord.get("upload_max_bytes"))
        self.chat_id = str(chat_id if chat_id is not None
                           else section.get("chat_id") or (discord.get("chat_id") if not section else "")
                           or "")
        # The channel → printer map (#335): built once at startup; a
        # duplicate claim raises RoutingError here, before anything is served.
        self.channel_printers = routing.channel_map(self.cfg, self.platform_name)
        self.gateway = Gateway(self.adapter, self.chat_id, self.channel_printers)
        self.router = router if router is not None else Router()
        self.router.attach_platform(self.platform_name, client, self.adapter)
        if client is not None and hasattr(client, "add_listener") and hasattr(self.adapter, "handle_click"):
            client.add_listener(self.on_interaction, "on_interaction")
        self.upload_dir = Path(self.cfg["paths"]["cache"]) / f"{self.platform_name}-uploads"
        # Pure-bot platforms (the adapter reports uses_llm=False, Telegram in
        # #164 stage 2) never reach the LLM fallback, even when [llm] is
        # configured: their unmatched text gets the command list only (#73).
        self.use_llm = bool(getattr(self.adapter, "uses_llm", True)) if use_llm is None else bool(use_llm)
        self.llm_opener = llm_opener
        self._refusal_notices: dict[str, float] = {}  # user_id -> last notice time (#386)
        self.bot_name = str(section.get("bot_name") or discord.get("bot_name") or "").strip() or "Print Buddy"
        self.help = commands.help_text(self.bot_name)
        self.started_at = time.time()

    # ------------------------------------------------------------------ routing

    def printer_for_chat(self, chat_id):
        """(routed, printer_id) for one chat. Unrouted chats are dropped silently (#335).

        With a roster map, a chat routes exactly when a printer claims it and
        the id is that printer's. Without one (no roster in the config) the
        legacy single chat routes, to the configured single printer (None).
        """
        chat_id = str(chat_id)
        if self.channel_printers:
            pid = self.channel_printers.get(chat_id)
            return pid is not None, pid
        if self.chat_id and chat_id == self.chat_id:
            return True, None
        return False, None

    # ------------------------------------------------------------------ messages

    async def handle_message(self, message):
        author = getattr(message, "author", None)
        me = getattr(getattr(self.client, "user", None), "id", None)
        if author is None or getattr(author, "bot", False) or (me is not None and author.id == me):
            return None
        chat_id, thread_id = channel_scope(message.channel)
        routed, printer_id = self.printer_for_chat(chat_id)
        if not routed:
            return None
        source = make_source(author.id, chat_id, thread_id, platform_name=self.platform_name,
                             printer_id=printer_id)
        if not self.gateway._is_user_authorized_for_source(source):
            # In the print channel but refused by an access list: never
            # silent (#386) — an INFO log naming the user and the reason,
            # plus one throttled in-channel notice.
            await self._note_refusal(source)
            return None
        media = await self.save_attachments(message)
        event = make_event(source, getattr(message, "content", ""), message.id, media)
        return await self.process(event)

    async def _note_refusal(self, source):
        """Log a list refusal at INFO and tell the channel, once per user per period (#386)."""
        reason = self.adapter.refusal_reason(source.user_id)
        if reason is None:
            return  # authorized after all (a race with a config reload); nothing to note
        logger.info("ignoring message from %s user %s in channel %s: %s",
                    self.platform_name, source.user_id, source.chat_id, reason)
        now = time.time()
        last = self._refusal_notices.get(str(source.user_id), 0.0)
        if now - last < REFUSAL_NOTICE_PERIOD_S:
            return
        self._refusal_notices[str(source.user_id)] = now
        metadata = {"thread_id": source.thread_id} if source.thread_id else None
        await self.adapter.send(chat_id=source.chat_id, content=REFUSAL_NOTICE, metadata=metadata)

    async def process(self, event, *, allow_llm=True):
        source = event.source
        metadata = {"thread_id": source.thread_id} if source.thread_id else None
        text = event.text.strip()
        if text.casefold() in HELP_WORDS:
            await self.adapter.send(chat_id=source.chat_id, content=self.help, metadata=metadata)
            return {"action": "skip", "reason": "help"}
        result = await self.router.dispatch(event, self.gateway)
        if result is not None:
            if result.get("action") == "rewrite":
                # A rewrite hands the rest to an agent. There is none here: say so, start nothing.
                await self.adapter.send(chat_id=source.chat_id, metadata=metadata,
                                        content="That needs the chat agent, which is not running. Nothing started.")
            return result
        if text and await self.adapter.answer_typed(session_key(source), text):
            return {"action": "skip", "reason": "typed answer to an open question"}
        if not text:
            return None
        return await self.fallback(event, allow_llm=allow_llm)

    async def fallback(self, event, *, allow_llm=True):
        """No handler took it. With an LLM: a worded reply and maybe one allowed command. Else the help."""
        source = event.source
        metadata = {"thread_id": source.thread_id} if source.thread_id else None
        if allow_llm and self.use_llm and llm.configured(self.cfg):
            try:
                reply, command = await asyncio.to_thread(llm.ask, event.text, self.help, cfg=self.cfg,
                                                         opener=self.llm_opener)
            except Exception as exc:
                logger.warning("LLM reply failed, sending the command list: %r", exc)
            else:
                if reply:
                    await self.adapter.send(chat_id=source.chat_id, content=reply, reply_to=event.message_id,
                                            metadata=metadata)
                if command:
                    routed = make_event(source, command, f"{event.message_id}:llm", metadata={"llm_command": True})
                    return await self.process(routed, allow_llm=False)
                if reply:
                    return {"action": "skip", "reason": "llm reply"}
        await self.adapter.send(chat_id=source.chat_id, content=self.help, reply_to=event.message_id,
                                metadata=metadata)
        return {"action": "skip", "reason": "command list"}

    def prune_uploads(self, now=None):
        now = time.time() if now is None else now
        for old in self.upload_dir.glob("doc_*"):
            try:
                if now - old.stat().st_mtime > UPLOAD_KEEP_S:
                    old.unlink()
            except OSError:
                pass

    async def save_attachments(self, message):
        """Save dropped .3mf/.stl files where the intake reads them. Other files are ignored."""
        self.prune_uploads()
        paths = []
        for attachment in getattr(message, "attachments", None) or []:
            name = safe_name(getattr(attachment, "filename", ""))
            if Path(name).suffix.lower() not in MODEL_FILE_EXTS:
                continue
            if int(getattr(attachment, "size", 0) or 0) > MAX_UPLOAD_BYTES:
                logger.warning("skipping %s: larger than %d bytes", name, MAX_UPLOAD_BYTES)
                continue
            self.upload_dir.mkdir(parents=True, exist_ok=True)
            # doc_<12 hex>_ is the gateway cache prefix; the intake strips it for the job title.
            target = self.upload_dir / f"doc_{uuid.uuid4().hex[:12]}_{name}"
            await attachment.save(target)
            paths.append(str(target))
        return paths

    # ------------------------------------------------------------------ interactions

    async def on_interaction(self, interaction):
        await self.adapter.handle_click(interaction)

    async def run_slash(self, interaction, name, values):
        """A slash command runs as its typed text, after the same channel and user checks."""
        user = interaction.user
        chat_id, thread_id = channel_scope(interaction.channel)
        routed, printer_id = self.printer_for_chat(chat_id)
        source = make_source(user.id, chat_id, thread_id, getattr(user, "bot", False),
                             platform_name=self.platform_name, printer_id=printer_id)
        if not routed:
            await interaction.response.send_message(f"{self.bot_name} only works in its print channel.", ephemeral=True)
            return None
        if not self.gateway._is_user_authorized_for_source(source):
            logger.info("refused slash command from %s user %s in channel %s: %s",
                        self.platform_name, source.user_id, source.chat_id,
                        self.adapter.refusal_reason(source.user_id))
            await interaction.response.send_message("Not allowed. Nothing changed.", ephemeral=True)
            return None
        text = commands.as_text(name, values)
        await interaction.response.send_message(f"`{text}`")
        return await self.process(make_event(source, text, interaction.id), allow_llm=False)

    # ------------------------------------------------------------------ status

    def _listener_statuses(self):
        """Per-printer listener health (#336), aggregated over the roster.

        Diagnostics only: a failure to compute it reads as an empty map,
        never as a status() failure — the heartbeat must keep beating.
        """
        try:
            from .. import healthcheck

            return healthcheck.listener_statuses(self.cfg)
        except Exception:
            return {}

    def status(self, connected):
        from . import health
        user = getattr(self.client, "user", None)
        return {"mode": "standalone", "pid": os.getpid(), "started_at": self.started_at,
                "platform": self.platform_name,
                "heartbeat_at": time.time(), "connected": bool(connected),
                "user": str(user) if user else None, "chat_id": self.chat_id,
                "channel_printers": dict(self.channel_printers),
                "listeners": self._listener_statuses(),
                "allowed_users": len(self.adapter.allowed),
                "access": self.adapter.access_description(),
                "handlers": len(self.router.dispatch_hooks),
                "llm": bool(self.use_llm and llm.configured(self.cfg)), "open_prompts": prompts.open_count(),
                "hermes_modules": health.hermes_modules_loaded()}
