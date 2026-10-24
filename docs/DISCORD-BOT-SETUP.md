# Discord bot setup

Print Buddy talks to you through a Discord bot you own. This takes about 5 minutes. The light installer
prints the same steps; skip this page if you already have a bot token.

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
answer, or neither.
