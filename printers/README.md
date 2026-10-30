# Printer registry

Root-level data index of the printers Print Handy knows about (issue #169).

The executable printer profiles stay where they are —
`print_handy/printers/<vendor>/<printer>.py`, one `MODEL` per file, discovered by
`print_handy/printers/__init__.py`. Moving that code would break every import,
config key and template path for no user benefit. This registry is the
discoverable front door to those profiles: hardware facts and firmware family in
one place, for lookups, troubleshooting and humans browsing the repository.

## File

`registry.toml`, one `[[printer]]` per registered model:

| Field | Meaning |
| --- | --- |
| `key` | The `vendor.printer` model key, identical to the profile's `MODEL.key` and the `[printer] model` config value. |
| `label` | Display name, identical to `MODEL.label`. |
| `vendor` | The vendor package name under `print_handy/printers/`. |
| `firmware` | The firmware string from the model's own defaults. |
| `firmware_family` | Lookup family in `../firmware/commands.toml`: `zmod`, `klipper`, `marlin`, or `none` when no command registry exists for it yet. |
| `connection` | How Print Handy reaches the printer (the vendor profile's connection). |
| `kinematics` | Motion system, or `unspecified` for the generic placeholder profiles. |
| `bed_mm`, `max_height_mm` | Usable print area and height from the model's defaults. |
| `filament_slots` | Independent filament paths the profile drives. |
| `tools` | Independent toolheads (a tool changer) when the model has them; toolhead models record `tools` instead of `filament_slots`. |
| `color_system` | The model's color architecture (issue #656): `single`, `multi_slot` (one extruder fed by several slots; `filament_slots` above 1), or `multi_tool` (independent toolheads; `tools` above 1). Identical to `MODEL.color_system`. Only the AD5X pair is `multi_slot` and only the Creator pair is `multi_tool`; everything else is `single`. |
| `profile` | Path of the profile module that is the source of truth. |
| `notes` | Quirks a troubleshooter should know before trusting the numbers. |

Tests (`tests/test_knowledge.py`) compare every entry with the registered
models — key, label, firmware, connection, bed, height and slots — so this file
fails CI instead of drifting when a profile changes. Adding a printer means
adding its profile module and its registry entry in the same change.
