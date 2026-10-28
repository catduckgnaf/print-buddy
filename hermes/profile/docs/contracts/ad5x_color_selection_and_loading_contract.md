# Implementation & Loading Contract: Print Handy AD5X Selection & Validation

## 1. Executive Summary & Inventory
- **Hardware Architecture:** Flashforge AD5X running ZMod with a four-slot IFS feeder. Do not treat AD5M or AD5M Pro as equivalent. Configured Moonraker: `services.moonraker_url`, authoritative for read-only active-job phase, filename, progress, and queue. The stock detail adapter is authenticated `POST /detail` on port 8898 and is limited to IFS occupancy and native start-readiness. Do not use port 8898 as a general status API: unauthenticated `GET /`, `GET /status`, and `GET /detail` 404 by design. Spoolman: `services.spoolman_url`. These are existing endpoints, not instructions to add listeners.
- Evidence precedence is not a universal ranking and not “operator always right.” Assess each field using source semantics, mode compatibility, provenance, and timestamp. Freshness alone does not cure mode mismatch or stale/incorrect semantics. Keep unresolved critical facts unknown and block unsafe action without fabricating either presence or absence.


---

## 2. Owning Paths & Component Map
1. **Hardware State Single-Source-of-Truth:**
   - Path: `state/printer_hardware.json`
   - Role: Tracks installed nozzle (0.4mm), Moonraker/Spoolman URLs, active spool ID, and limits.
2. **State & Validation Utilities:**
   - Path: `python3 -m print_handy.core.printer_state`
   - Role: Live hardware cross-check against Klipper nozzle and Moonraker/Spoolman active spool.
3. **Model Intake, Slicing & Print Orchestrator:**
   - Path: `python3 -m print_handy.core.model_job`
   - Role: Manages fetch from MakerWorld/Printables, selection dialogue, OrcaSlicer invocation, G-code verification, upload, and print start via Moonraker.
4. **Print Logging & Context:**
   - Path: `print_handy/core/print_records.py`
   - Role: Writes print record notes and tracks context in `the context file under the state directory`.
5. **Klipper / ZMod Firmware Macros & Configuration:**
   - Moonraker REST endpoints: `/printer/objects/query?zmod_color&filament_switch_sensor%20head_switch_sensor&save_variables`
   - Config files: `mod/ad5x_config_off.cfg`, `mod/display_off.cfg`, `mod/generic.cfg`, `Adventurer5M.json`.

---

## 3. Current Behavior vs. Identified Root Causes

### A. Slot Data Verification & Stale / Unobservable State
- **How slots are currently represented in ZMod:**
  - In Klipper, the `zmod_color` object exposes `slots`: 4 elements (ID "1" through "4", 1-based indexing in ZMod UI).
  - Each slot reports: `ID`, `Material`, `Color`, `HEX`, and `hasFilament` (boolean).
  - Also, `zmod_color.channel` (0=unloaded/bypass, 1-4=active slot) tracks the currently fed slot.
  - Sensor endpoints: `filament_switch_sensor head_switch_sensor` and `zmod_ifs_switch_sensor head_switch_sensor` report `filament_detected`.
- **The Blind Spot / Flaw:**
  - In `python3 -m print_handy.core.model_job`, model slicing and verification assume a single-spool machine inherited from the Sovol SV06 (`st["spool"]["material"]`, `st["spool"]["spoolman_id"]`).
  - It checks `verify_gcode` against `st["spool"]["material"]` only.
  - It does NOT inspect `zmod_color.slots` or verify whether the required filament/color is actually physically present (`hasFilament == True`) in the assigned IFS slot.
  - When `hasFilament` is `false` or the sensor cannot verify loaded filament, previous code fell back to assuming whatever spool was last used or saved in `state/printer_hardware.json`.

### B. Legacy SV06 Spool Preference Leakage
- `printer_hardware.json` retains a single `"spool"` key (e.g., `#8 Sunlu Black PLA`).
- When slicing a model, `python3 -m print_handy.core.model_job` blindly pulls `st["spool"]["material"]` and replaces slicer tokens with that single spool.
- If a user requests a print or a model has multiple colors, the code had no concept of mapping tool numbers (T0, T1, T2, T3) to IFS slots (1, 2, 3, 4) or Spoolman spool IDs.

---

## 4. Supported Hardware & Loading Contracts (AD5X / ZMod)

