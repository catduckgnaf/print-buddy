# Guided setup and debugging in Discord

[Documentation home](README.md) · [Discord bot setup](DISCORD-BOT-SETUP.md) · [Standalone bot](STANDALONE.md)

Print Buddy has two guided Discord flows, available in both runtimes (the standalone bot and
the Hermes print-feedback plugin) to allowed users in the print channel:

| Command | What it does |
| --- | --- |
| `/print-buddy setup` | Start or resume guided setup, one small question at a time |
| `/print-buddy debugging` | Run read-only diagnostics and report redacted, actionable findings |
| `/print-buddy status` | Show the saved setup checklist |
| `/print-buddy cancel` | Pause setup; the saved checklist is kept |
| `/print-buddy help` | List these commands |

Typing the same text works, like the other commands. Neither flow prints, moves, heats, or
authorizes a printer, and neither flow can start one.

## Setup

Setup asks seven small steps, validating each answer before moving on:

1. **Printer model** — a model key from the printer registry (see
   [printer profiles](PRINTER-PROFILES.md)).
2. **Bot mode** — `standalone` or `hermes`.
3. **Print channel** — the numeric Discord channel ID.
4. **Allowed users** — numeric Discord user IDs, comma separated.
5. **Moonraker URL** (optional) — validated as a URL, and refused for printer models that
   have no Moonraker connection.
6. **Spoolman URL** (optional) — validated as a URL. Spoolman is printer-independent, so
   this step is offered for every model, including models with no Moonraker connection.
   The Spoolman included in the Docker stack (#214) is at `http://spoolman:8000`; an
   existing external Spoolman keeps its own URL, exactly as in the CLI setup wizard.
7. **Bot token stored securely** — this step never collects the token. It explains how to
   store it: as the environment variable named by `[discord] token_env` (default
   `DISCORD_BOT_TOKEN`) in the profile/data folder `.env` file with mode 600, as in the
   [Discord bot setup guide](DISCORD-BOT-SETUP.md). Reply `stored` when it is saved, or
   `skip` to do it later. Pasting a token into chat is rejected and never saved.

### Progress, cancellation, timeout, and recovery

- After each answer the bot replies with the next question and a checklist showing what is
  done, what is current, and what remains.
- The checklist is saved in the state folder (`guided-setup.json`, file mode 600) after
  every step. `/print-buddy cancel` pauses setup without losing it; a bot restart does not
  lose it either. `/print-buddy setup` resumes at the first unfinished step, and
  `/print-buddy setup restart` discards the saved answers and starts over.
- A session that has been idle for 24 hours is timed out: a plain reply after that is not
  treated as an answer. Run `/print-buddy setup` to resume the saved checklist.
- An invalid answer (a non-numeric ID, a bad URL, an unknown model key) is rejected with the
  reason and the same question is asked again; the step does not advance.

### The consent step

Reaching the end writes nothing. The review step summarizes the answers (IDs are not
repeated back) and offers three replies:

- `apply` — the explicit consent to write. Only then are the collected settings merged
  into `config/local.yaml` through the same merge the CLI setup wizard uses: values already
  in the file always win, and no secret is written (the flow collected none).
- `manual` — nothing is written; the bot returns precise manual steps naming the file,
  sections, and keys to set, where the token belongs, and the offline checks to run.
- `/print-buddy cancel` — leave setup unfinished and resume later.

Setup never installs software, restarts a service, or changes network exposure. Those stay
manual, deliberate actions from the install guides.

## Debugging

`/print-buddy debugging` runs these read-only checks and reports each as ok, warning,
failed, or skipped, with a concrete next step for anything that needs one:

- **Configuration** — the settings load and validate; the failing key is named when not.
- **Bot mode and login** — the configured mode; in standalone mode, whether the token
  environment variable is set, plus a read-only Discord login check (`GET /users/@me`).
  In Hermes mode this is skipped: the gateway owns the login.
- **Permissions** — the print channel ID and allowed user IDs are present and numeric, and
  the report lists the channel permissions the bot needs (View Channels, Send Messages,
  Send Messages in Threads, Embed Links, Attach Files, Read Message History). Channel
  overrides themselves are only visible to the logged-in bot; checking them is a listed
  manual next step when this check fails.
- **Service connectivity and health** — for each configured service (Moonraker, Spoolman,
  OctoPrint), one read-only GET against its health/version path. Unconfigured services are
  skipped, not failures.
- **Executables and versions** — the Python version, whether the configured slicer command
  exists and runs (`--version`), and whether ffmpeg is present when configured.
- **State and logs** — the state folder exists and is writable, whether a log file is
  configured and its folder exists, and the standalone bot heartbeat when one is present.

Debugging is read-only by default and in fact: its only network calls are the GET probes
above, it never calls a printer operation or a write endpoint, and it changes no settings.
Remediation that would edit configuration, install software, restart a service, or change
network exposure is never performed by the command — the report gives the manual next step
instead, and any such change needs your explicit go-ahead outside this flow.

### Redaction

Every line of the report is redacted before it is sent: token and password values are
removed, secret-shaped values and Discord-token-shaped strings are removed, private
filesystem paths are replaced with a placeholder, and long numeric identifiers (channel
and user IDs) are masked. Exact state/log paths therefore do not appear in Discord; run
`python3 -m print_buddy.bot check` locally when you need the exact path.

## How this relates to the CLI checks

- The optional [Web UI](WEBUI.md) is a third setup surface over the same YAML settings:
  its `/config` page renders the catalogued settings with their source layer, previews a
  change before writing, and applies the same settings validation. It does not replace
  this guided flow, and neither surface collects secret values.
- `python3 -m print_buddy.setup_wizard` is the full terminal installer wizard (printer
  registry menus, service installs with their own confirmations). The Discord setup flow
  covers initial configuration only and reuses the wizard's validation and config merge.
- `python3 -m print_buddy.bot check` validates the standalone bot offline.
- `python3 -m print_buddy.doctor` remains the machine-level check; unlike `/print-buddy
  debugging` it is a terminal command whose output is not redacted for Discord, and it can
  contact configured services — run it only where those contacts are authorized.
