# ZMod printers

Print Buddy's home platform is Flashforge printers running [ZMod](https://zmod.link)
(Klipper + Moonraker on top of the stock firmware). ZMod supports five Flashforge
models; Print Buddy has first-class profiles for all five
([#301](https://github.com/catduckgnaf/print-buddy/issues/301)).

| Model | `[printer] model` | Build volume | Filament system | Status |
| --- | --- | --- | --- | --- |
| Flashforge AD5X | `flashforge.ad5x` | 220 × 220 × 220 mm | 4-slot IFS feeder | Supported |
| Flashforge AD5M | `flashforge.ad5m` | 220 × 220 × 220 mm | Single extruder, no IFS | Supported |
| Flashforge AD5M Pro | `flashforge.ad5m_pro` | 220 × 220 × 220 mm | Single extruder, no IFS | Supported |
| Flashforge Creator 5 | `flashforge.creator5` | 256 × 256 × 256 mm | 4 independent toolheads | Supported |
| Flashforge Creator 5 Pro | `flashforge.creator5_pro` | 256 × 256 × 256 mm | 4 independent toolheads | Supported |

Nothing in this table is live-hardware tested: every profile is offline-verified,
the same treatment the AD5X support has.

## How the models differ

All five models speak the same ZMod language — Moonraker transport and ZMod's
`START_PRINT ... MESH=` / `END_PRINT` start code from their Orca templates — and
each ships its own Orca machine/process/filament templates under
`print_buddy/templates/orca/`, derived from OrcaSlicer's upstream Flashforge
profiles with the same adjustments the AD5X templates carry (ZMod start/end
G-code, retraction tuning, corner-origin printable area).

ZMod documents **no Klipper 13 support on the Creator models** — run them on the
stock-Klipper ZMod configuration, not the Klipper 13 one.

The filament system is where they part:

- **AD5X** is the full ZMod path: 4 IFS slots, slot questions during intake, Spoolman
  slot matching, the native-screen and stock `/detail` machinery, and the
  `PRINT_BUDDY` ZMod plugin macro that reports spools ZMod can switch to mid-print
  (see the project reference's "ZMod plugin and spool matching" section).
- **AD5M and AD5M Pro** are single-extruder printers. Their adapter shares the ZMod
  start code and Moonraker transport with the AD5X and nothing else: no IFS slot
  questions, no spool-switch claims, no `PRINT_BUDDY` macro (it is AD5X-only), no
  native-screen sync and no stock `/detail` polling. A multi-colour job is refused,
  not approximated — slice it single-colour or use a multi-slot printer. The Pro's
  enclosure, camera and air filtration do not change slicing; its geometry is the
  AD5M's.
- **Creator 5 and Creator 5 Pro** are toolhead machines: four independent
  toolheads (T0–T3, Klipper `extruder`…`extruder3`), each with its own filament,
  changed by the sliced file's bare `T` lines — a tool changer, not a feeder.
  Print Buddy models them as **tools**, not IFS slots (`[printer] tool_count`,
  `ifs_slots` stays 1): slicer tool *i* always prints with toolhead *i*, readiness
  and status are per toolhead, and Spoolman spools bind per toolhead — the
  toolhead is the identity unit, never an IFS slot. A job that asks for a tool remapped to another head, or a fifth
  tool, is refused rather than approximated. Multi-colour slicing uses the
  four-extruder Orca templates, and the Discord colour questions are per
  toolhead: for a source with two to four colours, intake asks one question
  per colour — which toolhead prints it — showing each toolhead's loaded
  spool, and a toolhead already assigned a different colour is not offered
  again. The recorded picks are the identity mapping (slicer tool *i* prints
  with toolhead *i*), so nothing is remapped. A source with more colours
  than toolheads is refused with that explanation; printing everything in
  one colour on one toolhead stays available. Multi-colour jobs print as one
  merged plate; a source that cannot merge onto one bed is refused rather
  than split into per-toolhead plates. The `PRINT_BUDDY`
  plugin macro stays AD5X-only — ZMod's endless-spool feature exists on the
  Creator too, but the macro's slot model is the IFS one. The Pro adds the
  enclosed frame, active chamber heating (65 °C) and air filtration over the base
  Creator 5; the print geometry and tool model are identical, and its template
  records the chamber and filtration support.

## Bundled Spoolman from printer Moonraker (#443)

Print Buddy's bundled Spoolman normally lives on loopback inside the
Print Buddy container, which is enough for Print Buddy itself. When
Moonraker runs on the printer hardware — the usual ZMod layout, for
example an AD5X at `http://192.168.x.x:7125` — Moonraker's own
`[spoolman]` component needs to reach that API over the LAN to sync
active spool IDs with the IFS slots. That access is opt-in:

1. In the Unraid template, keep the advanced **Spoolman port** mapping
   (host 7912 to container 8000) and set the advanced **Spoolman bind
   host** variable `SPOOLMAN_HOST=0.0.0.0`. With the default
   `127.0.0.1`, Spoolman stays loopback-only and unexposed. Under
   Compose instead, uncomment the `"7912:8000"` mapping and set
   `SPOOLMAN_HOST=0.0.0.0` in `.env` (see
   [Docker](DOCKER.md#included-spoolman)).
2. In the printer's Moonraker config, point `[spoolman]` at the
   Print Buddy host:

   ```ini
   [spoolman]
   server: http://<unraid-ip>:7912
   ```

3. Check from any LAN machine: `GET http://<unraid-ip>:7912/api/v1/info`
   answers HTTP 200 when the bundled Spoolman is up.

The Spoolman API is unauthenticated — LAN only, never forward port 7912
from a router. Home Assistant REST sensors use the same base URL
(`http://<unraid-ip>:7912/api/v1/...`).

## Choosing a model

Set `[printer] model` to the key from the table (or `PRINT_BUDDY__PRINTER__MODEL` in
Docker). The setup wizard and the Web UI picker list these models from the printer
registry, so no other configuration names them. Stock (non-ZMod) firmware is a
separate path — only the AD5X has one today (`flashforge_stock.ad5x`,
see [Stock Flashforge printers](FLASHFORGE-STOCK.md)).
