---
name: klipper-3d-printing
description: Use when controlling Klipper through direct Klipper/Moonraker REST, handling print jobs, slicing, calibration, Spoolman, camera, or diagnostics.
version: 3.0.0
author: Print Buddy contributors
license: MIT
metadata:
  hermes:
    tags: [3d-printing, klipper, moonraker, fluidd, prusa-slicer, openscad, home-assistant, flashforge]
---

# Klipper / Moonraker & 3D Printing Operations

## Discord-first operating preference

the operator's preferred interface for model selection, filament choices, bed-clear approval, and print start is Discord. Use the Discord workflow as the single authoritative launch path; desktop/chat coordinate and report but must not create competing attempts. Keep printer replies concise, avoid duplicate confirmations, and preserve exact-once launch guards. This preference does not waive live hardware, current-job, filament, bed-clear, or print pipeline safety checks.

## Read-only status sources

Use Moonraker (`:7125`) for current print phase, active filename, progress, and queue. Moonraker alone is sufficient for a read-only current-job check. The stock firmware endpoint (`:8898`) is only for the existing authenticated `POST /detail` adapter used by IFS occupancy and native start-readiness. It is not a general status endpoint: never use `GET /`, `GET /status`, or unauthenticated `GET /detail`, and treat their 404 responses as expected rather than a printer failure.

## Mandatory AD5X evidence reconciliation
The feeders the operator lists as loaded stay loaded unless they report otherwise or verified mode-appropriate evidence establishes a change. Native-mode ZMod false presence flags alone do not overturn that baseline. Read `docs/contracts/ad5x_evidence_reconciliation.md` in this profile before resolving conflicting telemetry or selecting a slot. Distinguish feeder occupancy, nozzle engagement, logical tool mapping and color metadata. Preserve source/mode/timestamps; native API `printing` alone does not prove physical execution. The retained Ready job was Hermes-submitted and left pending, not started from the screen by the operator. Do not invent launch provenance. Slot 4 routing remains unverified; block uncertain launches without falsely reporting unloaded feeders.

For native `display_off=0`, never present `zmod_color.slots[*].hasFilament` or `filament_switch_sensor head_switch_sensor.filament_detected` as authoritative IFS feeder presence. These are ZMod/sensor readings; in the captured live native-mode sample the stock screen API `/detail` is unavailable (HTTP 404), and `zmod_color.ifs=false`, `zmod_ifs` has no Ports, while all four ZMod flags and the enabled head sensor read false. Preserve those raw readings and label feeder occupancy unknown/conflicted, not empty; the operator baseline remains loaded. Keep launch guarded when physical slot routing or occupancy cannot be established. An enabled head sensor reading false while `print_stats.state=standby` is an unloaded head before automatic IFS load, not a runout; during active execution, false remains a genuine runout guard. Readiness freshness is query time only, not sensor sample time. Z offset must name its mode-specific authoritative store: this live native-mode sample has `display_off=0`, saved `gcode_offsets.z=-0.005` (screenless store, not authoritative here), and stock `/detail` is unavailable, so native `zProbeOffset` is unverified. Do not call it absent or substitute the saved screenless value, probe trigger, or mesh status. Bed leveling, mesh availability, persisted user offset, and runtime offset are distinct.

For native `display_off=0`, never present `zmod_color.slots[*].hasFilament` or `filament_switch_sensor head_switch_sensor.filament_detected` as authoritative IFS feeder presence. These are ZMod/sensor readings; in the captured live native-mode sample the stock screen API `/detail` is unavailable (HTTP 404), and `zmod_color.ifs=false`, `zmod_ifs` has no Ports, while all four ZMod flags and the enabled head sensor read false. Preserve those raw readings and label feeder occupancy unknown/conflicted, not empty; the operator baseline remains loaded. Keep launch guarded when physical slot routing or occupancy cannot be established. An enabled head sensor reading false while `print_stats.state=standby` is an unloaded head before automatic IFS load, not a runout; during active execution, false remains a genuine runout guard. Readiness freshness is query time only, not sensor sample time. Z offset must name its mode-specific authoritative store: this live native-mode sample has `display_off=0`, saved `gcode_offsets.z=-0.005` (screenless store, not authoritative here), and stock `/detail` is unavailable, so native `zProbeOffset` is unverified. Do not call it absent or substitute the saved screenless value, probe trigger, or mesh status. Bed leveling, mesh availability, persisted user offset, and runtime offset are distinct.

## Current screenless operating contract

Follow [references/screenless-flow.md](references/screenless-flow.md) for the audited AD5X screenless workflow. It overrides generic historical examples below when the printer is actually screenless. Read display_off before treating either mode as current: display_off 1 means screenless, display_off 0 means the native screen is the offset and mesh owner. ZMod owns cleaning and probing startup. MESH=auto with PRINT_LEVELING=0 selects the saved mesh, and MESH_TEST permits only 0 or 1. User offset authority is the numeric value already persisted in save_variables gcode_offsets.z with LOAD_ZOFFSET=1. Do not require, restore, or inject a hardcoded magnitude. The native screen offset and the screenless offset are separate stored values; LOAD_ZOFFSET_NATIVE copies native into screenless and is a one-way overwrite, never a shared value and never a step on the way back to the screen. No automatic offset tuning or generic paper calibration.

## Native baseline and launch guards

In native screen mode, the captured calibration_baseline.native_mesh is the explicit slicer/startup mesh, not an implicit auto substitution. The adapter resolves filament RGB from the verified unique slot for the selected Spoolman ID, inserts single logical tool zmod_color_data, then prepends MD5 over the remaining exact bytes. Color metadata is not proof of physical feeder selection. Preserve native zProbeOffset, raw zLevelOffset, probe offset and screenless saved offset as separate stores.

The normal print-now path checks authenticated native POST /detail independently from Moonraker before approval consumption or upload. Native status `printing` alone is not proof of actual execution: an operator-reported screen-ready observation, native status, Moonraker state, heater targets, filename, and action history are distinct evidence and may conflict. The Oct 5 12:00:08 EDT native `printing` sample coincided with operator-reported Ready/no-error and Moonraker standby; the operator later explicitly identified that as Hermes having sent a job which was pending, not his having started it on-screen. That specific provenance supersedes interpretations in earlier audit prose; do not claim independently active printing. Similarly, distinguish idle, queued/pending, preparing, executing, completed, and canceled using source-specific signals. Reconcile samples by field, source semantics, mode applicability, timestamps, and provenance; freshness alone does not make a signal valid. Do not resolve conflicts by selecting whichever source has the highest presumed authority or supports the desired action. Preserve contradictory observations and their limitations. The verified later cancellation readback (native `cancel`, Moonraker `standby`, targets zero) establishes canceled/idle at its capture time, not prior start provenance.

