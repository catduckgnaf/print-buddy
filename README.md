# Print Buddy

Drop a link. Drop a file. Let Discord handle the rest.

Print Buddy is an automated 3D printing pipeline designed for Discord. It removes the desktop slicer, manual SD card shuffling, and confusing printer menus from household printing. Anyone in the house can drop a MakerWorld link, a Printables link, or a raw 3MF or STL file into a Discord channel, and the bot handles downloading, multi plate packing, color matching, headless slicing, and print staging.

## Why This Exists: The Household Test

Standard desktop 3D printing is built for hobbyists who enjoy tinkering with layer heights, tree supports, and temperature towers. It is terrible for anyone who just wants an object out of the printer.

Print Buddy was built so catduck's wife could see a model on MakerWorld, drop the URL into `#3d-printer` on Discord, and get a finished print without ever launching OrcaSlicer, selecting printer profiles, or guessing which spool is loaded in which slot.

## How It Works in Discord

Everything happens inside a single Discord channel. The bot speaks in plain English, keeps terminal spam out of the chat, and provides immediate feedback.

### 1. Drop a link or file

A user posts a link or uploads a file into the `#3d-printer` channel:

> **Mrs catduck:** https://makerworld.com/en/models/931302-holder-for-post-it-notes

### 2. Instant receipt

The bot responds in seconds with a plain English confirmation, an estimated preparation time, and a witty remark:

> **Print Buddy:** Downloading the file from MakerWorld and prepping it for the printer, about 2 minutes. The desk organizer is already more structured than catduck's weekend plans.

### 3. Automated preparation and job card

Behind the scenes, the pipeline:
* Fetches the model files and metadata
* Merges multi plate assemblies onto the bed
* Matches requested colors with loaded filaments in Spoolman
* Runs headless slicing through OrcaSlicer
* Verifies nozzle size, temperatures, and printer readiness

The bot posts the job summary with a single interactive button:

> **Print Buddy:**
> **Model:** Post it Note Holder with Stencils
> **Filament:** Matte Black PLA (~48g)
> **Estimated print time:** 1 hour 14 minutes
> **Target printer:** Flashforge AD5X (ZMod Klipper)
> 
> [🔘 Slice and print now (bed is clear)]

### 4. One tap launch and live updates

Once someone confirms the bed is clear by clicking the button, the print starts immediately:

> **Print Buddy:** Bed heating started. Job sent to Moonraker. Finish time estimated for 4:22 PM ET. Don't touch the build plate.

When the print finishes, the bot posts completion stats and records the job details directly to an Obsidian archive note for maintenance tracking.

## Release history

### 2.0.0 — Shareable offline core

The first release that contains runnable code, not only notes. Version 2.0.0 replaces the 1.10 line so the public number is not read as "version 10."

- **`print_buddy/core/`**: the offline pipeline. It reads 3MF and STL files, maps colors to slots, packs plates, checks slice output, and translates foreign part names. It does not connect to a printer, Discord, or any home server.
- **Orca templates**: machine, process, and filament JSON for a Flashforge AD5X style bed. Copy them and edit them for your own printer.
- **Tests**: `tests/core/test_part_translator.py` runs with no printer. 11 checks passed on the release commit.
- **Left private on purpose**: Discord intake, the Moonraker listener, spool sync, and job archive. Those bind one household's addresses and tokens. They are not in this tag.
- **License**: MIT. `LICENSE` is new in this tag.
- **Install pointer**: the Moonraker update example now uses this repository, `catduckgnaf/print-buddy`, instead of the old `print-bitch` name.

### 1.10.0 — Inch auto-scale, Bambu Studio fallback, faster motion, and reliability fixes

