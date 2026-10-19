# AD5X ZMod screenless operating contract

## Authority and version

Target Flashforge AD5X only, audited ZMod 1.7.4-51 and upstream AD5X macro source commit 75bcec539196aa022243c56397eba9a17e0577cc. Firmware or macro changes require a new compatibility review. Documentation describes current upstream and may differ from installed firmware; never apply a newly documented feature without installed compatibility evidence.

Reviewed source families: ZMod AD5X, Main, Calibrations, SetupCalibrations, System, Global, FAQ, Recommendations, Filament and Changelog; Klipper bed mesh/G-codes and Moonraker API. Locally archived wiki pages and audited macro files are in the orchestrator scratch ad5x-doc-review and .firecrawl. Primary links:

* https://wiki.zmod.link/AD5X/
* https://wiki.zmod.link/SetupCalibrations/
* https://wiki.zmod.link/Calibrations/
* https://wiki.zmod.link/Main/
* https://wiki.zmod.link/Global/
* https://wiki.zmod.link/FAQ/
* https://wiki.zmod.link/Filament/
* https://wiki.zmod.link/Recommendations/
* https://github.com/ghzserg/z_ad5x/tree/75bcec539196aa022243c56397eba9a17e0577cc

## Preparation and launch

1. Preserve model inventory, geometry, author structural settings and per-job filament binding. Reslice old artifacts whose startup lacks MESH=auto. Do not merely relabel an old artifact as reviewed.
2. Use Orca Flatpak and verified AD5X presets. Startup is START_PRINT with BED_TEMP, EXTRUDER_TEMP and MESH=auto; termination is END_PRINT. Never use native FlashForge protocol in screenless mode; transfer G-code through Moonraker, not 3MF. No redundant native header, raw G28/probing or independent purge sequence replaces ZMod startup.
3. Saved mesh strategy requires PRINT_LEVELING=0. MESH_TEST=0 or 1 is allowed; 2 can rebuild, 3 changes offset and 4 can do both, so these modes are refused. Do not change live settings to satisfy a guard without authorization.
4. User offset authority is the numeric value already persisted in save_variables gcode_offsets.z with LOAD_ZOFFSET=1. Reject explicit START_PRINT Z_OFFSET and forced leveling/KAMP. Do not equate probe.z_offset with the user offset. Do not require, restore, or inject a hardcoded magnitude. LOAD_ZOFFSET_NATIVE copies the native screen offset into the screenless value and is a one-way overwrite, not a per-print step and not a step on the way back to the screen.
5. print-now supplies current busy, hardware, mesh, filament, upload and start readback checks. Confirm physical clearance and verified notification delivery before launch. Accepted/printing telemetry is not proof of physical adhesion or deposited plastic.

## Calibration

Use canonical mesh-interface.json and checkpointed mesh-run. In screenless mode AUTO_FULL_BED_LEVEL EXTRUDER_TEMP=220 BED_TEMP=60 PROFILE=auto SAVE=0 owns heating, nozzle cleaning, homing and load-cell preparation. The macro may cool internally before contact; 220 is the requested cleaning temperature, not a claim that every probe occurs at 220. Runner verifies fresh 25-point matrix, cools, persists once, reconnects, compares saved points and loads auto for applied readback. Preserve offset and force-control configuration. No generic paper wizard or blind Z adjustment.

A fresh mesh is not a newly measured user offset. No supported standalone automatic replacement offset was established in this audit. Keep the persisted saved value pending separately authorized physical measurement/first-layer validation. Offline mocks validate refusal, checkpoint and transport behavior, not physical probe accuracy or compatibility on the machine.

## Filament and controls

IFS remains available without the native screen. Physical slot, slicer tool index, configured labels and Spoolman ID are distinct. Preserve verified mapping; do not infer stock-screen telemetry availability in screenless mode. Unknown filament presence is a blocked evidence path, not instruction to reload. SILENT=2 disables IFS; do not silently select it. Verify current runout/motion sensors and actual mapping through the pipeline before dispatch.

Use ZMod/Moonraker pause, resume and cancel semantics, never native-screen dialogs in screenless mode. Resume needs reconciliation of any filament/hands intervention and a safe current machine state. Cancellation and failure reporting distinguish requested cooldown from verified zero targets. A client timeout does not cancel a macro; inspect checkpoint and reconcile, never replay ambiguous motion. Stream complete Moonraker readbacks to jq via stdin, never a --argjson command argument: config exports can exceed Linux's per-argument limit. Keep large-state success and failure checkpoint regression cases.

## Persistence, recovery and remaining validation

Do not edit vendor macros or mod_data/variables.cfg; ZMod documents user.cfg and user.moonraker.conf as override locations and SAVE_ZMOD_DATA as settings interface. No new firmware, camera, network, motion tuning, PID or shaper changes were authorized by this review. Existing dual chat/Discord listener remains the event route.

A physical calibration card stays blocked until a fresh presence/bed/hands confirmation accompanies the corrected packet. Do not decompose it again. First supervised execution must verify installed macro behavior, full matrix, persisted/applied mesh, saved offset unchanged and heaters off. A print needs separate authorization and a newly reviewed artifact. No physical validation is claimed by this document.