Native slot occupancy is independent from active/engaged slot, per-job logical tool mapping, and spool/color metadata. the operator's standing physical report (kept in the local overlay MEMORY.md) says which feeders are loaded, and that holds unless they say otherwise or fresh, relevant, mode-correct evidence establishes a change. Do not ask him to load again merely because native-mode ZMod `hasFilament=false` conflicts with native occupancy; report the specific telemetry conflict. Native `slotInfos.hasFilament=true` proves firmware-reported occupancy only, not color correctness, logical T0 routing, or material in the nozzle. `currentLoadSlot` and `currentSlot` semantics for selection are not established by the installed read adapter alone.

The live read-only config source shows `SET_EXTRUDER_SLOT` forwarding to `_SET_EXTRUDER_SLOT`; screenless insertion macros call `IFS_F10`, `IFS_F23`, and record the slot, but these are not proof of native screen-mode route. Orca's one `zmod_color_data` marker is metadata, not a physical selector. ZMod's upstream AD5X guide says SILENT=0 shows selection dialog and SILENT=1 reuses prior colors; upstream issue #738 reports native-screen behavior depends on firmware/version and G-code versus 3MF launch path. Do not infer the installed native path from screenless macros or generic examples. Keep the physical-slot start guard until installed/current native start mapping is proven. A bare G-code launch without job selection does not satisfy native binding. Source ledger and evidence-limited conclusions: `state/research/20261005-ad5x-native-slot-routing/report.md` and `source-ledger.md` in the same directory.

Run the offline suite from the repo checkout with `python3 -m pytest tests`. If a test dependency is missing, report the exact invocation, interpreter, collection outcome, and first causal error, and keep unrelated suite failures separate from scoped results. Offline tests and verify-gcode passing do not establish native idle, logical-to-physical color routing or physical first-layer success.

## Reviewed launch without rediscovery

For an independently reviewed launch packet, load this skill once, hash the exact supplied artifact once, then use the supplied `python3 -m print_buddy.core.model_job print-now JOB.json` command once after current authorization and notification prerequisites are satisfied. That pipeline provides current busy-state, saved mesh/startup readiness, G-code/hardware, filament, upload and start readback gates. Do not separately repeat those checks or read command help when the packet already supplies syntax. Safety checks are delegated to the verified pipeline, not waived.

JOB.json must already point to existing local artifacts and contain the chosen filament. A missing path is a concrete packaging defect for the orchestrator; stop immediately rather than edit the manifest or launch a bare G-code file that loses job binding. Historic slicer command paths are provenance only, not current runtime paths.

Completion/failure notifications are optional conveniences under fleet policy, not a launch prerequisite. Do not block a reviewed launch merely because notification delivery is absent or unverified, and never promise a notification that has not been arranged. Service active status proves liveness only, not destination or delivery. Do not label all readiness checks complete while any actual safety prerequisite remains unresolved. No printer authorization is created by reset, prior success, or a fresh turn budget.

## Fresh plain-link intake and model binding

Every new plain MakerWorld or Printables URL event starts a fresh source-first intake. Honor a uniquely available URL profile hint, otherwise ask only necessary source selection. Download and inspect actual named geometry before color or slice/print approval. Same-event duplicates are idempotent; a new message never inherits previous color or launch permission. Configured slot labels do not establish physical readiness.

**Model name and URL discrepancy:**
- Never resurrect or suggest reusing a historical URL when the user mentions a model name (e.g. "Microfiber holder") that contradicts the title of the last fetched source (e.g. "Miniature Baroque Frame"). Prompt directly for the new model's URL or file attachment.
- When a user asks how to select among many profiles/files (e.g. 50+ options), explain that they can paste the direct profile URL (with `#profileId-<id>`), or specify the exact profile title, plate name, or file name.
- When the user says "Start over" or "STOP", immediately discard the active model context and wait for the new request. Never loop back to retry or re-fetch previous mismatched links.
- **Fresh file upload after cancellation:** A user re-uploading a file or sending a new attachment accompanied by instructions (e.g. "Prepare it", "Slice this") is a fresh intake event. Cancellation clears the prior pending intake session only; never treat a newly uploaded file as "the same canceled upload" or refuse to process it based on prior cancellation history.

The source-first hook persists canonical selections directly to the same source-bound JOB.json, then asks one local slice-only approval. SLICE_APPROVED authorizes `python3 -m print_buddy.core.model_job slice <exact job_json> --approved` once, not fetching again, duplicate color clarification or printing. COLORS_SAVED_STOPPED stops before agent dispatch. Never tell the user to run internal commands or supply paths or source indices. Legacy explicit /print-colors is recovery only. Preserve all historical jobs and calibration; source completeness, artifact binding and live execution gates remain mandatory.

## Source-bound multipart color selection

For normal intake, retain the exact fresh archived JOB.json and downloaded source. The native source-first dispatcher collects part choices once and saves source-hash-bound color_decisions using schema part_slots_v1. Unpainted geometry uses authoritative per-part slot assignments, not unused author palette rows. Distinct painted palette regions remain separate questions and unsupported segmentation slicing still refuses. Legacy jobs retain strict palette/part contradiction validation. Resume the ordinary `python3 -m print_buddy.core.model_job slice JOB.json --approved` only after the exact local slice approval; callbacks never slice, upload or launch. Changed choices invalidate readiness and retain historical artifact metadata; unchanged choices are idempotent. Successful slices bind source SHA256, canonical decisions digest and G-code SHA256. Stale JOB launches fail before approval consumption or upload. Unique reslice directories preserve historical successful artifact bytes.

Per-part slicing uses core 3MF mesh leaves with nested transforms and build instances preserved, one rigid centering/bed translation, deterministic logical-tool-to-slot mapping and one filament preset per tool. The filament_is_support array is mandatory in each Orca preset. Author process settings, native checksum/startup and existing launch guards remain enforced. Painted triangles, mixed materials, contradictory palette/part selections and invalid or changed sources fail closed rather than flattening colors. Single-color mode is explicitly chosen, not a fallback.

Offline Discord UI/callback tests use the installed adapter with fake transport, not live posts. Slicer verification with saved state and mocked display mode does not establish printer readiness, physical feeder mapping or print success. Live rendering requires a separately authorized Discord test message; production acceptance and gateway plugin activation belong to the specialist after independent review. No renewed print authorization is implied.

## Canonical AD5X Orca slicing

Normal `python3 -m print_buddy.core.model_job slice JOB.json --approved` and `prepare-first-layer` now use only the installed OrcaSlicer Flatpak. No Prusa slicing fallback or selectable Prusa engine remains. `scripts/orca_adapter.py` resolves AD5X JSON presets into each job and hashes source, transformed geometry, G-code and all configurations. Prusa `--info` in `audit` is a separate read-only geometry inspector, never slicing.

Legacy INI templates are retired in `templates/retired-prusa/` for forensic reproduction only. Historical Prusa examples below describe old evidence, not new-job instructions. Preserve author structural layer/wall/infill/support/brim intent, but use AD5X motion/material presets and installed ZMod macro compatibility. All 3MF build/component triangles and transforms are retained before one rigid centering/bed translation; float32 STL conversion rounding is recorded. A multi-plate 3MF is merged onto one bed by default (see Multi-plate slicing safety).

