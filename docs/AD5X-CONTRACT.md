# ZMod AD5X MVP implementation contract

## Source authority
Official AD5X documentation at ZMod commit 001703371c90e228defce41bb4230b7fafd37fea states that multiple spools assigned the same color AND material type automatically switch when the active spool runs out.
https://github.com/ghzserg/zmod/blob/001703371c90e228defce41bb4230b7fafd37fea/docs/en/AD5X.md

## Required implementation
- Use native infinite-spool handling. No AI polling/switch loop, new plugin or MCP.
- Verify same stored color and material type; additionally check compatible material variant and calibrated profile. These extra compatibility checks are local requirements, not claimed firmware capabilities.
- Keep slicer tools T0/T1 distinct from physical IFS slots and backup candidates.
- COLOR assigns spool metadata. SET_EXTRUDER_SLOT records which spool is loaded; it does not configure backups.
- Exclude unavailable/empty or unverified backup candidates. No eligible backup means native pause/error recovery, not guessed substitution.
- Preserve existing job identity/accounting and latency; no required new LLM calls or rendering.

## Acceptance
Offline tests: compatible backup, different color, different material, incompatible variant/profile, empty backup, stale metadata, exhausted candidates, remapped active slot and duplicate events. Installed-mode acceptance belongs to printer specialist. Native selection order and installed firmware/screen behavior have not been verified. No forced runout or physical print authorized by this reference phase.

## Compatibility
AD5X-specific docs govern over generic Klipper recommendations. Preserve existing start/end, purge, checksum, mesh/Z and IFS authority. Review object-exclusion crash warning before adoption. Keep existing Orca Flatpak. Bambufy is optional and officially incompatible with the native screen; no installation in MVP.

## Status
Contract delivered; runtime fallback integration and physical acceptance remain OPEN in issue #2. Existing hardening remains paused until coordinator release. Notify/Apprise audit is deferred, existing Discord behavior unchanged.

## Motion boundaries, margin contract, and multi-plate intake (1.9.1)
- **Physical sheet and motion limits**: The AD5X uses a 235x235 mm spring steel build plate. Klipper stepper travel reaches X [-20.0, 225.0] (245 mm total) and Y [-20.0, 232.0] (252 mm total).
- **Edge margins**: Single-copy prints use a 1.0 mm bed margin; multi-copy prints use a 3.0 mm margin. Parts up to ~218x218 mm fit on the nominal 220x220 mm bed area without endstop triggering or frame collision.
- **Multi-plate capacity evaluation**: Orca plate capacity tests multi-plate projects per-plate rather than across the combined canvas. If any plate exceeds the bed, binary search evaluates the minimal uniform scale ladder (e.g. 94%, 75%, 50%).
- **Plate boundary preservation**: Scaled multi-plate projects preserve plate separation during slicing, support per-plate scale overrides, and group parts by `(plate_id, slot)`.
- **Conversational continuity**: Affirmative replies ("Let's do it", "Print it", "Go ahead") automatically recover the candidate model link from conversation history. Failure messages omit prompts to resend links.

## Units, slicer fallback, and motion limits (1.10.0)
- **Units**: STL files do not record units, so an STL whose largest dimension is under 10 mm is not assumed to be in inches. Intake asks the user to confirm millimeters or inches and records the answer as source-bound unit provenance on the job (`unit_decision` / `unit_provenance`); inches print at 25.4x when the result fits the printer volume, otherwise the job fails with its measured and would-be sizes. An explicit user scale (including 1.0) settles the size and is never auto-scaled, and parts Print Handy generated itself in millimeters are never auto-scaled. Slicing a small STL with no recorded confirmation refuses with the measured size and asks for the confirmation.
- **Slicer order**: OrcaSlicer first; Bambu Studio CLI only after an Orca slicing failure. Both outputs pass the same post-slice and protected-settings gates. Bambu receives absolute line widths derived from nozzle diameter.
- **Acceleration**: Process acceleration is capped at 4,500 mm/s² (outer wall 3,200), below the measured X input shaper recommendation of 4,747 mm/s².

## Sliced .gcode.3mf delivery format (#564 stage 1)
- **Opt-in only**: `[delivery] format = gcode_3mf` (default `gcode`). The setting is refused for non-Flashforge vendors at load. With it on, a slice for a ZMod model also produces the Orca sliced export `plate_1.gcode.3mf` next to the `.gcode`, and the job record notes it (`delivery_format`, `delivery_file`, `delivery_file_sha256`, per derived plate as well).
- **Colour authority is unchanged**: the package's `slice_info.config` filaments are Orca's from the same profiles the `.gcode` path slices with, and the inner G-code is the exact finalized file (native startup header, `zmod_color_data`, MD5 line) that passed the post-slice guards — Print Handy rebinds the export to those bytes and refreshes the archive MD5 ZMod verifies at extraction. Spoolman matching and the confirmed tool→slot mapping stay Print Handy's; the printer learns the file's colours from the archive instead of the G-code scan/preprocessor, and applies them through the same `SET_ZCOLOR` flow.
- **Guards**: single-plate packages only; a package whose plate MD5 disagrees with its inner G-code, whose inner G-code fails an existing check (embedded ZMod checksum, vendor/adapter guards, `verify_gcode_offline` on the extracted inner file), or that lacks `slice_info` filaments or the `plate_1.json` bounding box is refused at slice time, never recorded. A slice produced by a fallback slicer cannot become a package and is refused with the reason.
- **Floor**: the format needs ZMod 1.7.5+ on the printer; older ZMod cannot print it and there is no printer-side fallback. Print Handy does not read the ZMod version yet (#562), so enabling the format is the operator's responsibility until #564 stage 3 makes selection version-aware. The `.gcode` path is untouched and remains the default.
