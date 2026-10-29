---
name: ad5x-multicolor-slicing
description: Use when slicing AD5X multicolor models in Orca.
version: 0.1.0
author: Print Handy contributors
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [AD5X, OrcaSlicer, multicolor, IFS, slicing]
---

# AD5X Multicolor Slicing

Produce genuine two, three or four tool Orca slices with traceable geometry, tool assignments and inspection evidence. Offline slice success does not authorize upload or establish physical feeder mapping. Preserve the installed printer startup, mesh and offset contracts; never change persistent printer configuration to make a slice pass.

## Installed source color intake

The canonical python3 -m print_handy.core.model_job intake and Orca adapter support explicit component/part assignments or source-filament palette mappings on a single plate. Core 3MF mesh leaves, nested transforms and build instances are preserved. Painted triangle segmentation and multiple plate slicing remain refused; do not silently flatten them or claim general painted-model support. Mixed materials and contradictory assignments also fail closed.

On Discord, /print-colors followed by an archived JOB.json path opens the installed deterministic color selection hook. It presents explicit per-part or single-color choices and persists them against the source hash. This command performs no slicing, upload, heating, motion or start. Changed choices invalidate earlier artifact readiness and require a new normal slice; unchanged choices preserve readiness. Normal approved slicing then creates the actual tool geometry and launch binding. Raw stale ancestor G-code must remain refused.

Installing the hook file does not prove the existing gateway has loaded it. Activation requires coordinated plugin reload or gateway restart by its owner, followed by separately authorized real Discord prompt rendering and button clicks. Fake transport tests exercise the installed views and callback contracts but do not establish live rendering or physical print success.

## Hard native startup rule

Require exactly one START_PRINT. Only the observed benign preamble commands M73 P0 R<nonnegative integer>, M106 S0 and M106 P2 S0 may precede the contiguous M190 S<bed> / M104 S<hotend> T0 / START_PRINT block, or START_PRINT / M190 / M104 T0 block. Comments and blanks may intervene, executable commands may not split the block. Extra parameters, arbitrary macros, nonzero fans, motion, extrusion and tool selections are not skippable preambles. Insert a missing heater pair immediately before START_PRINT only after validating its preamble and absence of partial/conflicting declarations; never relocate or mask an existing split header. Later layer heaters never prove startup compatibility. Preserve object/tool content and generate MD5 last. Independently approved regression: 202 tests plus 31 subtests, including actual immutable Orca source normal CLI finalization/verification/fake launch, idempotence and zero-transport unsafe controls. Completed historical artifacts remain immutable and deliberately fail this stricter adjacent-header rule; never auto-migrate or replay them.

Normal finalization and launch preflight share `print_handy/printers/flashforge/zmod/native_startup.py`. Require the adjacent heater/start block after only the explicit benign preamble defined above. Later layer heater commands never satisfy this gate. The ZMod FAQ specifies heater T0 for single_extruder_multi_material, independently of initial logical T1 selecting Pink. Preserve logical tool commands and object toolpaths. Refuse contradictory startup declarations; regenerate checksum only after corrections. The corrected four-tool and three-tool jobs machine-completed under the earlier startup contract; their unchanged files are historical evidence, not current preflight-ready candidates. The three-tool job used T0=slot1, T1=slot2, T2=slot4 with initial logical T1 retained, active MESH_DATA during execution, and heater targets zero at terminal standby. Saved terminal evidence is in `state/audits/t_1f2df8ab-hardening/TERMINAL.txt` and `three-outcome-checkpoint.json`; independent offline rerun passed 151 tests plus 31 subtests. Machine completion is not independent verification of physical colors or quality.

## When to Use

* Slicing AD5X models with multiple colors or materials.
* Diagnosing Orca native project reimport crashes, missing tools, purge tower bounds refusal or export path errors.
* Reviewing a multicolor file before the separate authorized print workflow.

## Prerequisites

Use installed Flatpak OrcaSlicer `com.orcaslicer.OrcaSlicer` and recovered validated AD5X machine, process and per-filament settings. Run dependency-preflight before declaring any runtime absent or installing anything. No AppImages or unapproved Docker containers.

Read `references/proven-workflow.md` for exact evidence locations and command structure. Load the existing printer management and print-job-validation skills before physical operations; this skill does not replace their safety contract.

## How to Run