Do not filter gap infill to pass a wall-width gate. Narrow gap transitions are legitimate geometry, not proof of starved walls. The limited structural-width gate excludes that role; it is not physical flow calibration. Installed START_PRINT owns heating and mesh startup. Screenless mode with LOAD_ZOFFSET=1 uses the saved save_variables gcode_offsets.z. Native mode (display_off=0) skips that load and relies on the stock startup path, where the native adjustment is stored in leftExtruderOffset.zProbeOffset rather than general.zLevelOffset. Installed START_PRINT explicit Z_OFFSET can override native if supplied; do not guarantee applied runtime merely from reading the native file. Preserve separate stores without LOAD_ZOFFSET_NATIVE or copying. In native mode, PRINT_LEVELING=0 and explicit MESH=auto can still load Klipper saved auto per installed _START_PRINT, so do not universally assert the screen owns the mesh regardless of arguments. The native physical path remains unvalidated. No leveling override is injected. Force protection remains 1500 g. Blank active standby mesh alone is not a defect.

Candidates require independent generator/hash, geometry/process parity, all-layer bounds, startup and IFS review. Offline validation never authorizes upload/start. Live filament/mesh and physical clearance remain specialist/operator checks.


## Supervised AD5X bed mesh

Use ONE installed `moonrakerctl mesh-run` command with the exact syntax and continuation rules in [references/bed-mesh-routine.md](references/bed-mesh-routine.md). This includes receipt, one initial fail-closed safety query, verified heating/homing/probing, bounded cooldown, persistence and applied mesh readback. Reuse the existing backup, old mesh, and reviewed interface. A finished `failed_cooldown_verified` directory stays untouched; the next attempt uses a new state directory. Do not resume a `*.pending` checkpoint, rediscover macros/source, repeat help/status/receipt/backups or hand-roll calibration. Stop after two identical terminal attempts. A guard refusal is the result: report it, do not route around it with another tool. Only this routine's checkpoint establishes completion, not `routine-status` idle alone.

## Fast direct Moonraker control

The Klipper MCP was intentionally retired. Do not attempt port 8010, do not wait for MCP discovery, and do not reinstall its daemon. The useful behavior lives here as direct Moonraker calls, without making every heater change attend a committee meeting.

Use the executable wrapper:

```bash
CTL=bin/moonrakerctl

$CTL status
$CTL temps
$CTL heat-hotend 150
$CTL heat-bed 60
$CTL heat PLA_PLUS
$CTL cool
$CTL history 10
$CTL files
$CTL metadata 'file.gcode'
$CTL tmc
$CTL spool
```

Rules:

1. Prefer `moonrakerctl` over ad hoc code for ordinary commands. It uses `curl` and `jq`, has no service or Python runtime, and reads back state after heater changes.
2. Heating commands are nonblocking. Use `wait-temp` only when the operation genuinely requires temperature before the next step.
3. Direct G-code calls use a separate 300-second timeout because Moonraker's `/printer/gcode/script` response is synchronous. Homing, meshes, calibration, and macros may legitimately take longer than the ordinary 15-second REST timeout. A client timeout does not prove the command failed; query `webhooks`, `toolhead`, `gcode_move`, and `gcode_store` before deciding what happened.
4. `home`, `start`, mesh calibration, and any Z-down motion retain the existing physical safety gates. The wrapper is transport, not permission. Use `$CTL home ...` instead of raw `gcode G28`; it waits with the long G-code timeout and returns both `toolhead.position` (physical coordinates) and `gcode_move.gcode_position` (logical coordinates).
5. the operator's standing printer rule remains: a positive relative Z raise is preauthorized; never home or move X or Y without the required explicit intent or approval. Heater changes must be explicitly requested or unambiguously required by an already approved print or calibration workflow. Do not confuse a faster command path with a license to reenact industrial sabotage.
6. `cancel` forces both heater targets to zero. Verify live state before reporting cancellation or cooldown.
7. High-risk host operations and deletion require a literal confirmation token in the command. Updates, restore, reboot, shutdown, TMC writes, and arbitrary service restarts are not routine shortcuts.
8. In Klipper, `toolhead.position` and `gcode_move.gcode_position` answer different questions. A configured `position_min: -4` makes `-4` a legal physical coordinate and does not itself show a failed home. Never compare one object's position to the other as if they were the same coordinate system.
9. Shell text `"G91\nG1 ..."` contains literal backslash characters. For multiline G-code, use ANSI C quoting (`$'G91\nG1 ...'`) or wrapper commands such as `raise-z`, which serialize real newline bytes.

Coverage retained from the retired MCP:

| MCP capability | Direct replacement |
|---|---|
| status, temperatures, G-code, heaters | `status`, `temps`, `gcode`, `heat-*`, `cool`, `wait-temp` |
| start, pause, resume, cancel, history | `start`, `pause`, `resume`, `cancel`, `history` |
| files and metadata | `files`, `metadata`, `upload`, raw `/server/files/*` for config reads |
| bed mesh | `mesh`, `mesh-load`, `mesh-clear`, `mesh-calibrate`, `mesh-save` |
| TMC diagnostics | `tmc`, `tmc-dump`; writes remain explicit raw G-code only |
| camera and timelapse | `camera-snapshot`, `webcams`, `timelapse` |
| Spoolman | `spool` plus direct Spoolman REST for inventory writes |
| server and system diagnostics | `objects`, `gcode-store`, `system-info`, `proc-stats`, `updates` |
| Klipper restart and emergency stop | `klipper-restart`, `firmware-restart`, `emergency-stop` |
| config backup | `backup-config DIR` |
| updates, service, reboot, shutdown | confirmation-gated `update`, `service-restart`, `reboot`, `shutdown` |
| toolchanger and LED effects | not installed on this printer; use direct macro or object calls only if future hardware exposes them |
| notifications and TTS | Hermes, Discord, Home Assistant, and existing completion watcher, not the removed MCP |
| G-code analysis | `python3 -m print_buddy.core.model_job verify-gcode`, Moonraker metadata, and local shell inspection |

The MCP's claimed 100 plus tools were mostly thin aliases around the same Moonraker endpoints, plus generic Voron and StealthChanger features this Klipper does not possess. Preserve capability, not ceremonial tool count. See `references/direct-moonraker-capability-map.md` for the complete feature-family audit and direct replacement paths.

MakerWorld is directly accessible from this profile. Use this retrieval order for every MakerWorld link: direct MakerWorld access, then the local 3D print archive and cache. Retrieve the complete model metadata, all available print profiles, plates, downloadable files, author settings, and assembly instructions directly first. Never ask the user to download or upload MakerWorld files. If both retrieval paths fail, report the exact failure and stop. Historical notes claiming MakerWorld is inaccessible are obsolete and must not override this procedure.

