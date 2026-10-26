# Printer macros

Macros are a Moonraker/Klipper feature: a macro is a named block in the
printer's own Klipper config, and Moonraker lists the ones a printer actually
defines. Print Buddy does not hard-code a per-model macro list — it asks the
printer.

## `/print-macros` — what your printer defines (Stage 1, read-only)

Run `/print-macros` in Discord, Telegram or Matrix. On a printer whose
connection is Moonraker, Print Buddy makes one read-only request —
`GET /printer/objects/list` — and lists every `gcode_macro <NAME>` the
printer reports, classified:

- **Known to Print Buddy** — the name matches a macro entry in the
  descriptive registry ([`firmware/commands.toml`](../firmware/commands.toml),
  the same registry `/print-lookup` searches). The listing shows the
  registry's description and safety note.
- **Defined by your printer's config** — the printer defines it but the
  registry does not describe it. Listed by name only; Print Buddy invents no
  description for a macro it has not verified.
- **Internal helper macros** — names starting with `_`, the Klipper helper
  convention. Listed separately and never presented as operator macros.

Stage 1 sends nothing to the printer beyond that one read request. It cannot
run a macro: running one is Stage 2 of
[issue #291](https://github.com/catduckgnaf/print-buddy/issues/291) and will
need its own confirmation design (a discovered name only, behind the usual
confirm button, never while a print is running). If Moonraker is unreachable
or answers something unreadable, the reply is "Could not read the printer's
macros" and nothing is sent.

On a printer whose connection is not Moonraker there is no macro namespace
to read, and `/print-macros` says so plainly instead of failing — see the
matrix below.

## The per-vendor macro matrix, as it actually is

| Printer | Connection | Macro situation |
| --- | --- | --- |
| Flashforge AD5X (ZMod) | Moonraker | ZMod macros in the printer's Klipper config: `START_PRINT` / `END_PRINT` own the job start and end, `CHANGE_ZCOLOR` syncs IFS slots to the native screen, `AUTO_FULL_BED_LEVEL` and `BED_LEVEL_SCREWS_TUNE` are the levelling helpers, and the IFS feed path is internal (`_`-prefixed). `/print-macros` discovers the live set; `/print-lookup` describes the registry-known ones. |
| Generic Klipper, Sovol SV06 | Moonraker | The printer's config is expected to provide `PRINT_START` / `PRINT_END`; Print Buddy's profiles emit those names and the installed macro owns heating, homing and mesh loading. Anything else the config defines is discovered live by `/print-macros`. |
| Elegoo Neptune 4 / Pro / Plus / Max | Moonraker | A Moonraker printer, so `/print-macros` works — but note the start sequence is **inline** in the sliced file, not a macro call. `PRINT_START` is a foreign marker on this family: Print Buddy's Elegoo guard refuses a file that calls it (see `print_buddy/printers/elegoo/guard.py`). A `PRINT_START` macro appearing in a Neptune's own config listing is the printer's business; Print Buddy never emits one into a Neptune job. |
| Bambu Lab (all models) | Bambu LAN | No Klipper macros at all. The printer runs plain G/M/T codes only; Klipper or ZMod macro lines are refused by the G-code guard before they can reach the hardware (see the note in `print_buddy/printers/base.py`). No macro namespace, so `/print-macros` explains instead of listing. |
| Prusa MK4S / CORE One / XL / MINI+ | PrusaLink | Buddy firmware, not Klipper. There is no Moonraker and no user macro namespace; start/end behaviour lives in the slicer profile's G-code. `/print-macros` explains instead of listing. |
| Elegoo Centauri Carbon | SDCP | No Moonraker and no macro namespace exposed over SDCP. `/print-macros` explains instead of listing. |
| Flashforge Adventurer 5X (stock) | Stock Flashforge | Stock firmware, plain G-code only — the same line-by-line guard posture as Bambu. The ZMod macro set exists only on a ZMod install (the AD5X row above). `/print-macros` explains instead of listing. |
| Marlin via OctoPrint | OctoPrint | Marlin has no Klipper-style macro namespace; start/end G-code lives in the slicer profile or OctoPrint settings. `/print-macros` explains instead of listing. |

## Where the knowledge lives

- The **printer** is the authority on which macros exist — that is what
  `/print-macros` reads, live.
- The **registry** (`firmware/commands.toml`) is the descriptive layer: it
  says what a known macro does and what to be careful about. It is advisory
  reference data, also used by `/print-lookup`, and an entry is never sent to
  a printer by the lookup, troubleshooting or macro-listing code.
- Registry entries are added only from verified firmware evidence (Stage 3
  of issue #291). An unverified name stays "defined by your printer's
  config" — present in the listing, without an invented description.

Nothing here claims live-hardware verification: discovery is tested offline
against recorded Moonraker response shapes, as with the Bambu, Prusa and
Elegoo LAN work.
