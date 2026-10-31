# AD5X best practices

Operator guidance for running Print Handy with a Flashforge Adventurer 5X
on ZMod. Part of [Best practices on specific devices](DEVICE-BEST-PRACTICES.md).

The contracts behind this page are in [ZMod printers](ZMOD.md),
[AD5X integration contract](AD5X-CONTRACT.md) and
[Printer calibration](CALIBRATION.md). This page says which choices to make
and in what order.

## Tested baseline

| Item | Value |
| --- | --- |
| Firmware | ZMod 1.7.5-2 (stock base 3.1.7) |
| Klipper | 13 |
| Screen mode | Screenless (`display_off=1`) |
| Touch screen | HelixScreen |
| Purge mode | Trash chute (`use_trash_on_print=1`) |
| Mesh | `use_kamp=1`, `clear=LINE_PURGE` |
| Z offset | Screenless store, `load_zoffset=1` |

## Run screenless

Recommendation: run ZMod screenless (`display_off=1`) and use HelixScreen,
Fluidd or Mainsail as the local interface.

> **Printing from chat screenless (2.2.0).** HelixScreen setups are
> screenless too: HelixScreen runs on screenless ZMod. Print Handy starts a
> screenless print the same way ZMod's own print-file macro does on the AD5X,
> with one `SET_ZCOLOR` call, and checks it from Klipper alone: idle state and
> heater targets from Moonraker, slot material and color from `zmod_color`,
> and slot presence from `zmod_color`'s `hasFilament` (the stock firmware's
> API does not answer screenless). This route is offline-tested only; the
> first screenless print from chat is its live check. Report what you see on
> the issue tracker.

Why it works better with Print Handy:

- **One owner for each value.** With the stock screen running, the screen
  owns the Z offset and the bed mesh and loads its own at every print start.
  Print Handy can only report those values and guide you through the screen.
  Screenless, the values live in Klipper and ZMod's saved variables, where
  Print Handy can read them, calibrate them and verify them.
- **IFS slot presence comes from Klipper.** Screenless, the stock firmware is
  not running, so its HTTP API does not answer. Print Handy reads slot
  presence from Klipper's `zmod_color` object (with `zmod_ifs` as the IFS
  state) instead. Insertion prompts, runout slot evidence and refill events
  work from that source.
- **Cancels are plain Klipper cancels.** A cancel from HelixScreen, Fluidd or
  Mainsail is handled like any Klipper cancel. Print Handy does not restart
  Klipper after it. The stock screen cancel handling only applies when the
  stock screen is actually running.

Stock screen mode still works. Expect report-only calibration and screen-owned
mesh and offset; see [Printer calibration](CALIBRATION.md).

## ZMod version

`/print-firmware` and the doctor's `zmod version` row show the ZMod version
Print Handy can read. Check it after any ZMod update.

