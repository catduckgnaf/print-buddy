# Printer macros

Macros are a Moonraker/Klipper feature: a macro is a named block in the
printer's own Klipper config, and Moonraker lists the ones a printer actually
defines. Print Handy does not hard-code a per-model macro list — it asks the
printer.

## `/print-macros` — what your printer defines (Stage 1, read-only)

Run `/print-macros` in Discord, Telegram or Matrix. On a printer whose
connection is Moonraker, Print Handy makes one read-only request —
`GET /printer/objects/list` — and lists every `gcode_macro <NAME>` the
printer reports, classified:

- **Known to Print Handy** — the name matches a macro entry in the
  descriptive registry ([`firmware/commands.toml`](../firmware/commands.toml),
  the same registry `/print-lookup` searches). The listing shows the
  registry's description and safety note.
- **Defined by your printer's config** — the printer defines it but the
  registry does not describe it. Listed by name only; Print Handy invents no
  description for a macro it has not verified.
- **Internal helper macros** — names starting with `_`, the Klipper helper
  convention. Listed separately, never presented as operator macros, and
  never runnable from the bot (Stage 2 included).

The listing sends nothing to the printer beyond that one read request. If
Moonraker is unreachable or answers something unreadable, the reply is
"Could not read the printer's macros" and nothing is sent.

On a printer whose connection is not Moonraker there is no macro namespace
to read, and `/print-macros` says so plainly instead of failing — see the
matrix below.

## `/print-macros run <name> [KEY=VALUE ...]` — run one, guarded (Stage 2)

```
/print-macros run START_PRINT BED_TEMP=60 EXTRUDER_TEMP=210
```

Running a macro is deliberately narrow:

- **Discovered names only.** The set of macros is read live from the
  printer again at run time, and the typed name must match one of those
  names (case-insensitively, Klipper's own convention). A name the printer
  does not define is refused — Print Handy never sends a typed name on
  trust, and there is no way to type free G-code here. Internal
  (`_`-prefixed) macros are refused even though they are discovered.
- **Arguments are `KEY=VALUE` words only** — one word each, letters, digits
  and `. _ + -` in the value, no spaces, quotes or other symbols, no key
  twice. Anything else refuses the run before any prompt appears.
- **The confirmation shows the exact line.** Before anything is sent, the
  confirm prompt displays the single script line exactly as it will be
  posted, plus the registry safety note for a known macro — or, for a
  printer-defined macro, the explicit statement that it is defined by the
  printer's own config and is not described by Print Handy. Only the usual
  confirm button runs it; declining or letting the prompt time out sends
  nothing.
- **Never while printing.** The printer's `print_stats` state is checked
  before the prompt and again immediately before sending. Printing, paused,
  an unrecognised state, or an unreadable state at either check refuses the
  run and sends nothing.
- **One POST, honestly reported.** A confirmed run makes one
  `POST /printer/gcode/script` with that one line. Success means Moonraker
  accepted the script — the reply says so and does not claim the macro's own
  actions have finished. A failed send is reported as failed/uncertain,
  never as "ran".

The natural-language (LLM) helper may name only the bare, read-only
`/print-macros` listing. It can never name a `run` form — running a macro is
something a person types and confirms, the same treatment the other
state-changing commands get in the allow-list.

## The per-vendor macro matrix, as it actually is

| Printer | Connection | Macro situation |
| --- | --- | --- |
| Flashforge AD5X (ZMod) | Moonraker | ZMod macros in the printer's Klipper config: `START_PRINT` / `END_PRINT` own the job start and end, `CHANGE_ZCOLOR` syncs IFS slots to the native screen, `AUTO_FULL_BED_LEVEL` and `BED_LEVEL_SCREWS_TUNE` are the levelling helpers, and the IFS feed path is internal (`_`-prefixed). The registry also describes ZMod's operator macros verified from its shipped config (Stage 3 of #291): `COLDPULL`, `LOAD_FILAMENT` / `UNLOAD_FILAMENT` / `LOAD_MATERIAL`, `CLEAR_NOZZLE`, `SET_EXTRUDER_SLOT`, the Spoolman pair `SET_ACTIVE_SPOOL` / `CLEAR_ACTIVE_SPOOL`, `SAVE_ZMOD_DATA` / `GET_ZMOD_DATA`, `NOZZLE_CONTROL`, the PID tunes, `ZSHAPER`, `DISPLAY_OFF` / `DISPLAY_ON`, and Print Handy's own `PRINT_HANDY` slot-match reporter. `/print-macros` discovers the live set; `/print-lookup` describes the registry-known ones. |
| Generic Klipper, Sovol SV06 | Moonraker | The printer's config is expected to provide `PRINT_START` / `PRINT_END`; Print Handy's profiles emit those names and the installed macro owns heating, homing and mesh loading. Anything else the config defines is discovered live by `/print-macros`. Where the config is Mainsail's client config, the registry also describes its `PAUSE` / `RESUME` / `CANCEL_PRINT` wrappers and the layer-pause set (`SET_PAUSE_NEXT_LAYER`, `SET_PAUSE_AT_LAYER`, `SET_PRINT_STATS_INFO`) — Klipper's own commands of the pause/resume names are built-ins under `[pause_resume]`, not macros, and never appear in a listing. |
| Elegoo Neptune 4 / Pro / Plus / Max | Moonraker | A Moonraker printer, so `/print-macros` works — but note the start sequence is **inline** in the sliced file, not a macro call. `PRINT_START` is a foreign marker on this family: Print Handy's Elegoo guard refuses a file that calls it (see `print_handy/printers/elegoo/guard.py`). A `PRINT_START` macro appearing in a Neptune's own config listing is the printer's business; Print Handy never emits one into a Neptune job. |
| Bambu Lab (all models) | Bambu LAN | No Klipper macros at all. The printer runs plain G/M/T codes only; Klipper or ZMod macro lines are refused by the G-code guard before they can reach the hardware (see the note in `print_handy/printers/base.py`). No macro namespace, so `/print-macros` explains instead of listing. |
| Prusa MK4S / CORE One / XL / MINI+ | PrusaLink | Buddy firmware, not Klipper. There is no Moonraker and no user macro namespace; start/end behaviour lives in the slicer profile's G-code. `/print-macros` explains instead of listing. |
| Elegoo Centauri Carbon | SDCP | No Moonraker and no macro namespace exposed over SDCP. `/print-macros` explains instead of listing. |
| Flashforge Adventurer 5X (stock) | Stock Flashforge | Stock firmware, plain G-code only — the same line-by-line guard posture as Bambu. The ZMod macro set exists only on a ZMod install (the AD5X row above). `/print-macros` explains instead of listing. |
| Marlin via OctoPrint | OctoPrint | Marlin has no Klipper-style macro namespace; start/end G-code lives in the slicer profile or OctoPrint settings. `/print-macros` explains instead of listing. |

## Where the knowledge lives

- The **printer** is the authority on which macros exist — that is what
  `/print-macros` reads, live.
- The **registry** (`firmware/commands.toml`) is the descriptive layer: it
  says what a known macro does and what to be careful about. It is advisory
  reference data, also used by `/print-lookup`; the lookup, troubleshooting
  and macro-listing code never sends an entry to a printer. The only send
  path for a macro is the guarded `/print-macros run` flow above, and it
  sends the operator-confirmed line for a live-discovered name — the
  registry supplies the safety note in the prompt, never the command.
- Registry entries are added only from verified firmware evidence (Stage 3
  of issue #291). An unverified name stays "defined by your printer's
  config" — present in the listing, without an invented description.

Nothing here claims live-hardware verification: discovery is tested offline
against recorded Moonraker response shapes, as with the Bambu, Prusa and
Elegoo LAN work.
