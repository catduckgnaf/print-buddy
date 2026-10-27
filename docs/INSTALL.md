# Install on a Hermes box

## 1. Clone

```sh
git clone https://github.com/<you>/print-buddy.git ~/print-buddy
cd ~/print-buddy
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
It also writes a `print_buddy.pth` into the Hermes venv's site-packages so `python -m print_buddy...`
works from any directory, and copies old `~/.print_bitch_*.json` (to the `print_buddy_*` names) and `~/.moonraker_discord_announcements.json`
state files into `<hermes home>/state/` when the new copy is missing. An old private `scripts/` folder in the
profile is moved aside. Anything replaced is moved to `<hermes home>/.install-backups/<time>/<path>` (units go under
`<systemd dir>/.install-backups/`), never next to the original, so Hermes cannot load a backup as a duplicate
plugin or skill. Rerunning is safe.

The listener unit is named `hermes-3dprinting-moonraker-listener.service`, the same as the private
setup used, so installing it replaces the old unit instead of running a second listener.

## 5. Check

```sh
python3 -m print_buddy.doctor
```

The doctor also checks the Hermes profile itself. If `platforms.discord.enabled` is `false` in
`<hermes home>/config.yaml`, the gateway never connects Discord — environment credentials do not
override an explicit platform disable — so attachment intake is silently absent while everything
else looks healthy. The doctor (and `python3 -m print_buddy.bot check`) report that as a named
failure with the fix: set it to `true` and restart the gateway. Print Buddy's template renders it
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
