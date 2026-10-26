# Telegram bot setup

Print Buddy can run its standalone bot on Telegram instead of Discord
(#164). The same handlers, prompts and safety gates serve both platforms;
only the transport changes. The Telegram bot is a **pure bot: it has no
LLM**. Unmatched text gets the command list, and no `[llm]` setting is
ever consulted for Telegram — that is deliberate, and it is how the
no-LLM standalone mode from the standalone design is being proven first.

The bot talks to the Telegram Bot API by long polling, so it needs no
inbound port, no public URL and no webhook. It uses only the Python
standard library; there is no Telegram package to install.

## 1. Create the bot with BotFather

1. In Telegram, open [@BotFather](https://t.me/BotFather) and send `/newbot`.
2. Pick a display name and a username ending in `bot`.
3. BotFather replies with the bot token (it looks like
   `123456789:AA...`). Keep it secret: anyone with the token controls the
   bot. If it ever leaks, revoke it with `/revoke` in BotFather.
4. Optionally send `/setcommands` to BotFather and paste the commands from
   `print_buddy/bot/commands.py` (names use underscores, e.g.
   `print_next`). The bot also registers its command menu itself at
   startup, best-effort, and typed commands work either way.

## 2. Create the print chat and find the IDs

1. Create a Telegram group for printing and add the bot to it. A private
   one-to-one chat with the bot works too.
2. **Chat ID**: send a message in the group, then read it back from
   `https://api.telegram.org/bot<token>/getUpdates` — the `chat.id` of the
   message is the chat ID. Group and supergroup IDs are **negative**
   (for example `-1001234567890`); a one-to-one chat ID is your own
   positive user ID. Tools like @userinfobot can also show it.
3. **Your user ID**: message [@userinfobot](https://t.me/userinfobot), or
   read `from.id` in the same `getUpdates` output. User IDs are positive
   numbers. Collect the ID of every person who may print, plus the
   approver's.

Forum groups (topics enabled) work: the bot scopes each topic like a
Discord thread, so a prompt opened in one topic is answered in that
topic.

## 3. Configure Print Buddy

```yaml
# config/local.yaml
bot:
  mode: standalone
  platform: telegram
telegram:
  chat_id: "-1001234567890"
  allowed_user_ids: "424242, 515151"
  approval_user_id: "424242"
services:
  moonraker_url: http://192.168.1.10:7125
```

Put the token in the environment variable `[telegram] token_env` names
(`TELEGRAM_BOT_TOKEN` by default) — in the process environment or in the
`.env` file in `paths.hermes_home`, mode 600. Never put the token in a
config file. Every setting can also come from the environment, for
example `PRINT_BUDDY__TELEGRAM__CHAT_ID=-1001234567890`.

Nobody allowed means nobody can use the bot: with no allowed users every
message is ignored and `check` fails.

## 4. Check and run

```bash
export TELEGRAM_BOT_TOKEN=...   # or put it in the data folder's .env
python3 -m print_buddy.bot check   # offline: mode, token present, chat, allowed users, handlers, no Hermes
python3 -m print_buddy.bot         # start polling
```

Printer event posts (started, complete, failed, timelapse) come from the
listener, unchanged: in standalone mode with `platform: telegram` it
posts through the Telegram Bot API instead of Discord REST.

## How Telegram differs from Discord here

- **Buttons**: prompts are inline keyboards. Answering edits the message
  to remove the keyboard and record the choice.
- **Alert buttons**: the listener's Discord button posts (pause alerts,
  plate picker, insertion and spool questions) are sent as plain text on
  Telegram. The text names the typed command or reply that does the same
  job; nothing is lost except the tap target.
- **Messages are plain text.** No Markdown parse mode is set, so file
  names, model names and G-code fragments are shown exactly as written
  (Discord's `**bold**` markers appear literally).
- **Limits**: 4096 characters per message (long replies are split),
  files up to 50 MB through the Bot API. Model files (.3mf/.stl) arrive
  as documents; previews and timelapses are sent back as photos/videos
  when Telegram has a native type for them, everything else as a
  document.
- **Commands** arrive as text: `/print-next plan-1`. A trailing
  `@YourBot` suffix that group chats add is stripped automatically.