On the AD5X, Moonraker's update manager lists the ZMod components (`Z-Mod`,
`klippy`, `moon`) as git repositories with version `?`, because the
printer's install carries no git metadata. When that happens, Print Handy
reads the version from Moonraker's `/machine/system_info` distribution entry
instead (for example `zmod 1.7.5 -> 1.7.5-2`). How the version is read and
reported is in [ZMod printers](ZMOD.md#audited-zmod-version). If the doctor
row still says `unknown`, everything version-gated takes the conservative
path (see [3MF delivery](#3mf-delivery)).

ZMod's saved variable `klipper13` can read `0` while the host runs Klipper
13. In that state ZMod's MCU/host mismatch warning is off. Confirm with ZMod
what that means for your install before relying on the warning.

## Z offset

Screenless, the offset is the saved `gcode_offsets.z`. It is loaded at print
start only when `SAVE_ZMOD_DATA LOAD_ZOFFSET=1` has been set once. Keep it
at 1.

- `LOAD_ZOFFSET_NATIVE` copies the stock screen's offset into the screenless
  store. With its default `START=0` it copies and saves. `START=1` (used at
  boot) only reports. There is no reverse copy.
- Run it once when switching from the stock screen, then adjust during a
  print from the web interface. ZMod saves those adjustments itself. Do not
  use `Z_OFFSET_APPLY_ENDSTOP` and do not edit `[probe] z_offset`.
- Sync the offset before building a mesh. The mesh routine refuses to run
  when the saved offset or `load_zoffset` does not match its reviewed
  interface packet.

Details: [Z offset](CALIBRATION.md#z-offset--report--guide-in-every-mode).

## Bed mesh

Build the full mesh with `/print-calibration` (or the supervised
`moonrakerctl mesh-run` routine,
[bed mesh routine](../hermes/skills/klipper-3d-printing/references/bed-mesh-routine.md)).
Screenless, both run ZMod's load-cell-aware leveling:

```
AUTO_FULL_BED_LEVEL EXTRUDER_TEMP=220 BED_TEMP=60 PROFILE=auto SAVE=0
```

`/print-calibration` measures into a scratch profile first and saves to
`auto` only after you accept. `mesh-run` measures into `auto` and persists
only after it verifies a full 5 by 5 mesh.

- **Temperatures are 220 C nozzle and 60 C bed.** ZMod heats, cleans the
  nozzle, homes and prepares the load cells itself.
- **It takes longer than five minutes.** Do not cut it short and do not
  assume a slow run is a hung run. On the reference printer a full run took
  well over 300 seconds.
- **`auto` is the profile prints load.** A mesh saved under any other name
  is not used by `START_PRINT`.
- **Check the heaters afterwards.** Both routines turn heater targets off
  and verify the readback. If anything is interrupted, confirm both targets
  read 0 before walking away.
- **Never calibrate mid-print.** Both routines refuse unless the printer is
  idle. Clear the bed first.
- A screw tune (`BED_LEVEL_SCREWS_TUNE`) invalidates both the mesh and the
  Z offset. Redo both after one.

### KAMP and which mesh a print uses

With `SAVE_ZMOD_DATA USE_KAMP=1`, ZMod builds an adaptive mesh over the
printed area at print start instead of relying only on the full `auto`
mesh. ZMod recommends `SAVE_ZMOD_DATA CLEAR=LINE_PURGE` with it, so the
purge line lands inside the adaptive area. With KAMP on, ZMod forces
`LINE_PURGE` regardless; without object labels in Orca it falls back to
`_CLEAR2`.

Print Handy's AD5X slices do not emit object labels (`gcode_label_objects`
and `exclude_object` are off in the AD5X Orca template), so with KAMP on,
expect ZMod's `_CLEAR2` fallback purge. Whether ZMod still builds an
adaptive mesh without labels has not been checked on a printer.

Today Print Handy's readiness check does not say whether a given print will
use KAMP or the saved `auto` mesh. Keep the full mesh current anyway: it is
the fallback and the reference for how flat the bed is.

## Purge mode and multicolor

ZMod's saved variable `use_trash_on_print` decides where color-change purge
goes. Print Handy reads it live and slices to match.

| Value | ZMod behaviour | Print Handy |
| --- | --- | --- |
| `1` (default) | Purges into the trash chute on every color change | Slices as before: the prime tower only primes |
| `0` (Nopoop) | No chute purge; the slicer purges into the prime tower | Slices with purge in the prime tower: tower type 2, by-layer sequence, no ramming, nozzle volume 144 mm³, 424 mm³ flush per color change. OrcaSlicer only |
| `2` | Slicer-controlled purge at the chute, from ZMod's own Orca profiles | Refused: Print Handy has no profile for it |

An unreadable or missing value is treated as `1`.

Nopoop is core ZMod. No plugin is needed. Switch with:

```
SAVE_ZMOD_DATA USE_TRASH_ON_PRINT=0
```

Then slice the next multicolor job through Print Handy. A file sliced
before the switch still carries the old purge plan. Reslice it.

## QuickSwap

QuickSwap is not yet verified with Print Handy. Treat everything here as
the safe order to try it in, not a supported configuration.

Recommended order:

1. Switch to Nopoop (`USE_TRASH_ON_PRINT=0`), above.
2. Print one two-color job sliced by Print Handy and check the colors
   are clean.
3. Only then install QuickSwap.
4. Test a single color change before any long multicolor print.

Known risks:

- Upstream QuickSwap recommends Klipper 12. Klipper 13 is untested there.
- It replaces ZMod's color-change routine. Print Handy's IFS handling
  relies on `SET_ZCOLOR` / `CHANGE_ZCOLOR` and the slot mapping. Re-check
  slot mapping and runout handling after installing.
- It wants `[zmod_ifs] next_cmd_delay: 0.02`. ZMod's default is `0.2`.
- Keep the rollback ready: `UPDATE_MCU FORCE=12` returns the MCU to the
  Klipper 12 firmware.

## 3MF delivery

`[printer] zmod_delivery_format` chooses how sliced jobs travel to the
printer. See [Print file format](ZMOD.md#print-file-format-gcode-or-gcode3mf-564)
and the [Settings reference](SETTINGS.md).

| Value | Sends |
| --- | --- |
| `auto` (default) | `.gcode.3mf` when the printer reports ZMod 1.7.5 or newer, `.gcode` otherwise |
| `gcode` | Always `.gcode` |
| `3mf` | Always `.gcode.3mf`, even when the version is unknown |

`auto` is the default. If Print Handy cannot read the version (see
[ZMod version](#zmod-version)), `auto` sends plain `.gcode`, the
long-standing path. With the version readable as 1.7.5 or newer, `auto`
already sends `.gcode.3mf`, and that path has not yet passed the live
checks on issue #564 (starting a packaged print, color mapping on the
printer, web UI metadata, timelapse markers). If a packaged print
misbehaves on your printer, set `gcode` to go back to the long-standing
path, and report what you saw on #564.

## Spools, IFS slots and Spoolman

- Load and unload through the IFS normally; Print Handy follows slot
  presence from `zmod_color`.
- Keep Spoolman's remaining weight honest. Readiness uses Spoolman's grams
  as well as slot presence. A spool that reads negative or far off in
  Spoolman should be corrected there, or Print Handy may offer a slot that
  just ran out.
- After a runout, answer the spool question first. Then start the next
  print.

## Camera and timelapse

The AD5X has no built-in camera. With a USB camera configured in ZMod,
Print Handy closes the timelapse capture before it announces the finished
print, so the video posted is the one from that print. A dark or covered
camera is not treated as a print failure. "Stop asking" on the watchdog
lasts for the print.

## Verified on hardware

| Item | Status |
| --- | --- |
| Z offset sync with `LOAD_ZOFFSET_NATIVE`, screenless store loaded at print start | Verified on 2026-10-28 |
| Full mesh run (`AUTO_FULL_BED_LEVEL` 220/60), saved to `auto`, persisted points match the probe | Verified on 2026-10-28 |
| Screenless IFS slot presence read from `zmod_color` | Verified on 2026-10-28 (read only) |
| Nopoop multicolor print sliced by Print Handy | Not verified |
| QuickSwap with Print Handy | Not verified |
| `.gcode.3mf` live print on ZMod 1.7.5 | Not verified |
| Starting a slot-bound print screenless (`display_off=1`) from chat | Not verified (offline-tested only, 2.2.0) |
| `/print-calibration mesh` from chat (the table's mesh row used the `mesh-run` script path) | Not verified |


## Start status after a lost Moonraker response

A timeout while submitting a native `SET_ZCOLOR` start does not prove that
the printer rejected the job: Moonraker may have accepted it before the
response was lost. Print Handy now checks read-only printer status for the
exact uploaded file (including the documented `.gcode.3mf` unpacked names)
before classifying the start. A matching preparing or printing state is
reported as such; absent, unrelated or unreadable status remains unresolved.
An unresolved start is not retried automatically. Check printer status before
taking further action.

This is an offline-tested software behavior, not a live AD5X start test.
Preparation evidence is not proof of a completed print, and a timeout followed
by inconclusive status cannot safely distinguish rejection from delayed
acceptance. Do not manually resubmit while the original result is uncertain.