- **Inch unit auto-scale**: STL files exported in inches (largest dimension under 10 mm) are scaled 25.4x automatically when the result fits the bed, then sliced without a prompt. The Discord slice summary states the original size, that it was treated as inches, and the final size; the job record keeps the same detail. An explicit user scale always wins, and a model that would not fit after 25.4x fails with its measured size instead of a guessed factor.
- **Bambu Studio slicer fallback**: OrcaSlicer stays primary. If Orca fails to slice, Bambu Studio CLI retries the same job behind the same post-slice safety gates, records which slicer produced the G-code, and says so in Discord. Percent line widths are converted to millimeters against the nozzle diameter for Bambu, which otherwise rejects them as "too large line width".
- **Faster print motion**: The Orca process profile now caps acceleration at 4,500 mm/s² (outer walls 3,200, top surface 3,000, first layer 500), under the AD5X X axis input shaper limit of about 4,747 mm/s². An offline slice of a large storage bin dropped from 14h 26m to 10h 38m.
- **Clone placement**: Multi-copy jobs from a scaled or rotated STL are placed explicitly on the bed instead of trusting slicer auto-arrange, which could overlap clones.
- **Status and cancel fixes**: Printer state settles before a job is reported as preparing or idle; cancel posts an immediate acknowledgement and no longer forces a firmware restart; completion and timelapse arrive as one message; reconnects no longer replay lifecycle notices.
- **Color and naming fixes**: Explicit color choices resolve to the correct filament slot and Spoolman spool; more foreign part names translate correctly; Orca conflict failures explain the overlap instead of a bare error.
- **Protected settings guard**: Slices are refused if start G-code, end G-code, or other protected machine settings drift from an approved baseline.
- **Test validation**: 724 tests passing in the deployed suite.

### 1.9.1 — Hardware edge margin tuning, multi-plate fit scaling, and conversational link recovery

- **Hardware edge margin relaxation**: Bed margins reduced to 1.0 mm (single-copy) and 3.0 mm (multi-copy), matching the FlashForge AD5X physical 235x235 mm build sheet and stepper bounds. Models up to ~218 mm fit and slice at 100% scale without artificial clipping or bed edge errors.
- **Multi-plate capacity & fit evaluation**: Replaced blind multi-plate capacity pass with per-plate bounding box checks. Multi-plate 3MF models that exceed bed bounds now compute an optimal uniform scale ladder via binary search rather than calculating against the combined multi-plate canvas.
- **Multi-plate slicing isolation**: Resolved an issue where scaled multi-plate jobs collapsed parts onto Plate 1. Multi-plate slice jobs now preserve plate separation, support per-plate scale overrides, and evaluate per-part fit options grouped by plate and slot.
- **Conversational model link recovery**: Affirmative follow-ups ("Let's do it", "Print that", "Go ahead", "Yes") automatically recover the recently discussed model URL from conversation history, eliminating prompts to resend links.
- **Test validation**: 213 unit and integration tests passing across geometry, adapter, multi-plate intake, and interaction guard suites.

### 1.9.0 — Spool lifecycle management and print orchestration

- **Spool lifecycle & usage suspension**: Mid-print filament runout and swap detection with debounced presence tracking, 10-minute continuous Discord nagging until confirmed, and automatic Moonraker filament usage charging freeze (`spool_id` cleared) during unconfirmed swaps to prevent charging either spool.
- **One-way Spoolman to AD5X screen sync**: Direct sync pushing Spoolman slot assignments, color hex, and material type (with safe coercion of unsupported screen types like `PLA+` to `PLA`) to the printer via Z-Mod macros; native screen changes never overwrite Spoolman.
- **Permanent chronological print numbering**: Fixed print IDs to guarantee permanent sequential print numbers across archive and history, ensuring `/print-again` identifiers remain stable and never shift when old jobs rotate.
- **Multi-copy reprint queuing**: Extended `/print-again` with copy multipliers (`xN` / `N copies`, up to 20), individual completion prompts, bed-clear confirmations between plates, and queue cancellation (`/print-again stop`).
- **Interactive Discord spool control**: Added `/spool` command suite (`/spool list`, `/spool change <slot> <spool#>`, `/spool new ...`, `/spool sync`).
- **Test suite validation**: 605 tests passing across local unit, klipper contract, and regression suites.

### 1.8.0 — Print Buddy public release