**Mandatory MakerWorld two-pass completeness audit:** Before slicing, uploading, or printing, first inventory the source-level profiles, plates, files, named parts, and assembly instructions. Then inspect the selected 3MF/archive internally and count plates, build items, objects, component meshes, named parts, and disconnected mesh components. A single downloaded file or selected profile is not proof of a single-part model. Compare both inventories and explicitly classify the source as `Confirmed single-part model`, `Confirmed multi-part model`, or `Completeness unresolved`. State the evidence before proceeding. For multi-part models, create and retain a named part checklist and print order until every part completes or the operator explicitly cancels the remainder. Do not print if completeness is unresolved. Repeat this audit even for cached artifacts and links whose selected profile appears to contain one plate.

Use this skill when managing FDM 3D printers through Klipper and Moonraker, performing remote calibration and slicing, inspecting prints via camera feeds, or integrating print telemetry into Home Assistant dashboards.

## Hardware References & Specifications
Primary source of truth for Klipper 3D Printer hardware specs, pinouts, and part replacements: `https://github.com/bassamanator/ad5x-klipper` (indexed in the optional memory plugin). Secondary: Blakadder Klipper 3D Printer wiki.

### Current installed stack, mandatory pre-print baseline

**Live hardware is mandatory.** The persistent record is `state/printer_hardware.json`. Do not hardcode or assume an old nozzle, filament, or Z offset from historical notes. Always read `state/printer_hardware.json` and check it against live Klipper via `python3 -m print_buddy.core.printer_state check`.

Before every fetch, slice, G-code reuse, upload, and print start, run `python3 -m print_buddy.core.printer_state check`. It checks the persistent record against Klipper's live nozzle diameter and Z offset, Moonraker's active spool, and Spoolman's record. **Refuse the job on a nozzle or Z offset mismatch.** Moonraker's active spool is an accounting pointer left by the last job, not physical filament: when a job names an IFS slot, the slot's own mapping decides, and `print-now` moves the pointer to that slot's spool before upload. Never block a slot-selected job because the active spool differs; let `print-now` decide and report only its own refusal.

**Automatic Hardware Swaps and Sync:**
When the operator tells you in Discord or chat that he swapped or changed the nozzle or filament (e.g., "changed to 0.4", "swap done", "all done", "new nozzle installed", "you tell klipper"):
1. **Never stall, refuse, or claim you cannot edit Klipper config.** Do not dump manual instructions or tell the operator to edit `printer.cfg` himself.
2. **Invoke `python3 -m print_buddy.core.printer_state set --nozzle <size> --nozzle-type "<type>"` immediately.** This updates `printer_hardware.json`, writes the new `nozzle_diameter` to Klipper's `printer.cfg` via Moonraker API, issues `FIRMWARE_RESTART`, and marks `z_offset` unverified.
3. **Do not automatically actuate after a hardware report.** Obtain current physical presence, bed-clear and hands-clear authorization before heating or homing. A maintenance report is not motion authorization.
4. **AD5X screenless calibration:** Use the supervised mesh routine and reviewed screenless interface. ZMod `AUTO_FULL_BED_LEVEL EXTRUDER_TEMP=220 BED_TEMP=60 PROFILE=auto SAVE=0` owns heating, nozzle cleaning, homing and load-cell preparation; the runner verifies points before persistence. Do not substitute raw probing at 150 °C or generic PROBE_CALIBRATE/TESTZ instructions.
5. **Offset authority:** Preserve the numeric saved `gcode_offsets.z` with `LOAD_ZOFFSET=1`. Do not require or restore a hardcoded magnitude. `probe.z_offset` is not the user offset. A nozzle change invalidates physical calibration and needs documented measurement/first-layer validation; do not mark it verified merely by copying a configuration number. Do not reimport native offset after a new measured calibration.
6. Long synchronous macros require bounded transport and checkpoints. A timeout does not cancel server-side motion; reconcile before any replay.

### Multi-plate slicing safety

`python3 -m print_buddy.core.model_job plate-manifest SOURCE.3mf` provides a read-only inventory of plate IDs, names, assigned object IDs, and the source SHA256. This does not slice or authorize an old project. The current machine is the Flashforge AD5X. Verify nozzle diameter against live Klipper and installed hardware records before slicing. Do not inherit former-printer hotend or nozzle specifications from print history. `python3 -m print_buddy.core.model_job slice` merges every object from every plate of a multi-plate 3MF by default: one shelf-packed layout on one 220x220 bed (8 mm edge margin, 10 mm spacing, prime tower strip reserved when more than one slot is used), sliced once into ONE G-code, with all parts accounted for before the artifact is bound. It splits into one G-code per source plate and slot, with the reason printed and saved in `JOB.json` `plate_merge.reason`, only when: the parts do not fit one bed, they need more than the 4 IFS slots or mixed materials, painted regions span several slots, the 3MF notes ask for separate printing, or the merged estimate exceeds 12 h. `slice --separate` forces the split. A merged job reports plates in, objects in and out, spacing and fit in `plate_merge`; an unreadable multi-plate source still fails closed with a multi-plate error. It cross-checks the cached audit against plate thumbnails and `Metadata/model_settings.config`; a PrusaSlicer success without a nonempty output G-code is also an error. A refusal is **not** evidence the project was sliced. Preserve the author's plate and part manifest, verify every part separately, and tell the operator what remains. Do not bypass this guard by editing the audit or renaming the archive. Do not restore cancelled Råskog files or infer a new authorization from an old job. Before enabling an automated plate workflow, validate OrcaSlicer's documented `--slice` and local printer, process, and filament presets against real multi-plate fixtures offline, then perform the full G-code verifier on every result. OrcaSlicer 2.4.2 CLI successfully exported source plate 1 using the embedded Bambu A1 mini profile, but that G-code was rejected for this printer. Loading an offline Klipper 3D Printer 0.4 mm Klipper preset against the same source returned `The selected printer is not compatible with the 3mf` (return code -16). Treat this as an unresolved source compatibility gate, not permission to use `--no-check`, ship the Bambu output, or claim the project was sliced for the Klipper 3D Printer. Never run the experimental path against the printer or upload a file merely to test slicing.

### OrcaSlicer calibration and optimization guide

