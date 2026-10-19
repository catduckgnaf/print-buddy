# Print Buddy

[![CI](https://github.com/catduckgnaf/print-buddy/actions/workflows/ci.yml/badge.svg)](https://github.com/catduckgnaf/print-buddy/actions/workflows/ci.yml)

Print Buddy is an automated 3D printing pipeline driven from a Discord channel. Post a MakerWorld or Printables link, or a 3MF or STL file, and the bot downloads the model, merges multi plate parts, matches colors to loaded spools in Spoolman, and slices headless with OrcaSlicer. Once someone confirms the bed is clear, it sends the job to Moonraker on a Klipper printer. The Discord side runs on Hermes Agent. The live setup is a Flashforge AD5X on ZMod Klipper firmware. The offline core in `print_buddy/core/` runs with no printer.

## How it works

In the `#3d-printer` channel, someone posts a link. The bot replies with a job summary and a button:

> **Mrs catduck:** https://makerworld.com/en/models/931302-holder-for-post-it-notes
>
> **Print Buddy:** Model: Post it Note Holder with Stencils. Filament: Matte Black PLA (~48g). Estimated print time: 1 hour 14 minutes. Target printer: Flashforge AD5X (ZMod Klipper).
>
> [Slice and print now (bed is clear)]
>
> **Print Buddy:** Bed heating started. Job sent to Moonraker. Finish time estimated for 4:22 PM ET. Don't touch the build plate.

The print starts only when someone clicks the button. On completion, the bot posts stats and writes the job to an Obsidian archive note.

## Settings

`config/home.toml` holds the home AD5X setup: bed size, print height, nozzle, IFS slot count, margins, prime tower, Orca templates, and slicer commands.

`config/local.toml` overrides any key in it for one machine. It is gitignored, so `git pull` never touches it. Environment variables named `PRINT_BUDDY__SECTION__KEY` override a key too, and the names the home services already use (`MOONRAKER_URL`, `SPOOLMAN_URL`, `HERMES_HOME`, ...) still work. `PRINT_BUDDY_CONFIG=/path/to/settings.toml` loads a different file.

A typo or bad value stops the import and names the key. Requires Python 3.11 or newer.

`[visual_watch] sensitivity` sets how readily the camera watchdog posts a "stalled layers" alert, on a scale of 1 (quietest) to 5 (most alerts). 3 is the original behavior. Lower levels need a larger unchanged stretch before calling a stall and check the camera less often. At 1 and 2 a stall alerts only when the vision model does not also report the print as `ok`/`safe`. Empty-bed, spaghetti, detached-part, uncertain, and vision-failure alerts fire at every level. Example in `config/local.toml`:

```toml
[visual_watch]
sensitivity = 2
```

Restart the Moonraker listener after changing it.

`[printer] family` picks the printer adapter (`flashforge_zmod` by default, `generic_klipper`, `sovol_klipper`). The single-extruder families skip every ZMod/AD5X step (IFS slots, screen offsets, MD5 gcode) and refuse multi-color jobs. Each sliced job records its family in `JOB.json`; `print-now` refuses a job prepared for a different family, and `model_job fetch|slice --printer <family>` prepares a job for another one. See `print_buddy/printers/base.py`.

## Updating the home box

Update only from a commit that is green in CI. On the home machine:
```bash
scripts/home-update.sh          # fast-forward to origin/main
scripts/home-update.sh v2.0.3   # or a tag
```
The script refuses to run if tracked files were edited by hand. It runs the offline tests and the doctor after the update, and resets to the previous commit if either fails. `config/local.toml` is never touched. A listener restart command can go in `config/after-update.sh` (gitignored), which runs after a good update.

Check the setup any time with `python3 -m print_buddy.doctor`. It also checks Moonraker and Spoolman when `config/local.toml` sets them:
```toml
[services]
moonraker_url = "http://192.168.x.x:7125"
spoolman_url = "http://192.168.x.x:7912"
```

## Running tests

From the repository root, CI runs this on every push and pull request:
```bash
python3 -m pip install -r requirements-test.txt
python3 -m pytest tests
```
A second CI job installs the Flathub OrcaSlicer the home box runs, slices small test models with the home templates, and runs the slice guards on the real G-code. Run it locally with `PRINT_BUDDY_REAL_SLICER=1 python3 -m pytest -s tests/slicer`.

## ZMod plugin and spool matching

ZMod switches to a backup spool mid-print only when another slot holds the exact same color and material. The `print_bitch.cfg` macro checks that before a job starts:
```gcode
PRINT_BITCH SLOT=1
```
If slot 1 and slot 3 are both black PETG, it confirms:
```
PRINT_BITCH: black / PETG also on slot 3. ZMod can switch. This macro does not.
```
`PRINT_BITCH COLOR=black MATERIAL=PETG` checks all four slots without assuming an active toolhead.

To install, run this on the printer console:
```gcode
ENABLE_PLUGIN name=print-bitch
```
Then add your slot assignments to `mod_data/user.cfg` in a `[gcode_macro _PRINT_BITCH_VARS]` block and run `FIRMWARE_RESTART`. Moonraker update manager entry:
```ini
[update_manager print-bitch]
type: git_repo
path: /root/printer_data/config/mod_data/plugins/print-bitch
origin: https://github.com/catduckgnaf/print-buddy.git
primary_branch: main
managed_services: klipper
channel: dev
is_system_service: False
```

## Repository structure

* `config/home.toml`: home setup settings. See Settings.
* `print_buddy/settings.py`: loads and validates settings.
* `print_buddy/doctor.py`: checks that a machine can run Print Buddy.
* `scripts/home-update.sh`: updates the checkout and rolls back if checks fail.
* `print_buddy/core/`: offline 3MF and STL helpers. No printer connection.
* `print_buddy/templates/orca/`: example Orca machine, process, and filament JSON.
* `plugins/print-feedback/`: guards that limit clarify choices and repeated terminal loops.
* `print_bitch.cfg`: Klipper macro for backup IFS slot matching. The name is historical.
* `install.sh`, `uninstall.sh`, `update.sh`: ZMod plugin lifecycle scripts.
* `tests/`: unit tests for the offline core, the Klipper macro, and interaction guards.
* `docs/`: AD5X integration specs and upstream tool research.

Printer families live in `print_buddy/printers/`; see `base.py` for what each one owns.

## Links

* ZMod AD5X docs: [AD5X.md at 0017033](https://github.com/ghzserg/zmod/blob/001703371c90e228defce41bb4230b7fafd37fea/docs/en/AD5X.md)
* ZMod firmware project: [ghzserg/zmod](https://github.com/ghzserg/zmod)
* ZMod plugin guide: [wiki.zmod.link/Plugin](https://wiki.zmod.link/Plugin/)
* OrcaSlicer CLI documentation: [CLI mode](https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_mode)

## Release history

### 2.0.3: Split plates track their plan, honest copy counts
* **Split plates advance their plan**: plates 2 and later of a split job now start with the plan ID and part, so finishing them updates the plan and `/print-next` offers the right next plate (#48).
* **Copies only where they print**: split, multi-plate and per-part jobs no longer offer a copy count they would ignore. Intake says it is printing one copy, and the job record stays at 1 (#37).
* **PLA+ in a PLA slot**: native multicolor accepts a PLA+ spool in a slot the printer labels PLA.
* **Home update**: `scripts/home-update.sh` uses the Hermes agent venv when `$PYTHON` is unset, and its test no longer inherits the caller's `HERMES_HOME`.

### 2.0.2: Whole stack public, other Klipper printers
* **Full runtime in the repo**: the Discord intake, Moonraker listener, Hermes plugin, spool sync and job archive now live here, installed into a Hermes profile with `scripts/install-hermes.sh` (symlinks plus a gitignored personal overlay).
* **Settings file**: `config/home.toml` with `config/local.toml` overrides. `scripts/home-update.sh` updates and rolls back on failed checks.
* **Printer families**: `[printer] family` selects `flashforge_zmod` (default), `generic_klipper` or `sovol_klipper`. Stock Klipper families print single color with no ZMod steps; jobs record the family they were sliced for.
* **Multi-plate jobs**: pick the next plate from a Discord picker, confirm the bed once, and get one combined timelapse at the end.
* **Spool swap mid-job**: a swapped spool can finish a job sliced for the old one, by explicit choice.
* **Estimates**: per plate and per part figures that count only the copies the G-code contains.
* **Tests**: CI runs the offline suite, a real Orca slice, and a real Spoolman on every push.

### 2.0.1: Honest filament estimates and readable part names
* **Filament estimates**: when parts share one filament, the total is split across them instead of multiplied.
* **Model page estimates**: the first intake message shows print time and grams from the MakerWorld page.
* **Readable part names**: generic CAD names like "Cylinder" become a shape description with size, plate, and color.

### 2.0.0: Shareable offline core
* **`print_buddy/core/`**: the offline pipeline for 3MF and STL files. It does not connect to a printer, Discord, or any home server.
* **Orca templates and license**: machine, process, and filament JSON for a Flashforge AD5X style bed. MIT license.
* **Left private on purpose**: Discord intake, the Moonraker listener, spool sync, and job archive.

Older releases: see git history and tags.
