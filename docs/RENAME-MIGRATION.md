# Rename migration: Print Bitch to Print Buddy

Everything named after the old project name now uses Print Buddy. There are no aliases or fallbacks, so an existing install has to be migrated once.

## This machine

```sh
scripts/migrate-names.sh --dry-run   # show every action
scripts/migrate-names.sh
```

It renames `print_bitch*` files in the profile `state/` dir and the archive dir, and replaces `PRINT_BITCH_` env var names with `PRINT_BUDDY_` in `config/local.toml`, the profile `.env` and `config.yaml`, and the listener systemd unit and drop-ins (each edited file is kept as `<file>.pre-rename`). It is safe to run again. Then restart the listener:

```sh
systemctl --user daemon-reload
systemctl --user restart hermes-3dprinting-moonraker-listener.service
```

Renamed env vars: `PRINT_BITCH_CONTEXT_PATH`, `_START_CLAIMS`, `_START_MESSAGES`, `_ARCHIVE`, `_BOUNDS_CACHE`, `_NOTIFICATION_STATE` and `_CLEANUP_DRY_RUN` all become `PRINT_BUDDY_...`.

To keep the old bot name in Discord and in the roast persona, set `[discord] bot_name = "Print Bitch"` in `config/local.toml`, then re-render `SOUL.md` and `locales/en.yaml` (the installer only renders them when missing).

## Printer (AD5X)

Do this while the printer is idle. These steps run on the printer, so the script cannot do them.

1. Disable the old plugin: `DISABLE_PLUGIN name=print-bitch` (ZMod runs its `uninstall.sh`).
2. In `mod_data/user.moonraker.conf`, replace the `[update_manager print-bitch]` section with:
   ```ini
   [update_manager print-buddy]
   type: git_repo
   channel: dev
   path: /root/printer_data/config/mod_data/plugins/print-buddy
   origin: https://github.com/catduckgnaf/print-buddy.git
   is_system_service: False
   primary_branch: main
   managed_services: klipper
   ```
   Restart Moonraker so it clones the repo into `plugins/print-buddy`, then delete the old `plugins/print-bitch` folder.
3. Enable the new one: `ENABLE_PLUGIN name=print-buddy`.
4. In `mod_data/user.cfg`, rename `[gcode_macro _PRINT_BITCH_VARS]` to `[gcode_macro _PRINT_BUDDY_VARS]`. The values stay as they are.
5. Run `FIRMWARE_RESTART`, then `PRINT_BUDDY SLOT=1` to check the macro answers.

ZMod's external plugin list links this repo; if it registered the plugin as `print-bitch`, ask for the entry to become `print-buddy` so fresh installs get the new name.

The macro is now `PRINT_BUDDY`; update any gcode or slicer start macros that call `PRINT_BITCH`.

## Printer model setting

`[printer] family` is gone. `scripts/migrate-names.sh` rewrites it in `config/local.toml` (backup `local.toml.pre-model`). To do it by hand, replace it with `model = "flashforge.ad5x"` (or `sovol.sv06`, `klipper.generic`), or the import stops and names the key. Printer defaults now come from the model file under `print_buddy/printers/`. JOB.json files record `printer_model` instead of `printer_family`; a job without it is an AD5X job.
