# Firmware registry

Root-level index of firmware commands, macros and error codes for Print Buddy
(issue #169), read by `print_buddy/knowledge/` and surfaced through
`/print-lookup`. Entries are reference data: a lookup returns the text, it never
sends the command. Sending anything to a printer stays behind the existing
guarded print-control flows and their confirmation buttons.

## File

`commands.toml`, one `[[entry]]` per command, macro or error:

| Field | Meaning |
| --- | --- |
| `id` | Stable slug prefixed with the family: `zmod.`, `klipper.` or `marlin.`. |
| `name` | The command or macro name as the firmware knows it, or the error text. |
| `aliases` | Phrasings lookups should match (for example "ifs load"). |
| `firmware` | `zmod`, `klipper` or `marlin`. ZMod is listed separately from stock Klipper because the AD5X macro set and authority rules differ. |
| `kind` | `command`, `macro` or `error`. |
| `printers` | Registered printer model keys (see `../printers/registry.toml`) the entry is known to apply to, or `["*"]` for every printer on that firmware. |
| `command` | The literal command line, with `<placeholders>` for values. Empty for errors. |
| `description` | What it does, when to use it, and the traps. |
| `safety` | What it can do physically (heat, motion, extrusion, restart) and the guard that applies. |
| `notes` | Optional extra context. |

Only add an entry you can stand behind: prefer commands the repository already
uses or documents, and say where an entry is generic firmware knowledge rather
than verified on a Print Buddy printer. The loader validates the schema
(`print_buddy/knowledge/registry.py`) and the tests pin the ZMod, Klipper and
Marlin coverage the issue asks for.
