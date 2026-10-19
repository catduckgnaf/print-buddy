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

1. Disable the old plugin: `DISABLE_PLUGIN name=print-bitch`. ZMod runs the plugin's `uninstall.sh` and removes the plugin directory. If your ZMod has no such command, delete `mod_data/plugins/print-bitch` by hand.
2. Enable the new one: `ENABLE_PLUGIN name=print-buddy`. `install.sh` prints the reminder to copy the slot values.
3. In `mod_data/user.cfg`, rename `[gcode_macro _PRINT_BITCH_VARS]` to `[gcode_macro _PRINT_BUDDY_VARS]`. The values stay as they are.
4. In `moonraker.conf`, replace `[update_manager print-bitch]` with `[update_manager print-buddy]` and set `path: /root/printer_data/config/mod_data/plugins/print-buddy`.
5. Run `FIRMWARE_RESTART`, then `PRINT_BUDDY SLOT=1` to check the macro answers.

The macro is now `PRINT_BUDDY`; update any gcode or slicer start macros that call `PRINT_BITCH`.
