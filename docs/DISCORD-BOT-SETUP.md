# Discord bot setup

Print Buddy talks to you through a Discord bot you own. Use this page for the standalone bot;
Hermes users can follow the Discord application steps, then use [Hermes installation](INSTALL.md).
Allow about 15 minutes after installing Print Buddy and its Python requirements. Start in the
repository root with the installation's Python environment activated. For installation itself,
use [light install](INSTALL-LIGHT.md) or [standalone bot](STANDALONE.md).

The [wiki setup entry](https://github.com/catduckgnaf/print-buddy/wiki/Discord-Bot-Setup)
links here: this versioned page is the authoritative guide.

## 1. Create the bot

1. Open https://discord.com/developers/applications and click **New Application**. Name it (for example "Print Buddy").
2. On **General Information**, copy the **Application ID**. You need it for the invite link.
3. Open **Bot**, click **Reset Token**, and copy the token. Treat it like a password: anyone with it controls the bot.
4. Still on **Bot**, under **Privileged Gateway Intents**, turn on **MESSAGE CONTENT**. Print Buddy reads
   the messages in its channel. It does not need the Server Members or Presence intents.

## 2. Invite it to your server

Replace `<APPLICATION_ID>` and open the link:

```
https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot+applications.commands&permissions=274878024704
```

The scopes are `bot` and `applications.commands` (slash commands). The permission number is exactly these,
nothing more:

| Permission | Why |
|---|---|
| View Channels | See the print channel |
| Send Messages | Replies and status |
| Send Messages in Threads | Replies inside print threads |
| Embed Links | Status cards |
| Attach Files | Previews, G-code and timelapse videos |
| Read Message History | Follow the conversation and approvals |

## 3. Copy the IDs

1. In Discord, open **User Settings > Advanced** and turn on **Developer Mode**.
2. Right-click the print channel and choose **Copy Channel ID**.
3. Right-click your own name and choose **Copy User ID**. Repeat for anyone else allowed to print.

## 4. Give them to Print Buddy

The light installer asks for the channel ID, the user IDs and the token. The token is typed hidden and saved
only to the data folder's `.env` file (mode 600); it is never printed or written to `config/local.yaml`.

Doing it by hand instead:

- Standalone: put `DISCORD_BOT_TOKEN=...` in `~/.local/share/print-buddy/.env` (or your `paths.hermes_home`),
  and set `discord.chat_id` and `discord.allowed_user_ids` in `config/local.yaml`. See [standalone bot](STANDALONE.md).
- Hermes: put `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS` and `DISCORD_HOME_CHANNEL` in
  `~/.hermes/profiles/<profile>/.env`. See [Hermes installation](INSTALL.md).

Use one bot token for one mode. Running the standalone bot and a Hermes profile on the same token makes both
answer, or neither. Stop the old owner before starting the new one; see [moving from Hermes](STANDALONE.md#moving-from-hermes).

### Standalone configuration

The installer creates the configuration. For a manual install, edit `config/local.yaml`:

```yaml
bot:
  mode: standalone
  sync_commands: true
  health_port: 0
paths:
  hermes_home: ~/.local/share/print-buddy
discord:
  chat_id: "123456789012345678"             # replace with your channel ID
  allowed_user_ids: "234567890123456789"    # replace with your user IDs
  token_env: DISCORD_BOT_TOKEN
```

These IDs are placeholders, not usable setup values. `paths.hermes_home` is the data directory;
its name is historical and does not require Hermes. Keep the printer-specific configuration
created by the installer. This example only shows the Discord fields.

Store the real token in that data directory's `.env` using a local editor, not a shell command
that leaves the token in history. Restrict access with `chmod 600 ~/.local/share/print-buddy/.env`.
Do not paste tokens into Discord, issue reports or screenshots. Reset an exposed token in the
Developer Portal and replace it locally. Never commit `.env` or `config/local.yaml`.

| Setting | Meaning |
|---|---|
| `discord.chat_id` | Only this channel and its threads are served |
| `discord.allowed_user_ids` | Numeric user IDs separated by commas or spaces; empty refuses everyone |
| `discord.approval_user_id` | Optional additional allowed user |
| `discord.token_env` | Environment variable name holding the secret, not the token itself |
| `discord.bot_name` | Name in replies; does not change the Discord account name |
| `bot.mode` | Set `standalone`; default is `hermes` |
| `bot.sync_commands` | Register slash commands at startup; default `true` |
| `bot.health_port` | Default `0`: no HTTP listener; leave disabled for this setup |
| `bot.health_stale_s` | Heartbeat freshness limit; default 120 seconds |

All settings support `PRINT_BUDDY__SECTION__KEY` process-environment overrides, for example
`PRINT_BUDDY__BOT__MODE=standalone` and
`PRINT_BUDDY__DISCORD__ALLOWED_USER_IDS="234567890123456789 345678901234567890"`.
The actual token still comes from the variable named by `token_env` (default `DISCORD_BOT_TOKEN`),
not a `discord.token` field. `PRINT_BUDDY_CONFIG` selects an explicit configuration file.
See [settings and optional LLM/logging fields](STANDALONE.md#settings) and
[configuration load order](CONFIGURATION-YAML.md). Leave `llm.chat_url` empty for command-list replies
with no LLM.

## 5. Verify offline before connecting

Run in the repository root using the Python environment from installation:

```bash
python3 -m print_buddy.bot check
```

This does not log into Discord or contact a printer. It checks mode, token presence (not validity),
channel, allowed users, discord.py, loaded handlers, absence of Hermes modules and writable state.
It creates the state directory and briefly writes a probe file there. Expect exit 0 and `ok` lines;
resolve each `FAIL` before proceeding. A valid configuration is not proof the token can log in.
Do not use `python3 -m print_buddy.doctor` as this offline check: doctor can contact configured services.

## 6. First launch and health

Once the offline check passes, deliberately connect the bot to Discord:

```bash
python3 -m print_buddy.bot run
```

Keep the printer listener stopped during this first check. As an allowed user in the configured
channel, send `/print-help` or plain `hello` with the optional LLM disabled. Expect the command list;
neither starts a print. Do not send model links, files or printer-control commands for verification.
A stranger or a message in another channel is ignored.

In a second terminal using the same environment and configuration:

```bash
python3 -m print_buddy.bot health
```

Expect exit 0 with `ok standalone bot: connected as ...`. This reads the local heartbeat and
process identity, not the printer. It checks a live, connected process and freshness, not printer
readiness. Stop a foreground bot with Ctrl+C. Do not run a second copy alongside a service.
For user services, `scripts/install-standalone.sh` renders units but enables nothing; review its
printed instructions in [standalone systemd setup](STANDALONE.md#systemd) before enabling services.

## Recovery

| Symptom | Safe next step |
|---|---|
| `check` reports mode, channel or allowed users FAIL | Correct the named YAML field or environment override; rerun `check`. IDs must be numeric, not names |
| Token missing or Discord refuses login | Check `token_env`, the data-directory `.env` and service environment; reset/re-enter a rejected token locally. Never include its value in logs or reports |
| Privileged intents error or typed messages ignored | Enable **Message Content Intent** on the Developer Portal's **Bot** page; restart the bot deliberately |
| Bot online but no replies / missing permissions | Confirm channel and user IDs, then check channel overrides for View Channel, Send Messages and Read Message History; check Attach Files/Embed Links for attachments |
| Slash commands absent | Confirm `applications.commands` invite scope and `bot.sync_commands: true`; inspect startup errors. Allow Discord time to propagate; typed `/print-help` can test routing meanwhile |
| Login/connectivity errors | Inspect local startup logs for DNS, TLS or Discord availability errors. Do not disable TLS checks or expose a new port; retry after resolving the reported cause |
| Health fails | Start with its reason: no heartbeat, stale heartbeat, disconnected, or replaced process. Check that both terminals/services use the same config and data directory |
| Duplicate replies | Stop the extra standalone process or Hermes gateway using that token. Keep exactly one owner |

Startup logs go to stderr by default; optional logging settings are in [standalone settings](STANDALONE.md#settings).
Review and redact logs locally before sharing: diagnostic output can contain paths, channel IDs and service URLs.
Setup/debugging slash-command wizards are not implemented; the supported checks here are CLI commands.
After a restart, intake questions held in memory must be restarted by resending the model; do not treat old
buttons as authorization. Listener alerts have separate persistent-button support.
