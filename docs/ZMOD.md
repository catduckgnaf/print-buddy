# ZMod printers

Print Buddy's home platform is Flashforge printers running [ZMod](https://zmod.link)
(Klipper + Moonraker on top of the stock firmware). ZMod supports five Flashforge
models; Print Buddy has first-class profiles for the three single-filament-system
machines below, and the two toolhead machines are Stage 2 of
[#301](https://github.com/catduckgnaf/print-buddy/issues/301).

| Model | `[printer] model` | Build volume | Filament system | Status |
| --- | --- | --- | --- | --- |
| Flashforge AD5X | `flashforge.ad5x` | 220 × 220 × 220 mm | 4-slot IFS feeder | Supported |
| Flashforge AD5M | `flashforge.ad5m` | 220 × 220 × 220 mm | Single extruder, no IFS | Supported |
| Flashforge AD5M Pro | `flashforge.ad5m_pro` | 220 × 220 × 220 mm | Single extruder, no IFS | Supported |
| Flashforge Creator 5 | `flashforge.creator5` | 256 × 256 × 256 mm | 4 independent toolheads | Not yet — #301 Stage 2 |
| Flashforge Creator 5 Pro | `flashforge.creator5_pro` | 256 × 256 × 256 mm | 4 independent toolheads | Not yet — #301 Stage 2 |

The Creator rows name the model keys Stage 2 will register; selecting them today is
rejected as an unknown model. Nothing in this table is live-hardware tested: every
profile is offline-verified, the same treatment the AD5X support has.

## How the supported models differ

All three supported models speak the same ZMod language — Moonraker transport and
ZMod's `START_PRINT ... MESH=` / `END_PRINT` start code from their Orca templates —
and each ships its own Orca machine/process/filament templates under
`print_buddy/templates/orca/`, derived from OrcaSlicer's upstream Flashforge profiles
with the same adjustments the AD5X templates carry (ZMod start/end G-code, retraction
tuning, corner-origin printable area).

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

## Choosing a model

Set `[printer] model` to the key from the table (or `PRINT_BUDDY__PRINTER__MODEL` in
Docker). The setup wizard and the Web UI picker list these models from the printer
registry, so no other configuration names them. Stock (non-ZMod) firmware is a
separate path — only the AD5X has one today (`flashforge_stock.ad5x`).
