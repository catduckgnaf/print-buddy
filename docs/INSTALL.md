# Install on a Hermes box

> **New installs default to the standalone bot** (#524): `bot.mode` defaults to `standalone`, and the
> shipped config templates say so. Start with [docs/STANDALONE.md](STANDALONE.md) and
> `scripts/install-standalone.sh` unless you specifically want Print Handy hosted inside a Hermes
> profile. This page remains the install path for that explicit choice — `bot.mode: hermes` is still
> supported — and the migration notes at the bottom are for installs moving off it.

## 1. Clone

```sh
git clone https://github.com/<you>/print-handy.git ~/print-handy
cd ~/print-handy
python3 -m pip install -r requirements-test.txt
```

Needs Python 3.11+, Hermes (`~/.hermes/hermes-agent`), and OrcaSlicer as a Flatpak.
Stock Flashforge IFS occupancy is read from `/detail` and is not verified on a live printer.

## 2. Settings: YAML preferred, TOML supported during migration

Defaults live in `config/home.yaml`. Put machine-specific overrides in the gitignored `config/local.yaml`; existing `config/home.toml` and `config/local.toml` files remain supported. YAML takes precedence when both formats are present. See [the configuration guide](CONFIGURATION-YAML.md) for precedence, validation and migration details.

- `services.moonraker_url` and `services.spoolman_url`
- `paths.hermes_home`, `archive`, `records_vault`, `cache` and `hermes_bin`
- `printer.model` and supported printer-specific overrides

## 3. Overlay: `config/overlay/` (gitignored)

Your private profile files. Each is copied over the profile at the same relative path:
`SOUL.md`, `MEMORY.md`, `config.yaml`, `.env`, and `systemd/<unit>.service.d/*.conf`.
Without an overlay you get the generic templates in `hermes/profile/`.
Fill template values from the environment on first install:
`LLM_PROVIDER LLM_MODEL LLM_BASE_URL TIMEZONE DISCORD_CHANNEL_ID DISPLAY_NAME`.

## 4. Install

```sh
scripts/install-hermes.sh --dry-run   # show what would happen
scripts/install-hermes.sh
systemctl --user enable --now hermes-3dprinting-moonraker-listener.service
```

Options: `--hermes-home DIR`, `--python PATH`, env `SYSTEMD_USER_DIR`.
It symlinks the skills, `print-feedback` plugin and docs into the profile, renders templates only
where the target is missing, applies the overlay, and installs the systemd user units.
It also writes a `print_handy.pth` into the Hermes venv's site-packages so `python -m print_handy...`
works from any directory, and copies old `~/.print_bitch_*.json` (to the `print_handy_*` names) and `~/.moonraker_discord_announcements.json`
state files into `<hermes home>/state/` when the new copy is missing. An old private `scripts/` folder in the
profile is moved aside. Anything replaced is moved to `<hermes home>/.install-backups/<time>/<path>` (units go under
`<systemd dir>/.install-backups/`), never next to the original, so Hermes cannot load a backup as a duplicate
plugin or skill. Rerunning is safe.

The listener unit is named `hermes-3dprinting-moonraker-listener.service`, the same as the private
setup used, so installing it replaces the old unit instead of running a second listener.

## 5. Check

```sh
python3 -m print_handy.doctor
```

The doctor also checks the Hermes profile itself. If `platforms.discord.enabled` is `false` in
`<hermes home>/config.yaml`, the gateway never connects Discord — environment credentials do not
override an explicit platform disable — so attachment intake is silently absent while everything
else looks healthy. The doctor (and `python3 -m print_handy.bot check`) report that as a named
failure with the fix: set it to `true` and restart the gateway. Print Handy's template renders it
`true` and the installer never rewrites an existing profile config, so a `false` there always
comes from outside the installer: a private overlay `config.yaml`, a hand edit, or Hermes-side
tooling.

## 6. Update

```sh
scripts/home-update.sh          # fast-forward, run checks, roll back on failure
```

Code is symlinked, so the pull is the update. Template changes do not touch files you already have.
To restart the listener after an update, put `systemctl --user restart hermes-3dprinting-moonraker-listener.service`
in `config/after-update.sh`.

## Optional external plugins

Not shipped here. Install them yourself if you want them: `openviking` (memory), `image_gen`.

## Migration notes: the default mode is now standalone (#524)

The `bot.mode` default flipped from `hermes` to `standalone`. Almost nothing changes by itself:
existing configs state `mode: hermes` **explicitly** (the templates always shipped the line), so an
explicit config keeps resolving to Hermes exactly as before — the flip only bites fresh installs and
configs that omit the line. If you move an install to standalone deliberately, do these in order
(the full checklist is [docs/STANDALONE.md](STANDALONE.md#moving-from-hermes)):

1. **One token, one connection:** stop the Hermes gateway's Discord platform (or remove the print
   channel from it) *before* starting the standalone bot. Two live connections on one bot token
   answer twice and race the button flows; the doctor's shared-token check
   (`python3 -m print_handy.bot check`) detects it, but stopping the gateway first is the control.
2. **Keep the agent (optional):** set `[agent] chat_url` (plus `api_key_env`) pointing at Hermes'
   API to keep stray-chat agent answers. Without it, stray chat gets the bounded `[llm]` call if one
   is configured, else the short reply. Set `[discord] chat_llm_enabled` explicitly if you had an
   opinion about chat answers.
3. **Design model moves:** if you used the profile's `auxiliary.print_design` pin, set `[design]
   model` (or `[llm]`) to the same model — the HTTP values are the normal path now.
4. **Session resets become Hermes' own:** the bot's post-print session reset/archive is retired in
   every mode; the profile's `session_reset: daily, at_hour 4` (already in the shipped template) is
   the remaining behaviour.