Source: [OrcaSlicer Calibration Guide](https://github.com/OrcaSlicer/OrcaSlicer/wiki/calibration_guide). This is an ordered, **opt-in physical test workflow**, not authorization to heat, home, move, upload, print, or overwrite a live preset. First identify the installed nozzle, active spool and material, bed surface, and current Klipper configuration from live state. Capture baseline temperature, volumetric limit, flow ratio, pressure advance, retraction, acceleration, and input shaper values. Keep a dated per-spool/material and nozzle test record with the slicer version, chosen range, result, and rollback values. Do not borrow a prior spool's calibration as a current setting. Preview each generated calibration G-code, run the live G-code verifier, and obtain the normal bed-clear and print-start confirmation for **each** physical test.

Orca's recommended order is **temperature → max volumetric speed → pressure advance → flow ratio → retraction → cornering → input shaping → VFA**. Tolerance is a separate fit test. Measure one variable at a time, assess actual print quality and adhesion, and save a result only after the operator confirms the physical outcome. Temperature and volumetric tests establish the safe operating envelope before optimizing speed. Pressure advance and flow ratio tune extrusion; then retraction addresses stringing. Cornering, input shaping, and VFA depend on the actual machine and Klipper configuration: inspect existing Klipper values first, and do not copy Marlin jerk values into Klipper or run motion calibration without explicit approval. Apply a conservative limit below observed failure rather than treating a tower's highest surviving segment as a guaranteed production speed. Never silently write calibration values to printer config or a production filament preset. Record what remains untested and revert to the captured baseline on a bad result.

For offline multi-plate CLI validation consult [CLI mode](https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_mode), [CLI actions](https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_actions), and [CLI misc](https://github.com/OrcaSlicer/OrcaSlicer/wiki/cli_misc). `--slice 0` means all plates, whereas `--slice i` selects plate `i`; `--load-settings` loads process and machine JSON, `--load-filaments` loads filament JSON, and `--outputdir` directs exports. Do **not** assume a source 3MF's Bambu printer or G-code is compatible with the Klipper 3D Printer. OrcaSlicer is installed only as the Flathub Flatpak `com.orcaslicer.OrcaSlicer` (user install; never an AppImage). Invoke the CLI as `flatpak run --command=orca-slicer com.orcaslicer.OrcaSlicer ...` or `flatpak run com.orcaslicer.OrcaSlicer ...`; the sandbox sees `$HOME`, so keep inputs and `--outputdir` under home. Validate that Flatpak executable and locally exported Klipper 3D Printer machine, process, and filament presets; confirm exact plate indexing and output names from a disposable offline fixture before adding executable support to `python3 -m print_buddy.core.model_job`. Verify each output is nonempty, contains only its selected plate, and passes `verify-gcode` against current hardware. Do not turn on `--no-check` to make an invalid slice pass. Offline first-layer generation supports `--slicer orca`, generating a compliant single-layer G-code artifact via validated Flashforge AD5X Orca presets (`templates/orca/`).

### Native canceled-idle and backup reconciliation

the operator's standing rule: the agent always clears native on-screen errors itself (FIRMWARE_RESTART, then installed ZMod `REBOOT` via gcode script once Moonraker is standby with zero heater targets); never ask the operator to tap the screen. Clearing an error is not a print retry: after a nozzle-hit shutdown, report and do not relaunch without his go.
Read `docs/contracts/ad5x_native_idle_and_launch.md` in the printer profile before clearing a retained native job or launching mapped multicolor. Native `cancel` can be successful cleared idle, not a stuck job. Require `native_idle.require_idle` corroboration with Moonraker standby, all heater targets zero, empty native error and zero progress/duration. Never force `ready` by reboot or offset resets. Keep legacy filename-only route guards intact. `TAR_CONFIG` returns a versioned archive filename; use the actual gcode-store completion, verify native parameter and variables coverage, and keep backups private. Silent explicit mapping and uncertain `flowCalibration=true` authorization are separate gates; confirmed idle is not confirmed printing.

### Selection consistency and bounded diagnosis

Keep physical color, requested IFS channel, configured channel labels, and Spoolman accounting separate. Never resolve a missing spool ID from the globally active spool: `python3 -m print_buddy.core.model_job` resolves it only from the requested slot, refuses conflicting IDs/color/material before source downloads, and rechecks before slicing or print dispatch. If no slot mapping exists, provide an explicit verified Spoolman ID. Slicing with a selected slot refuses when its spool differs from the verified active spool, rather than borrowing the active spool's material preset. Do not update inventory merely to make a refusal disappear; reconcile it with physical evidence.

Stop after two identical terminal attempts on the same step. A guard refusal is the result: report cause, impact, and the one decision needed, and do not route around it with another tool or a rewritten command. Long-running routines use the event listener rather than an agent polling loop. Do not recommend an unverified macro or infer a historical Z-height cause from current telemetry. Returning to the native screen is a separate, explicitly authorized migration: DISPLAY_ON makes the screen the offset and mesh owner, and it must not be preceded by LOAD_ZOFFSET_NATIVE. Confirm LAN-only mode first, because a return from Helix or Guppy has left AD5X unable to start prints. Rollback is DISPLAY_OFF, and the screenless offset must be treated as possibly gone.

### Existing model-job helper

`python3 -m print_buddy.core.model_job` subcommands are strictly `{fetch, slice, filament-select, color-plan, color-select, filament-status, finalize-gcode, verify-gcode, print-now, routine-receipt, routine-status, plate-manifest, record-start, prepare-first-layer}`. It does NOT have a `history` subcommand — use `moonrakerctl history [N]` for print history.

`python3 -m print_buddy.core.model_job print-now <JOB.json or local G-code>` requires an existing **local** file path. It validates and uploads the artifact to Moonraker before launching. Remote filenames reported by `moonrakerctl files` reside on the printer (`/usr/data/gcodes`), not locally. Passing a bare Moonraker filename to `print-now` fails with `REFUSED: no G-code at <cwd>/<filename>`. When an interrupted job has returned to standby and local artifacts are missing from `~/3d-prints`, do not repeatedly attempt `print-now` with remote filenames; ask the user for the model link or local project file to perform a fresh fetch and slice.

For MakerWorld or Printables, use `python3 -m print_buddy.core.model_job fetch URL`: it does the source inventory, stores `JOB.json`, and stops before slicing. Never use a site supplied G-code or Bambu profile on this Klipper 3D Printer. After the operator selects the exact numbered source and explicitly approves slicing, use `python3 -m print_buddy.core.model_job fetch URL --select N --approved` or `python3 -m print_buddy.core.model_job slice JOB.json --approved`. To start a print, the job also needs an explicit filament selection: add `--filament-slot S --filament-color C --filament-material M`, or run `python3 -m print_buddy.core.model_job filament-select` first. Without one, `--print-now` is refused. Never reuse a previous job's selection; ask the operator if any value is missing. It reslices only the selected STL/3MF using the live verified hardware. `fetch` and `slice` never upload or start; only `print-now` (or `--print-now` after an exact bed-clear authorization) does, through its own launch gates.

**Proven fast path (iPad stand test: 3 commands instead of 43 calls):**
1. `python3 -m print_buddy.core.model_job fetch URL` → report the numbered sources, the part audit, and the time estimate. Stop and wait for selection plus approval.
2. `python3 -m print_buddy.core.model_job fetch URL --select N --approved` → writes `sliced/<slug>_klipper_<live-nozzle>_<spool>.gcode` and `JOB.json`. Never infer the nozzle from the filename example or a prior print.
3. Before upload, run `python3 -m print_buddy.core.model_job verify-gcode FILE`. It refuses any G-code whose embedded `nozzle_diameter`, `filament_type`, or `PRINT_START BED= HOTEND=` do not match live state. Previously sliced files for another nozzle or material **fail this check by design**. Reslice them; never force them.
4. Upload and start only after explicit authorization for the exact current file and bed-clear confirmation. Check `print_stats.state` and queue first, upload the verified G-code, then start that same filename. Confirm `print_stats.state=printing`, filename, and heater targets against the **current verified job settings**, not a hardcoded historical temperature. An idle printer is not authorization to start.
5. **print record print record (mandatory, same turn as the confirmed start):** `python3 -m print_buddy.core.model_job record-start G --started-at "$(curl -s $M/server/history/list?limit=1\&order=desc | jq -r '.result.jobs[0].start_time|todate')"`. This writes a dated note to the dedicated vault `the print records folder` with the start time (ET), title, source URL, nozzle, spool, temps, estimate, and key slicer settings, and registers it in `~/.print_buddy_context.json`. The completion watcher then finalizes that same note on complete, cancel, or error, adding the finish time, actual duration, and filament used. Include the note path in the start reply. If `record-start` fails, say so in that reply; never skip it silently.
6. **Outcome follow-up:** when the operator reports how a print came out (success, warping, stringing, failed layer, reprint needed), append that verbatim under `## Result` in the print's note (find it by G-code name in `Prints/`). Do not change the frontmatter or other sections: finalized notes are records, not drafts. For prints started outside this workflow (Fluidd or Mainsail), run `record-start` as soon as you notice them.

**Site profiles are metadata, not settings.** MakerWorld profiles are Bambu presets, often for a different nozzle or material. A mismatch is not a refusal reason. The script prints `SITE PROFILE NOT REUSED` and reslices the geometry for the **live verified nozzle and active spool**, never a remembered 0.6 mm setup. Choose the source by geometry and part completeness, not by the site's nozzle label.

**Geometry audit libraries:** system python3 has numpy 2.3.5, scipy 1.16.3, trimesh 4.5.1, and networkx 3.2.1 (apt). Use `trimesh.load(path, force="mesh")` plus `.split(only_watertight=False)`, `.is_watertight`, and `.extents` for body count, manifold checks, and dimensions. Do not pip install into the system python.

**Offline 3D model render / visual preview:**
When asked to preview or render what a model looks like without slicing or printing:
- Use OpenSCAD with xvfb for headless rendering: `xvfb-run -a openscad --autocenter --viewall --imgsize=1200,900 --projection=o --colorscheme=Tomorrow --render -o /path/to/preview.png /path/to/model.stl`
- Do not attempt interactive Python GUI viewers (`trimesh.Scene.show()`, `pyglet`), which fail on headless servers.
- Send the rendered image directly via `MEDIA:/path/to/preview.png`.
- Reassure the user that the render is strictly an offline visual preview and no slicing, upload, heating, or motion was initiated.

## THIS PRINTER RUNS KLIPPER — READ FIRST

| What | Where |
|---|---|
| Fluidd UI | `http://HOST:80` |
| Moonraker API | `http://PRINTER_HOST:7125` (no API key) |
| Camera snapshot | `http://PRINTER_HOST/webcam/?action=snapshot`; camera relay `http://HOST:1984/api/frame.jpeg?src=printer` |
| Klipper config | Moonraker `config` root: `/usr/data/config` on the AD5X |
| G-code files | Moonraker `gcodes` root: `/usr/data/gcodes` on the AD5X |
| MCU serial | `/dev/ttyS2` on the AD5X; verify from live config before changes |


- **The only live Klipper config is `printer.cfg` at the config root** (plus its includes: `printer.base.cfg`, `mod/`, `mod_data/`). The `rw/` folder is ZMOD's link to the read-only factory firmware defaults (`/usr/prog/config`, 1969 timestamps, 0.3 mm nozzle, different PIDs). Klipper never loads it. Never read values from `rw/`, never edit, sync, or delete it, and never report a `rw/` value as a current setting. Live values come from `printer/objects/query?configfile=settings` or the object itself (for example `extruder=pressure_advance`).
- **Uploading a config file:** `curl -s -X POST "$M/server/files/upload" -F root=config -F "file=@edited.cfg;filename=printer.cfg"`. The upload filename must be the target name. Do not send a `path` field containing the filename: Moonraker treats `path` as a directory and fails with HTTP 500 `NotADirectoryError`. Diff against the downloaded original first so only the intended line changes. `diff` exits 1 when files differ, so under `set -e` run it as `diff -u a b || true` or the script dies before the upload and looks like an upload failure.
- **There is no EEPROM.** `M500`/`M501`/`M503` do not exist. Calibration lives in an auto-generated `#*#` block at the bottom of `printer.cfg`, written by `SAVE_CONFIG`, which **restarts the firmware**. Never hand-edit that block.
- **`M851` does not exist.** The probe offset is `[probe] z_offset` in config; runtime adjustment is `SET_GCODE_OFFSET Z=`, and the calibration wizard is `PROBE_CALIBRATE` + `TESTZ`, ending in `ACCEPT` then `SAVE_CONFIG`.
- **`M420`/`G29` do not exist.** Meshes are `BED_MESH_CALIBRATE`, `BED_MESH_PROFILE LOAD=default`, `BED_MESH_OUTPUT`. A mesh is not automatically applied after `G28`; the start G-code (or `PRINT_START`) must load it.
- **Use only AD5X macros verified in the live object list.** The current printer exposes `START_PRINT`, `END_PRINT`, `AUTO_FULL_BED_LEVEL`, and `BED_LEVEL_SCREWS_TUNE`. It does not expose `G34`; never use old gantry top-stop alignment instructions on this machine.
- **Config errors are fatal and visible.** Klipper refuses to start on a bad config and reports the exact line over the API. Check `printer.info` / `server.info` state before assuming hardware trouble.
- **Do not import old inductive-probe assumptions.** The AD5X/ZMod config currently exposes `[probe]` on `!PB3`, zero X/Y offsets, and `LOAD_CELL_TARE`. Follow the AD5X/ZMod leveling workflow, not sensor-bracket relocation or an old machine's paper-calibration recipe. Read current config before calibration; nozzle cleanliness matters.

Generic G-codes (`G28`, `G1`, `M104`, `M140`, `M114`, `M83`) still work — Klipper emulates them. Anything Marlin-specific does not.

### Moonraker API essentials

```bash
M=http://PRINTER_HOST:7125
CTL=bin/moonrakerctl

# Prefer the fast wrapper for routine operations
$CTL status
$CTL temps
$CTL gcode 'G28'

# Raw endpoint examples remain valid for uncommon operations
curl -s "$M/printer/objects/query?print_stats&toolhead&extruder&heater_bed&gcode_move"

# Klippy health — 'ready' vs 'error'/'shutdown' (report state_message on error)
curl -s "$M/server/info"; curl -s "$M/printer/info"

# Run a G-code command or a Klipper macro (same endpoint)
curl -s -X POST "$M/printer/gcode/script?script=G28"
curl -s -X POST "$M/printer/gcode/script?script=BED_MESH_CALIBRATE"

# Emergency stop, then the REQUIRED recovery (estop latches until firmware restart)
curl -s -X POST "$M/printer/emergency_stop"
curl -s -X POST "$M/printer/firmware_restart"

# Files, job control
curl -s "$M/server/files/list?root=gcodes"
curl -s -X POST "$M/printer/print/start?filename=foo.gcode"
curl -s -X POST "$M/printer/print/pause"   # /resume /cancel

# Upload
curl -s -F "file=@out.gcode" -F "root=gcodes" "$M/server/files/upload"
```

`gcode/script` **blocks until the command finishes**. A `BED_MESH_CALIBRATE` or other long calibration call will hold the HTTP connection for minutes. Set a long curl timeout and do not interpret the wait as a hang. This replaces the whole legacy "poll serial.log for `Recv: ok`" dance; when the call returns, the move is done.

Errors come back as `{"error": {"message": "..."}}` with HTTP 400 and are explicit (`Must home axis first`, `Probe triggered prior to movement`). Read the message instead of guessing.


### AD5X calibration workflow

Calibration is not a prerequisite for every routine print. Preserve known-good settings unless evidence shows a problem.

1. Confirm the bed is clear, printer is idle, and the requested calibration is authorized.
2. Read current config and macro definitions. Use the AD5X/ZMod calibration skills; do not import another printer's gantry, probe, screw layout, or offset recipe.
3. Execute only the requested calibration with its documented thermal and homing requirements. Verify the resulting state before another action.
4. Save only when required by that procedure. `SAVE_CONFIG` restarts firmware and clears homing; never issue it during a print.

For screw adjustment, the current config declares `CW-M3`. Verify live screw coordinates and actual physical response before instructing turns. Do not reuse old parking coordinates or assume a center screw exists. Numeric offset values alone do not establish whether calibration is valid.

### Native Moonraker requirements

- No API key header is needed. Sending `X-Api-Key` is harmless but pointless.
- There is no `serial.log` to tail. Discover the live logs through `/server/files/roots` and `/server/files/list?root=logs`; the current log root is `/usr/data/logs` on the AD5X.
- Do not send `M500` after a calibration. It silently does nothing; the value is lost on restart and you will believe it was saved.
- Cancelling a non-job routine: there is no HTTP 409 problem. `emergency_stop` works any time, but **always follow it with `firmware_restart`** or every later command returns `Klipper is shutdown`.


## Print Failure Differential Diagnosis

When the user reports "the printer is broken," establish whether the *machine* changed or the *G-code* changed before touching hardware, calibration, or filament. Full procedure and the Klipper 3D Printer silk-PLA reslice recipe are in `references/print-failure-triage.md`.

1. **Pull the job history first.** `moonrakerctl history` lists recent jobs with their filename and terminal state. If *some* files completed while *others* failed in the same period, the printer is fine and the slicing profile is the suspect. A machine fault fails everything indiscriminately; a profile fault fails one file repeatedly.
2. **Diff the embedded slicer configs, not the hardware.** PrusaSlicer appends its full configuration to the end of every G-code file as `; key = value` lines. Compare a known-good file against the failing one and read the delta as the hypothesis:
   ```bash
   grep -aE '^; (brim_width|skirts|retract_lift|first_layer_speed|perimeter_speed|travel_speed|first_layer_temperature|first_layer_bed_temperature|filament_type|fill_density) = ' good.gcode failing.gcode
   ```
   Present the delta as a table. A failing profile that dropped brim, dropped Z-lift, and raised first-layer/travel speed relative to a profile that printed successfully on the same machine is a complete diagnosis; no calibration is warranted.
3. **A slicer-profile diagnosis can be simultaneously correct and not the root cause.** A profile that dropped brim and Z-lift while raising speeds genuinely does cause detachment, and fixing it genuinely does improve the result — but partial improvement is not confirmation. If the reslice visibly helps and the print still fails, the profile was a real *contributing* defect layered on top of an unfound fault. Do not treat the improvement as validation of the theory; re-open the diagnosis and consider hardware.
4. **Confirm the machine is innocent before saying so.** Read `/printer/info`, query `probe`, `bed_mesh`, `toolhead`, `extruder`, and `heater_bed`, then inspect recent G-code responses with `moonrakerctl history`. State the actual firmware state, probe offset, loaded mesh, temperatures, and homing state when clearing the hardware.
5. **Ask the user what the failure physically looked like.** Logs distinguish cancelled from completed; only the user distinguishes "would not stick and got dragged" from "clogged, nothing came out" from "stuck fine but ugly." These have disjoint fixes and the state machine cannot tell them apart. Ask before reslicing, not after.
6. **A filament change is a new variable, not a fix.** When the user proposes swapping filament to solve an adhesion failure, evaluate whether the new material is *easier or harder* to stick and say so plainly before reslicing. Silk/specialty PLA contains additives that lower surface energy and adhere noticeably worse than plain PLA, and wants roughly 10–20°C more hotend heat; swapping into it without raising temperature and adhesion aids makes an adhesion failure worse.

## Visual Print Inspection & Failure Triage

- **Escalate hotend faults to direct physical observations:** A room webcam can show head position and obvious crashes but usually cannot resolve nozzle threads or a nozzle-to-heatbreak leak. Ask the operator to inspect specific landmarks and report what he sees. A voluntarily supplied close-up may be analyzed, but never require a phone photograph of the nozzle or probe.
- **Do not use the IR printer camera to clear the bed for motion:** PEI grain, clips, lighting, and shadows are routinely classified as leftover prints. Before homing, probing, mesh calibration, or commanded motion, get an explicit empty-bed confirmation from the user. Use the camera for "is the head parked / is there an obvious crash," not for "is the PEI empty."
```bash
moonrakerctl camera-snapshot ~/.cache/print-buddy/printer-snapshot.jpg
```
- **The Klipper and Moonraker state model cannot detect adhesion or extrusion failure.** `printing: true` and no `error` flag only means the firmware is still executing G-code — it has no sensor for whether extruded plastic actually bonded to the bed or even exited the nozzle. A print can run cleanly through the state machine's eyes while depositing loose, unbonded blobs the whole time. Furthermore, a job that runs to 100% completion and logs "Print job done" can be a complete ghost print (air-printing for 30+ minutes with zero plastic deposited due to a clog, stripped filament, or extruder slip). Do not treat "no error flag" or "Print job done" as evidence of a successful print; only visual inspection of the bed proves physical deposition and adhesion.
- **IR/night snapshots at low resolution will not resolve fine first-layer or brim-line detail, but they DO resolve the difference between a continuous adhered line and scattered detached blobs — take that difference seriously.** Cropping/zooming a grainy nightvision frame does not recover texture that was never captured, so do not claim to see clean lines, corners, or infill patterns from a soft blob. But do not use that same limitation as an excuse to wave off a genuinely ambiguous or wrong-looking shape as "probably fine" — describe literally what pixels are visible (continuous ribbon vs. scattered dots/loose curls) and say so plainly, including when the honest answer is "I can't tell from this frame, zooming in further." A prior real failure on this printer was missed this way: a soft blurry blob was called "intact" from a wide shot, and a tighter crop one check later showed it was actually a scatter of detached, curled blobs the whole time — the frame had the evidence, it just wasn't looked at closely enough before declaring the print fine.
- **`printTimeLeftOrigin` will jump from `"analysis"` to `"linear"` early in a print and report a wildly inflated remaining time — this is not the printer slowing down.** `"analysis"` is the slicer's precomputed per-line estimate; `"linear"` is Moonraker.s current linear progress extrapolation, and brim/skirt G-code is short and travel-heavy so its early byte rate does not represent the denser perimeter/infill G-code coming later. Do not diagnose a problem from this jump alone; cross-check `filepos / file size` against elapsed time before concluding anything is wrong.
- **Overhead color washing:** High angle and wide angle surveillance cameras with ambient daylight or overhead LEDs often wash out light colored filament (yellow, white, clear) against textured gold/bronze PEI sheets, making active first layers appear invisible. Use a close up inspection angle or verify toolhead Z height and extruder stepper wheel rotation before assuming extrusion failed.
- **First layer verification:** Inspect adhesion during the first 60 seconds of extrusion. If corners lift, lines drag or gaps appear, stop and diagnose nozzle cleanliness, bed preparation, material, temperatures and mesh. Do not automatically subtract an offset. Keep the persisted saved value until an explicitly authorized documented measurement justifies a replacement.
- **Spaghetti detection & emergency shutdown:** If extruded filament loops loosely in the air or bunches around the nozzle heater block, immediately cancel the job, raise Z by 30mm, park the bed forward, and turn off all heaters (`M104 S0`, `M140 S0`).
- **Separate adhesion failure from warping failure by WHEN the part let go — they have disjoint fixes and fixing one does not fix the other.** A part that never stuck, or came loose within the first minutes, is an adhesion problem: bed prep, first-layer temperature, first-layer speed, squish. A part that printed a clean first layer, ran fifteen-plus minutes, and then lifted at a corner is thermal contraction: each cooling layer shrinks against a bottom the bed holds fixed, and the accumulated stress peels the edge. Adhesion aids will not stop it. The warping levers are sustained bed temperature for the whole print (not just layer 1), throttled part cooling, and a wider brim — see the warping table in `references/print-failure-triage.md`. When an adhesion fix visibly improves the result but the part still fails later, do not re-tune adhesion harder; re-diagnose as warping. Also ask about room airflow: an HVAC vent, open window, or fan blowing across the machine reliably lifts corners on flat parts no matter what the profile says.
- **Plastic on the outside of the hotend requires physical inspection.** Stop the job and safely cool the machine before maintenance. Do not apply a threaded Volcano nozzle repair, wrench size, torque, or inductive-probe procedure to the AD5X. Identify the installed assembly and use its manufacturer replacement procedure. After authorized maintenance, verify extrusion and AD5X calibration before printing.
- **A leaking hotend can imitate adhesion, warping, and extrusion faults.** When several downstream fixes partly help but the failure returns, stop tuning around the leak and inspect the hotend physically.
- **Detachment root-cause triage (broad flat vs small footprint):**
  - **Broad flat parts (nameplates, trays, tags):** Never diagnose mid-print detachment as needing a brim. A broad flat base already provides maximum surface area. Look for scrape marks or dragged raster lines on the upper surface. The typical culprit is zero Z-hop (`retract_lift = 0`) combined with fast travel moves (>100mm/s): the nozzle impacts curled infill ridges (especially prominent with silk PLA die swell) and shears the part off the bed. Fix by setting `retract_lift = 0.2`mm, using non-crossing infill (Gyroid rather than Grid), and bumping bed temperature to 60–65°C for silk PLA.
  - **Small-footprint parts:** Slender bases detach from thermal warping leverage. Fix with a 4mm to 6mm brim and slower first layer speeds.

## Timelapse

Use the active AD5X Moonraker installation, not retired container host container instructions. See `references/klipper-timelapse.md` for read-only discovery and evidence requirements. Do not claim capture or rendering works without a real output video.


## Pitfall: percentage first-layer width
PrusaSlicer resolves `first_layer_extrusion_width` percentages against the first layer HEIGHT, not the nozzle. A historical `200%` at 0.2 mm gave 0.40 mm lines through a 0.6 mm nozzle: thin, starved first layer that looked like a feed problem. The template's absolute widths are defaults **overridden from live nozzle state by `python3 -m print_buddy.core.model_job`**; they are not a declaration of installed hardware. `python3 -m print_buddy.core.model_job verify-gcode` refuses any file whose first-layer or layer 2-5 median `;WIDTH` is under 90% of the live nozzle; reslice, never override.


## Readiness and selection reconciliation

The captured native detail response is distinct from Klipper `print_stats`. Native `status="printing"` by itself is not proof of physical or Moonraker execution; a disagreement with Moonraker standby is unresolved and must block. For native mode, use authenticated `/detail` `slotInfos.hasFilament` for per-slot presence, not ZMod's stale screenless `zmod_color.hasFilament` flags. Preserve the native timestamp/source and fail closed when occupancy is missing, malformed, or stale.

A generated `; zmod_color_data = 0|RGB|material` describes logical tool metadata, not physical feeder selection. Public release-matched source for ZMod 1.7.4-51 (ghzserg/z_ad5x commit 75bcec539196aa022243c56397eba9a17e0577cc, .shell/zmod_color.py) establishes that native PRINT_ZCOLOR sends explicit toolId/slotId materialMappings to /printGcode. _SET_EXTRUDER_SLOT rejects display-on mode. SILENT=0 emits compatible web UI prompts; SILENT=1 proceeds to a print submission and is never a preview. Defaults are constructed from slot order, not a proven previous mapping. Installed source parity and exact-file readiness must still be verified before using this route. See state/research/ad5x-public-source-multicolor/CATDUCK_RECONCILIATION.md.

The operator-confirmed October 5 morning native baseline is the active calibration authority. Generic screenless z_offset_mm is null, not an invitation to copy the probe trigger or native level offset. Inactive values remain only in historical evidence. Nozzle changes invalidate calibration_authority as well as generic offset verification. Unknown or mismatched values must fail closed, not be replaced by an unrelated store.

- When `display_off: 0`, the native Flashforge screen is the primary calibration authority.
- Native on-screen calibration updates `Adventurer5M.json` (`zLevelOffset`, `leftExtruderOffset.zProbeOffset`) and stores bed mesh under profile `MESH_DATA` in Klipper.
- Do not overwrite or re-probe mesh if `MESH=MESH_DATA` is used.
- Spoolman mappings for IFS slots 1-4 are recorded in the dated baseline only. Do not treat this as current physical slot identity, live mapping, or a universal logical-tool-to-slot rule; resolve requested spool metadata from the selected slot mapping and verify live evidence.
- Baseline reference: `$HERMES_HOME/state/calibration-baselines/<timestamp>/`.
