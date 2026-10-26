# Light install (Raspberry Pi or Debian/Ubuntu, no Docker)

One command installs Print Buddy natively and walks you through the setup.

```bash
curl -fsSL https://raw.githubusercontent.com/catduckgnaf/print-buddy/main/scripts/install-light.sh | bash
```

Pin a release with `bash -s -- --ref 2.1.3`. Read the script first if you prefer:
[scripts/install-light.sh](../scripts/install-light.sh).

## Requirements

- Raspberry Pi 4 or 5 (4 GB or more recommended for slicing) with **64-bit** Raspberry Pi OS (Bookworm or newer),
  or a 64-bit Debian or Ubuntu machine (arm64 or x86_64). 32-bit Pi OS is refused: the slicers have no 32-bit build.
- Python 3.11 or newer (Bookworm and Ubuntu 24.04 have it), `sudo` for apt, about 2 GB free for a slicer.
- A Discord bot: see [Discord bot setup](DISCORD-BOT-SETUP.md).
- Stock Flashforge IFS occupancy is read from `/detail` and is not verified on a live printer.

## What it does

1. Installs the missing apt packages: `python3-venv python3-pip flatpak xvfb git unzip curl`, and adds the Flathub remote.
2. Clones the code to `~/print-buddy` (change with `--dir`) and creates `~/print-buddy/.venv` with `requirements.txt`.
   Everything is pure Python or has arm64 wheels; nothing compiles.
3. Starts the setup wizard (`python -m print_buddy.setup_wizard`). It asks:
   1. **Printer:** brand, then model. Pick **Other / generic** for anything not listed, then the firmware
      (Klipper, Marlin with OctoPrint, or Bambu Lab) and the build volume.
   2. **Connection:** the Moonraker or OctoPrint address (Bambu Lab is offline only). If Klipper or OctoPrint is
      not installed yet, it offers the official installer (KIAUH, or OctoPrint in a venv) and runs it only after a yes.
   3. **Nozzle and filament:** nozzle size and material, main filament.
   4. **Slicer:** Bambu Lab printers use Bambu Studio, everything else OrcaSlicer, both from Flathub.
   5. **Spoolman:** skip, use an existing server, or run the official Spoolman installer on this machine.
   6. **Camera and timelapse:** the snapshot URL; timelapse videos need moonraker-timelapse on the printer.
   7. **Discord:** setup steps if you have no bot yet, the invite link, channel and user IDs, the token (hidden).
   8. **Hermes Agent:** if you use Hermes, it creates (or reuses) a profile, default `3dprinting`, and runs
      `scripts/install-hermes.sh` for it. Otherwise it installs the standalone bot as systemd user services.
4. Shows a summary and asks before changing anything.

## Safe to run again

- `config/local.yaml` is written only if missing. If it exists, the wizard shows a diff of the settings it would
  add, and your existing values always win.
- Secrets go only to the data folder's `.env` (mode 600). Existing values are kept. Nothing secret is printed.
- An existing Hermes profile is reused, never recreated. In Hermes mode the standalone services are not installed,
  because two bots on one token collide.

## Unattended install

Answer any question ahead of time with a file (YAML or `KEY=value`). Keys match the question keys in
`print_buddy/setup_wizard.py`; anything missing is asked, or takes the default with `--yes`.

```yaml
brand: sovol
model: sovol.sv06
moonraker_url: http://192.168.1.50:7125
nozzle_diameter_mm: "0.4"
material: PLA
spoolman: skip
camera: "no"
have_bot: "yes"
discord_chat_id: "123456789012345678"
discord_user_ids: "234567890123456789"
hermes: "no"
```

```bash
bash install-light.sh --answers answers.yaml --yes
```

Leave the token out of the file and add it to the `.env` afterwards, or answer `discord_bot_token` with
`PB_DISCORD_BOT_TOKEN` in the environment.

`--dry-run` asks every question and prints each command and the config it would write, without changing anything.

## After install

```bash
~/print-buddy/.venv/bin/python -m print_buddy.bot check     # standalone
systemctl --user status print-buddy-bot.service
```

In Hermes mode, run `hermes -p <profile> setup` to pick the model, then restart the gateway.

## Update and remove

- Update: run the same one-liner again. A checkout with local edits is left alone.
- Remove the services: `bash ~/print-buddy/scripts/install-light.sh --uninstall`
- Remove everything, including the code and data folder: add `--purge`. A Hermes profile is never deleted;
  the script prints the `hermes profile delete` command instead. Flatpak slicers stay installed.
