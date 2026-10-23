"""Discord delivery for the standalone bot: the two calls the handlers make, plus the user check.

``send`` and ``send_clarify`` have the signatures of Hermes' Discord adapter, so the print-feedback
handlers run unchanged. A ``MEDIA:/path`` marker becomes an attachment. A button press resolves the
core prompt registry (print_buddy.core.prompts); the click handler lives here too.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..core import prompts
from . import rest

logger = logging.getLogger(__name__)

CUSTOM_PREFIX = "pbq:"
MAX_BUTTONS = 25
LABEL_LIMIT = 80


@dataclass
class SendResult:
    success: bool
    message_id: str | None = None
    error: str | None = None


def custom_id(clarify_id, index):
    return f"{CUSTOM_PREFIX}{clarify_id}:{index}"


def parse_custom_id(value):
    """(clarify_id, index) for a prompt button, else None."""
    value = str(value or "")
    if not value.startswith(CUSTOM_PREFIX):
        return None
    cid, _, index = value[len(CUSTOM_PREFIX):].rpartition(":")
    if not cid or not index.isdigit():
        return None
    return cid, int(index)


class StandaloneAdapter:
    """Sends through a discord.py client. ``allowed`` holds the Discord user IDs that may act."""

    def __init__(self, client, allowed, *, registry=prompts):
        self.client = client
        self.allowed = {str(u) for u in allowed}
        self.registry = registry
        self._prompts: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ who may act

    def is_allowed_id(self, user_id):
        return str(user_id or "") in self.allowed

    def _is_allowed_user(self, uid, user=None, guild=None, channel_ids=None):
        """The check the listener alert buttons call (same name as the Hermes adapter's)."""
        if getattr(user, "bot", False):
            return False
        return self.is_allowed_id(uid)

    # ------------------------------------------------------------------ delivery

    async def _channel(self, chat_id, metadata=None):
        target = (metadata or {}).get("thread_id") or chat_id
        channel = self.client.get_channel(int(target))
        if channel is None:
            channel = await self.client.fetch_channel(int(target))
        return channel

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        import discord
        body, paths = rest.split_media(content)
        pieces = rest.chunks(body)
        first = None
        opened = []
        try:
            channel = await self._channel(chat_id, metadata)
            for index, piece in enumerate(pieces):
                kwargs = {"allowed_mentions": discord.AllowedMentions.none()}
                if index == 0 and reply_to and str(reply_to).isdigit():
                    kwargs["reference"] = discord.MessageReference(
                        message_id=int(reply_to), channel_id=channel.id, fail_if_not_exists=False)
                if index == len(pieces) - 1 and paths:
                    opened = [discord.File(str(path)) for path in paths]
                    kwargs["files"] = opened
                sent = await channel.send(piece or None, **kwargs)
                first = first or sent
        except Exception as exc:
            logger.warning("Discord send failed: %r", exc)
            return SendResult(False, error=str(exc))
        finally:
            for handle in opened:
                handle.close()
        return SendResult(True, message_id=str(first.id) if first is not None else None)

    async def send_clarify(self, chat_id, question, choices, clarify_id, session_key, metadata=None):
        """One message with one button per choice. A press resolves ``clarify_id`` in the registry."""
        import discord
        labels = [str(c) for c in choices][:MAX_BUTTONS]
        pieces = rest.chunks(question)
        try:
            channel = await self._channel(chat_id, metadata)
            for piece in pieces[:-1]:
                await channel.send(piece, allowed_mentions=discord.AllowedMentions.none())
            view = discord.ui.View(timeout=None)
            for index, label in enumerate(labels):
                style = (discord.ButtonStyle.secondary if _is_cancel(label)
                         else discord.ButtonStyle.primary)
                view.add_item(discord.ui.Button(label=label[:LABEL_LIMIT], style=style,
                                                custom_id=custom_id(clarify_id, index)))
            message = await channel.send(pieces[-1], view=view, allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:
            logger.warning("Discord button question failed: %r", exc)
            return SendResult(False, error=str(exc))
        self._prompts[str(clarify_id)] = {"message": message, "choices": labels, "question": pieces[-1]}
        self._forget_closed()
        return SendResult(True, message_id=str(message.id))

    def _forget_closed(self):
        for cid in [c for c in self._prompts if not self.registry.is_open(c)]:
            self._prompts.pop(cid, None)

    # ------------------------------------------------------------------ answers

    def open_prompt(self, session_key):
        """The newest open button question asked under ``session_key``, else None."""
        # The registry key is the live chat session (who asked, where); send_clarify's key names the flow.
        hits = [cid for cid in self._prompts if self.registry.session_key(cid) == str(session_key)]
        return hits[-1] if hits else None

    async def answer_typed(self, session_key, text):
        """A typed reply to the open question of this session (Hermes routes these the same way)."""
        cid = self.open_prompt(session_key)
        if cid is None or not self.registry.resolve_gateway_clarify(cid, str(text)):
            return False
        await self._close_buttons(cid, f"Answered by message: {str(text)[:100]}")
        return True

    async def _close_buttons(self, cid, note):
        row = self._prompts.pop(str(cid), None)
        if not row:
            return
        try:
            await row["message"].edit(content=f"{row['question']}\n> {note}"[:rest.LIMIT], view=None)
        except Exception:
            logger.debug("could not strip answered buttons", exc_info=True)

    async def handle_click(self, interaction):
        """Resolve a prompt button. Returns False when the interaction is not one of ours."""
        data = getattr(interaction, "data", None) or {}
        parsed = parse_custom_id(data.get("custom_id"))
        if parsed is None:
            return False
        cid, index = parsed
        user = getattr(interaction, "user", None)
        if not self._is_allowed_user(str(getattr(user, "id", "")), user):
            await interaction.response.send_message("Not allowed. Nothing changed.", ephemeral=True)
            return True
        row = self._prompts.get(cid)
        labels = row["choices"] if row else (self.registry.choices(cid) or [])
        if not 0 <= index < len(labels) or not self.registry.resolve_gateway_clarify(cid, labels[index]):
            await interaction.response.send_message("That question already closed. Nothing changed.",
                                                    ephemeral=True)
            return True
        who = getattr(user, "display_name", None) or getattr(user, "name", None) or "Someone"
        question = row["question"] if row else str(getattr(getattr(interaction, "message", None), "content", "") or "")
        self._prompts.pop(cid, None)
        try:
            await interaction.response.edit_message(
                content=f"{question}\n> {who} chose **{labels[index]}**"[:rest.LIMIT], view=None)
        except Exception:
            logger.debug("could not acknowledge prompt click", exc_info=True)
        return True


def _is_cancel(label):
    low = label.casefold()
    return any(word in low for word in ("cancel", "don't", "keep", "skip", "not "))
