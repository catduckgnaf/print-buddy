# Install on a Hermes box

## 1. Clone

```sh
git clone https://github.com/<you>/print-buddy.git ~/print-buddy
cd ~/print-buddy
python3 -m pip install -r requirements-test.txt
```

Needs Python 3.11+, Hermes (`~/.hermes/hermes-agent`), and OrcaSlicer as a Flatpak.

## 2. Settings: `config/local.toml` (gitignored)

Defaults live in `config/home.toml`. Override only what differs:

- `[services]` `moonraker_url`, `spoolman_url`
- `[paths]` `hermes_home`, `archive`, `records_vault`, `cache`, `hermes_bin`
- `[printer]` anything that is not an AD5X with a 0.4 mm nozzle

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
Anything replaced is moved to `<name>.bak-<time>`. Rerunning is safe.

The listener unit is named `hermes-3dprinting-moonraker-listener.service`, the same as the private
setup used, so installing it replaces the old unit instead of running a second listener.

## 5. Check

```sh
python3 -m print_buddy.doctor
```

## 6. Update

```sh
scripts/home-update.sh          # fast-forward, run checks, roll back on failure
```

Code is symlinked, so the pull is the update. Template changes do not touch files you already have.
To restart the listener after an update, put `systemctl --user restart hermes-3dprinting-moonraker-listener.service`
in `config/after-update.sh`.

## Optional external plugins

Not shipped here. Install them yourself if you want them: `openviking` (memory), `image_gen`.