Use `terminal` for the installed slicer, `search_files` for bounded artifact discovery, and `read_file` for commands/settings/logs. Preserve the original model and settings; construct a core 3MF only when necessary to represent actual geometry, not as a reason to replace the user's model with a coupon.

## Procedure

1. Establish requested colors/materials and record logical tool to physical IFS slot mapping. Source-part extruder numbers are one based; emitted G-code tools are zero based. Do not assume tool index equals physical slot. Completion: every actual part/color has an explicit logical assignment and intended slot.
2. Recover a proven slicer invocation and presets. Prefer core 3MF geometry plus separate JSON settings when native Orca project reimport crashes. Keep actual printable regions and their transforms intact. Completion: source model contains real geometry assigned to each intended tool, not only filament metadata or renamed G-code tools.
3. Check multimaterial and tower settings against the installed AD5X preset. The proven preset has `single_extruder_multi_material=1`, `enable_prime_tower=1`, empty `change_filament_gcode`, and `purge_in_prime_tower=0`. Those last two values are not independently evidence of failure. That preset is ZMod `use_trash_on_print=1` (trash-chute purge); Print Handy reads the live value at slice time, switches to prime-tower purge (`purge_in_prime_tower=1`, wipe tower Type 2, explicit flush volumes) for 0 (Nopoop), and refuses multicolour for 2 or an unreadable value. Position the entire tower inside printable bounds; the demonstrated coupon location X15/Y150 is not universal for every model. Completion: model and tower footprints fit without disabling bounds validation.
4. Run actual Orca slicing using the documented command pattern. Supply a basename, not an absolute path, to `--export-3mf` when using `--outputdir`. Preserve commands, stdout/stderr, exit status and `result.json`. Completion: exit zero and successful result, with all warnings inspected; otherwise capture a concrete error before proposing remediation.
5. Inspect emitted executable G-code. Track modal extrusion, tool changes and object roles separately from purge/tower moves. Require positive object extrusion for every intended tool and inspect tower behavior after tool changes. Audit bounds, temperatures and unexpected commands; explicit path bounds exclude hidden macro motion. Completion: actual object extrusion and geometric source assignments agree for every requested color.
6. Preserve source/project, settings, untouched G-code, command/logs, intended mapping, audit and SHA256 manifest. After all reviewed artifact edits run `python3 -m print_handy.core.model_job finalize-gcode FILE --tool-map MAP.json`, then normal `verify-gcode FILE` and authorized `print-now FILE`. Shared finalization inserts checksum-bound slot/color/material metadata and computes native MD5 over exact remaining bytes. Unchanged refinalization is byte-identical; invalid existing checksums are refused. Both coupons initially select T1; do not assume T0 starts. See the reference for tested commands and evidence tiers. Preparation, accepted submission, extrusion, completion and confirmed physical colors remain separate.

## Pitfalls

* Exit139/SIGSEGV was observed in native project reimport even without tool edits. Core geometry plus JSON settings is a verified alternate slicing path, not a proven fix or diagnosis of the native crash.
* Internal -102 was a bed bounds refusal: a tower at Y220 was on the edge. Move the tower footprint appropriately; do not suppress checking.
* Internal -13/exit243 came from a doubled export path. Use an export filename basename.
* A three-tool job can map T2 to physical slot4. A descriptive mapping JSON does not execute printer mapping.
* Empty toolchange customization and `purge_in_prime_tower=0` occur in the installed preset. Do not invent a native purge contract from those settings.
* User confirms this printer's feeders remain physically loaded. Idle `hasFilament=false` alone must not contradict that confirmation or demand reloading. Keep genuine in-print runout, jam, thermal and motion protections. This procedural rule is not proof that software sensor handling has been fixed.
* Do not claim no print was submitted merely from idle state after an uncertain request; preserve receipts and never duplicate an uncertain start.
* Missing output before attempting slicing is unfinished assigned work, not missing human input. Stop repeated identical crash commands; change the diagnostic approach using the saved evidence.

## Verification

Independently verify manifest hashes, source mesh/tool assignments, actual object extrusion per tool and explicit bounds. Rerun the exact slicing command into a separate output directory when independent reproducibility is needed; compare executable lines, allowing only non-executable timestamp differences. Never claim physical multicolor success from slice completion or machine completion alone. No additional print, heating or motion is authorized by loading this skill.
