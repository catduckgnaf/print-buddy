# Print Buddy

[![CI](https://github.com/catduckgnaf/print-buddy/actions/workflows/ci.yml/badge.svg)](https://github.com/catduckgnaf/print-buddy/actions/workflows/ci.yml)

Print Buddy is an automated 3D printing pipeline driven from a Discord channel, for Klipper printers and Flashforge printers running ZMod. Post a MakerWorld or Printables link, or a 3MF or STL file, and the bot downloads the model, merges multi plate parts, matches colors to loaded spools in Spoolman, and slices headless with OrcaSlicer. Once someone confirms the bed is clear, it sends the job to the printer through Moonraker, watches it through the camera, and posts the result.

## About

Print Buddy is almost entirely Python. Downloading, plate merging, color matching, slicing, job start, printer monitoring, spool sync, timelapses, and print records are all plain scripts with fixed rules, so they are fast and make no LLM calls.

The Discord conversation runs on [Hermes Agent](https://github.com/NousResearch/hermes-agent) using Luna at medium reasoning. Two optional extras also call a model: the camera watchdog asks a vision model to classify a print frame, and the "print started" post adds a one line roast. Leave `services.vision_chat_url` empty and neither runs.

Supported printers:
* **Klipper:** the Sovol SV06 on stock Klipper (`sovol_klipper`), where Print Buddy started, and any other Klipper printer with Moonraker (`generic_klipper`). Single extruder.
* **ZMod (Flashforge):** Flashforge printers running ZMod firmware (`flashforge_zmod`), built and run on the AD5X, including IFS multi color slots and the ZMod plugin below.

Pick one with `[printer] family`. The current printer is a Flashforge AD5X on ZMod; the SV06 came first. The offline core in `print_buddy/core/` runs with no printer.

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

## Features

**Intake and slicing**
* MakerWorld and Printables links, or uploaded 3MF and STL files.
* Print time and grams from the model page in the first reply.
* Multi plate models merged onto one bed when they fit; plates that would run longer than `layout.max_merged_hours` stay separate.
* Oversized models split across plates, tracked as one plan.
* Copy counts offered only where the G-code will actually contain the copies.
* Headless OrcaSlicer with versioned machine, process, and filament templates; Bambu Studio as a fallback slicer with its network cut.
* Readable part names: generic CAD names like "Cylinder" become a shape, size, plate, and color description.

**Filament and spools**
* Colors matched to loaded IFS slots from Spoolman. PLA+ is accepted in a PLA slot.
* Filament estimates split across parts that share a spool, never multiplied.
* `/spool` lists, changes, creates, and syncs spools without moving the printer.
* A swapped spool can finish a job sliced for the old one, by explicit choice.
* `PRINT_BUDDY` Klipper macro confirms ZMod can fall back to a matching backup slot.

**Printing**
* Nothing starts without a bed clear button press.
* Multi plate plans: `/print-next` offers the exact next plate, and finishing a plate advances the plan.
* `/print-again` reprints an archived job exactly, with no re-slice.
* `/print-stop` and `/print-resume` each send at most one Moonraker command behind a confirm button.
* `/print-reboot` uses the safe ZMod reboot flow.
* Printer families: `flashforge_zmod`, `generic_klipper`, `sovol_klipper`. Each job records the family it was sliced for and refuses another.

**Monitoring**
* Event driven Moonraker listener: start, pause, error, and completion posts with stats.
* Camera watchdog checks layer 2, layer 5, and periodic frames for empty bed, spaghetti, a detached part, or a stalled print. Stall sensitivity is adjustable from 1 to 5.
* Stop and pause alerts carry Resume and Cancel buttons.
* Klipper report posted when a print is cancelled.
* Timelapse per print, or one combined video for a multi plate plan, sized to fit Discord.

**Records and upkeep**
* Every finished job written to an Obsidian vault and the job archive.
* Nightly catch up against Moonraker job history so nothing is missed.
* `/print-maintenance` guided checklist and reminders by print hours and days.
* `/print-coldpull` runs an operator confirmed cold pull at configured temperatures.

## Settings

`config/home.toml` holds the defaults for the AD5X setup. `config/local.toml` overrides any key for one machine; it is gitignored, so `git pull` never touches it. An environment variable named `PRINT_BUDDY__SECTION__KEY` overrides a key too, and the older names the services already use (`MOONRAKER_URL`, `SPOOLMAN_URL`, `HERMES_HOME`, ...) still work. `PRINT_BUDDY_CONFIG=/path/to/settings.toml` loads a different file.

A typo or bad value stops the import and names the key. Requires Python 3.11 or newer. Restart the Moonraker listener after changing a setting.

```toml
# config/local.toml example
[services]
moonraker_url = "http://192.168.x.x:7125"
spoolman_url = "http://192.168.x.x:7912"

[visual_watch]
sensitivity = 2
```

### Camera stall sensitivity

`[visual_watch] sensitivity` sets how readily the camera watchdog posts a "stalled layers" alert, from 1 (quietest) to 5 (most alerts). Default is 3.

| Level | Frame counts as unchanged if diff below | Stall alert after | Periodic camera check | Vision "ok" cancels a stall |
|---|---|---|---|---|
| 1 | 1.5 | 8 layers | 30 min | yes |
| 2 | 2.0 | 5 layers | 20 min | yes |
| 3 | 3.0 | 3 layers | 15 min | no |
| 4 | 4.0 | 3 layers | 10 min | no |
| 5 | 5.0 | 2 layers | 7.5 min | no |

Empty bed, spaghetti, detached part, uncertain, and vision failure alerts fire at every level.

### All settings

| Section | Key | Default | What it does |
|---|---|---|---|
| `printer` | `name`, `firmware` | Flashforge AD5X, ZMod Klipper | Shown in job summaries |
| | `family` | `flashforge_zmod` | Printer adapter: `flashforge_zmod`, `generic_klipper`, `sovol_klipper` |
| | `start_macro`, `end_macro` | `PRINT_START`, `PRINT_END` | Start and end macros for the Klipper families |
| | `bed_mm` | `[220, 220]` | Usable print area |
| | `max_print_height_mm` | `220` | Tallest allowed print |
| | `nozzle_diameter_mm` | `0.4` | Slicing refuses any other nozzle |
| | `ifs_slots` | `4` | Filament slots; 1 for a single extruder |
| `layout` | `single_copy_edge_mm`, `multi_copy_edge_mm` | `1`, `3` | Distance from the bed edge |
| | `merge_edge_margin_mm`, `merge_spacing_mm` | `8`, `10` | Gaps when merging plates |
| | `max_merged_hours` | `12` | Longer merged plates stay separate |
| `prime_tower` | `size_mm`, `part_clearance_mm`, `edge_mm`, `merge_slack_mm` | `45`, `8`, `10`, `5` | Prime tower size and clearances |
| `orca` | `templates` | `print_buddy/templates/orca` | Orca machine, process, and filament JSON |
| | `command` | Flathub OrcaSlicer | How to start the Orca CLI |
| `bambu` | `command` | Flathub Bambu Studio, no network | Fallback slicer |
| `paths` | `hermes_home` | `~/.hermes/profiles/3dprinting` | Hermes profile the bot runs in |
| | `archive`, `records_vault`, `cache` | `~/3d-prints`, `~/Documents/3D Printing Records`, `~/.hermes/cache` | Job archive, Obsidian records, cache |
| | `hermes_bin`, `hermes_agent`, `hermes_restart_helper`, `ffmpeg` | | Tool locations |
| `services` | `moonraker_url`, `moonraker_ws_url`, `camera_snapshot_url` | empty | Printer and camera; websocket is derived when empty |
| | `spoolman_url`, `openviking_url` | empty | Spoolman and optional memory store |
| | `vision_chat_url` | empty | OpenAI compatible endpoint for vision checks and roasts; empty disables both |
| | `stock_api_port` | `8898` | Flashforge stock API for IFS presence |
| `discord` | `chat_id`, `approval_user_id` | empty | Channel and approver IDs |
| | `upload_max_bytes` | `9500000` | Largest upload before video is shrunk |
| | `post_print_quiet_s` | `7200` | Quiet time before a chat session resets |
| | `daily_reset_hour`, `timezone` | `4`, `America/New_York` | Daily session reset |
| | `bot_name` | `Print Buddy` | Name the bot uses in the roast persona and the rendered profile templates (`SOUL.md`, locale strings). Set it to anything, for example your old name |
| `listener` | `tick_s` | `600` | Listener housekeeping interval |
| | `ifs_presence_poll_s` | `15` | IFS spool presence poll |
| | `spool_nag_s` | `600` | Reminder interval for an unanswered spool question |
| | `start_claim_ttl_s` | `1800` | How long a start button stays claimed |
| `vision` | `model`, `roast_model` | `gemini-latest`, `luna-latest` | Models for camera checks and roasts |
| `visual_watch` | `sensitivity` | `3` | Camera stall sensitivity, 1 to 5 |
| `timelapse` | `archive_host`, `archive_dir`, `ssh_key` | empty | Remote timelapse copy; empty host disables it |
| | `render_wait_s`, `render_poll_s` | `900`, `10` | Wait for the printer to render the timelapse |
| | `max_bytes`, `local_retention_days`, `plan_clip_retention_days` | 200 MiB, `1`, `14` | Size cap and retention |
| `maintenance` | `quick_hours`, `full_hours`, `full_days` | `25`, `75`, `30` | When maintenance reminders come due |
| `cold_pull` | profile name | `pla_trial = [220, 90]`, `petg = [245, 100]` | Hot and cold temperatures in C |

## Install and update

See [docs/INSTALL.md](docs/INSTALL.md) to install into a Hermes profile.

Update only from a commit that is green in CI. On the machine running Print Buddy:
```bash
scripts/home-update.sh          # fast-forward to origin/main
scripts/home-update.sh <tag>    # or a release tag
```
The script refuses to run if tracked files were edited by hand. It runs the offline tests and the doctor after the update, and resets to the previous commit if either fails. `config/local.toml` is never touched. A listener restart command can go in `config/after-update.sh` (gitignored), which runs after a good update.

Check the setup any time with `python3 -m print_buddy.doctor`. It also checks Moonraker and Spoolman when they are set in `[services]`.

## Running tests

From the repository root, CI runs this on every push and pull request:
```bash
python3 -m pip install -r requirements-test.txt
python3 -m pytest tests
```
A second CI job installs the Flathub OrcaSlicer, slices small test models with the templates, and runs the slice guards on the real G-code. Run it locally with `PRINT_BUDDY_REAL_SLICER=1 python3 -m pytest -s tests/slicer`.

### Discord flow corpus

`tests/corpus/cases/` holds 3MF models run end to end through the Discord intake with fake button clicks: color questions, fit check and resize or split offer, plate planning, slicing, and G-code checks. Nothing contacts a printer. Every PR runs it with a fake Orca; the real-slicer job runs it with Flathub Orca. One test also runs the intake with the gateway's `HERMES_HOME` to keep state in the profile.

To add a model that broke Discord: make `tests/corpus/cases/<name>/` with `model.3mf` (only models you may redistribute: your own, CC0, or attribution licenses; note it as `license = "..."`) and a `case.toml` listing the buttons pressed and what you expect. An unanswered question fails the test and prints its buttons, so copy them in. `tests/corpus/make_models.py` writes the built-in models; see any existing `case.toml` for the format.

```bash
python3 -m pytest -q tests/corpus                                # fake Orca
PRINT_BUDDY_REAL_SLICER=1 python3 -m pytest -q -s tests/corpus   # real Orca, slices under .slicer-work/
```

## ZMod plugin and spool matching

ZMod switches to a backup spool mid-print only when another slot holds the exact same color and material. The `print_buddy.cfg` macro checks that before a job starts:
```gcode
PRINT_BUDDY SLOT=1
```
If slot 1 and slot 3 are both black PETG, it confirms:
```
PRINT_BUDDY: black / PETG also on slot 3. ZMod can switch. This macro does not.
```
`PRINT_BUDDY COLOR=black MATERIAL=PETG` checks all four slots without assuming an active toolhead.

To install, run this on the printer console:
```gcode
ENABLE_PLUGIN name=print-buddy
```
Then add your slot assignments to `mod_data/user.cfg` in a `[gcode_macro _PRINT_BUDDY_VARS]` block and run `FIRMWARE_RESTART`. Moonraker update manager entry, in `mod_data/user.moonraker.conf`:
```ini
[update_manager print-buddy]
type: git_repo
path: /root/printer_data/config/mod_data/plugins/print-buddy
origin: https://github.com/catduckgnaf/print-buddy.git
primary_branch: main
managed_services: klipper
channel: dev
is_system_service: False
```

## Repository structure

* `config/home.toml`: default settings. See Settings.
* `print_buddy/settings.py`: loads and validates settings.
* `print_buddy/doctor.py`: checks that a machine can run Print Buddy.
* `print_buddy/core/`: offline 3MF and STL pipeline. No printer connection.
* `print_buddy/hermes/`: Moonraker listener, Discord posts, spool sync, print control, and records.
* `print_buddy/printers/`: printer family adapters; see `base.py` for what each one owns.
* `print_buddy/templates/orca/`: Orca machine, process, and filament JSON.
* `plugins/print-feedback/`: Hermes plugin with the Discord slash commands and interaction guards.
* `hermes/`: profile templates and skills installed by `scripts/install-hermes.sh`.
* `scripts/`: `install-hermes.sh`, `home-update.sh`, and `migrate-names.sh` (one-shot, see `docs/RENAME-MIGRATION.md`).
* `print_buddy.cfg`, `install.sh`, `uninstall.sh`, `update.sh`: ZMod plugin macro and lifecycle scripts.
* `tests/`: offline suite, real slicer checks, the Discord flow corpus (`tests/corpus/`), and the Klipper macro tests.
* `docs/`: install guide and AD5X integration specs.

## Links

* ZMod AD5X docs: [AD5X.md at 0017033](https://github.com/ghzserg/zmod/blob/001703371c90e228defce41bb4230b7fafd37fea/docs/en/AD5X.md)
* ZMod firmware project: [ghzserg/zmod](https://github.com/ghzserg/zmod)
* ZMod plugin guide: [wiki.zmod.link/Plugin](https://wiki.zmod.link/Plugin/)
* OrcaSlicer CLI documentation: [CLI mode](https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_mode)
* Releases: [GitHub releases](https://github.com/catduckgnaf/print-buddy/releases)