This initial public release consolidates previously shipped MVP work: Discord model intake, guarded preparation and print staging, the AD5X spool compatibility macro, and portable print feedback guards. It also includes the AD5X implementation contract and setup guidance. The current release changes the public project/repository name to Print Buddy; printer behavior is unchanged.

## Architecture and Pipeline

Print Buddy ties several open tools into a single conversational interface:

* **Discord Interface:** Powered by Hermes Agent in the `#3d-printer` channel.
* **Intake and Scraping:** Fetches model packages from MakerWorld and Printables or extracts uploaded attachments.
* **Headless Slicing:** Uses the OrcaSlicer Flatpak in CLI mode, applying calibrated printer and filament profiles.
* **Filament and Spool Inventory:** Queries Spoolman over LAN to match requested colors and materials against loaded slots.
* **Printer Control:** Sends G-code directly to Moonraker and Klipper over the local network.
* **Interaction Guards:** Python hooks prevent runaway agent command loops and enforce concise UI button choices.

## Hardware Support and ZMod Plugin

The live setup runs on a Flashforge Adventurer 5M / AD5X running ZMod Klipper firmware with an internal filament system (IFS).

### Spool Slot Matching Macro (`print_bitch.cfg`)

ZMod natively supports infinite spool switching during a print when an active spool runs out, provided another slot contains the exact same color and material.

The included `print_bitch.cfg` Klipper macro lets users check backup compatibility before a job begins:

```gcode
PRINT_BITCH SLOT=1
```

If slot 1 and slot 3 are both black PETG, the macro confirms:
```
PRINT_BITCH: black / PETG also on slot 3. ZMod can switch. This macro does not.
```

Querying `PRINT_BITCH COLOR=black MATERIAL=PETG` checks availability across all four slots without assuming an active toolhead.

### ZMod Plugin Installation

Run on the printer console:

```gcode
ENABLE_PLUGIN name=print-bitch
```

Add your slot assignments to `mod_data/user.cfg` in a `[gcode_macro _PRINT_BITCH_VARS]` block, then run `FIRMWARE_RESTART`.

Moonraker update manager entry:

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

## Repository Structure

* `print_buddy/core/`: Offline 3MF and STL helpers. No printer connection.
* `print_buddy/templates/orca/`: Example Orca machine, process, and filament JSON.
* `plugins/print-feedback/`: Small guards that limit clarify choices and repeated terminal loops.
* `print_bitch.cfg`: Klipper G-code macro for checking backup IFS slot matching. The macro name is historical. The project name is Print Buddy.
* `install.sh` / `uninstall.sh` / `update.sh`: ZMod plugin lifecycle scripts.
* `tests/`: Unit tests verifying macro logic and interaction guards without requiring physical hardware.
* `docs/`: Technical specifications for AD5X integration and upstream tool research.

## Running Tests

Run the test suite with standard Python:

```bash
python3 -m unittest discover -s tests -v
```

## Roadmap: Expanding to More Klipper Printers

* **TODO: Generic Klipper printer support.** The pipeline currently targets a Flashforge AD5X on ZMod, but the core intake, slicing, and Moonraker dispatch are printer agnostic. Adding other Klipper printers (such as Sovol, Voron, or custom beds) is architecturally straightforward:
  * Replace hardcoded bed dimensions (220x220) and nozzle parameters with configurable printer profiles.
  * Support single extruder workflows without multi spool IFS requirements.
  * Standardize start, cancel, and status calls using generic Klipper macros.
  * This is not difficult to implement, but requires thorough real world testing on physical hardware before claiming support.

## Links and Reference

* ZMod AD5X docs: [AD5X.md at 0017033](https://github.com/ghzserg/zmod/blob/001703371c90e228defce41bb4230b7fafd37fea/docs/en/AD5X.md)
* ZMod firmware project: [ghzserg/zmod](https://github.com/ghzserg/zmod)
* ZMod plugin guide: [wiki.zmod.link/Plugin](https://wiki.zmod.link/Plugin/)
* OrcaSlicer CLI documentation: [CLI mode](https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_mode)