### A. Numbering & Indexing Conventions
- Orca logical tools (`T0`, `T1`, ...) and physical IFS slots (`1`–`4`) are separate namespaces. There is no fixed `T[i] -> slot i+1` mapping. ZMod's color selection maps each logical tool to a chosen physical spool; its own AD5X documentation gives examples where `T0` maps to physical spool 4 and multiple tools map to one spool.
- The actual mapping is selected per print through the ZMod/native color-selection path. Do not infer it from tool index, `zmod_color.channel`, Spoolman active spool, or `currentLoadSlot` alone.
- `SET_EXTRUDER_SLOT SLOT=<1-4>` records which spool is already engaged; it is not a feeder load or tool-to-slot mapping command.

### B. Loading / Feeding Contract
- **Sensor Semantics:**
  - `hasFilament` in `zmod_color.slots[i]`: a reported presence flag whose reliability and source must be established for the installed screen mode. Native-mode audit found false values for all four despite native occupancy reporting all four present; do not label this verified optical sensor truth.
  - `head_switch_sensor`: reports presence at the extruder toolhead above the nozzle.
  - *Crucial Finding:* The head sensor is `filament_detected: false` when filament is staged in the IFS buffer or tube before `START_PRINT` or before an IFS load command (`_INSERT_PRUTOK_IFS` / `IFS_F10`) feeds it into the extruder!
  - Therefore, pre-start checks MUST NOT require `head_switch_sensor == True` if an automated IFS load sequence is configured to load the slot at start. Instead, pre-start checks MUST verify:
    1. The mapped physical feeder is available using verified, mode-appropriate occupancy evidence. Do not require ZMod presence flags in native mode when they conflict with native occupancy.
    2. The slot material matches the required slicer material.
    3. The slot is not empty or unassigned.
- **Physical Output Verification:** Neither `hasFilament` nor G-code extrusion commands guarantee melted plastic exits the nozzle. Proper pre-start contracts verify loaded status and report clearly without masking failures.

---

## 5. Dialogue & User Interaction Specification

### A. Rule 1: Fast Missing Color/Material Query BEFORE Expensive Operations
- Before downloading massive multi-part files or initiating OrcaSlicer:
  - If a user request specifies a model without indicating color/material, and the model profile metadata indicates specific colors or materials:
  - Check live `zmod_color` slots and Spoolman available spools.
  - Ask ONE concise English question:
    "Model requires [Material/Color]. Slot 1 has <color> PLA, Slot 2 has <color> PLA, .... Which slot or spool should be used?"
- Never reask if the user already explicitly specified the slot, color, or material in their prompt.

### B. Rule 2: Multicolor vs Single-Color Resolution
- If the model source contains multicolor plates/tools:
  - If unresolved, ask:
    1. `Preserve colors (use slots [X, Y, Z])` (Recommended)
    2. `Print single-color using [Slot N]`
  - Map necessary colors compactly into the OrcaSlicer tools.

### C. Rule 3: No Inferred State
- If ZMod presence is false or unknown, reconcile with native occupancy and installed mode before asking for physical loading. Do not reask the operator to load already confirmed feeders. Conflicting evidence remains unresolved; neither invent availability nor infer absence.

---

## 6. Implementation Architecture

1. **Update `python3 -m print_handy.core.printer_state`:**
   - Add inspection of `zmod_color` objects from Moonraker (`/printer/objects/query?zmod_color`).
   - Cross-reference IFS slots 1-4 with Spoolman inventory where mapped.
2. **Update `python3 -m print_handy.core.model_job`:**
   - In `fetch` / intake: inspect model metadata for multicolor tools and material requirements.
   - Dialogue handler: ensure the concise pre-download/slice question is triggered if ambiguous.
   - Slicer mapping: generate tool-to-slot mapping for OrcaSlicer (T0-T3 -> Slots 1-4).
   - In `verify_gcode`: reconcile required logical tool, physical slot, and material against mode-appropriate live evidence. Reject confirmed absence or material mismatch. An unreliable ZMod false flag alone does not establish native feeder absence.
3. **Regression Test Suite:**
   - Extend `test_model_job.py` to cover:
     - Missing color prompt before slice.
     - Retaining explicit color selections without re-asking.
     - Single-color vs multicolor plate resolution.
     - Pre-start verification blocking when mapped IFS slot is empty (`hasFilament: false`).
     - Allowing pre-start when head sensor is false but IFS slot sensor is true.


## Standing assumption
The operator states which IFS feeders are loaded and their colors in the local overlay MEMORY.md. Treat that as the baseline unless the operator reports a change or verified mode-appropriate evidence establishes one. ZMod presence flags that read false in native mode are not proof of empty feeders. Occupancy, nozzle engagement, logical tool map, RGB metadata and Spoolman ID are distinct evidence.
