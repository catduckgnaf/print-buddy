# Bambu Lab A1 (phase 1: offline only)

Select it with `printer.model: bambulab.a1`. Print Buddy slices for the A1, checks fit and G-code, and leaves a verified file for you to move to the printer yourself. It never connects to the printer. The P1S is a separate later model and is not covered here.

## What works and what does not

| Capability | Status |
|---|---|
| Slicing with OrcaSlicer (`templates/orca/bambulab_a1`) | Supported |
| Fit checks against 256 × 256 × 256 mm, original dimensions kept, shrink only on operator choice | Supported, same deterministic checks as other models |
| G-code compatibility validation after slicing and again at `print-now` | Supported (`print_buddy/printers/bambulab/guard.py`) |
| File handoff | Manual: `print-now` verifies the file, prints its path and refuses to start. The bed clear approval is not used up |
| Live telemetry (MQTT, LAN or cloud status) | Not supported |
| File upload (FTPS, LAN, cloud) | Not supported |
| Print control (start, pause, resume, stop) | Not supported |
| AMS Lite multi-color | Not supported: multi-color, multi-part and multi-plate sources are refused, as on other single-extruder models |
| Bambu Studio handoff (upstream issue #123) | Out of scope |
| P1S | Not started; follows only after the A1 path is validated on hardware |

Supported firmware and authentication modes for live use: none. No LAN-only mode, access code, developer mode or cloud login has been tested or implemented, and no credentials are read. `services.moonraker_url` and `services.octoprint_url` must stay empty for this model; settings refuse to load otherwise, so the listener, `/print-stop` and `/print-resume` cannot act on some other printer that answers at an old URL. The Moonraker listener, camera watchdog, timelapse, cold pull and other Klipper-only commands do not apply to the A1.

## Never Klipper or ZMod code on a Bambu printer

AD5X and Klipper start code (`START_PRINT ... MESH=`, `PRINT_START`, `END_PRINT`, `BED_MESH_*`, `SET_PRINT_STATS_INFO`, `CHANGE_ZCOLOR`, `SAVE_VARIABLE`, the ZMod `; MD5:` line, and any other Klipper `UPPER_SNAKE` command) is refused at three points:

1. Template assembly: the A1 adapter's `machine_start_gcode` and `machine_end_gcode` raise `ForeignStartCode` unless the start is the A1 vendor sequence and both are free of Klipper/ZMod commands. An `[orca] templates` override that points the A1 at another printer's folder fails here.
2. After slicing: `adapter.gcode_problems` blocks the slice. The G-code must declare `printer_model = Bambu Lab A1` and contain the vendor start.
3. At `print-now` and `verify-gcode`: the same checks run against the hardware record before the operator is told the file passed.

A job sliced for another model is still refused by the existing `printer_model` check on `JOB.json`.

## Values and sources

The machine, process and filament templates are OrcaSlicer's own A1 profiles, flattened. `scripts/bambu-a1-templates.py` rebuilds them from OrcaSlicer tag v2.4.2 (commit `8500fcdccaa10b5099ac20d252af3a7c560046f1`, the version the real-slicer CI job installs): `Bambu Lab A1 0.4 nozzle` → `fdm_bbl_3dp_001_common` → `fdm_machine_common` with its five `template *_gcode` includes, `0.20mm Standard @BBL A1`, and `Generic PLA @BBL A1`. The tests pin the SHA-256 of every vendor G-code block, so a change has to be a deliberate re-import.

| Value | Source | Verified |
|---|---|---|
| Printable area 0..256 × 0..256 mm, height 256 mm | OrcaSlicer A1 profile | Yes, read from the pinned commit. Bambu also publishes 256 × 256 × 256 mm |
| No bed exclusion area (the A1 profile empties the X1 family's corner exclusion) | OrcaSlicer A1 profile | Yes |
| Head-wrap detection zone 226..256 × 224..256 mm (where the firmware checks for a nozzle clump; not an exclusion) | OrcaSlicer A1 profile | Yes, but its runtime effect is unverified |
| 0.4 mm stainless steel stock nozzle, `marlin` G-code flavor | OrcaSlicer A1 profile | Yes |
| Hotend 300 °C max, bed 100 °C max | Bambu Lab A1 spec pages | No: read from search-result extracts; bambulab.com was unreachable from the build sandbox |
| 0.2, 0.6 and 0.8 mm hotends; hardened steel needed for CF/GF and glow filaments | Bambu Lab A1 spec pages | No, same reason. Only 0.4 mm is templated and accepted |
| PLA, PETG, TPU, PVA ideal; ABS, ASA, PC, PA, PET and fiber-filled versions not recommended | Bambu Lab A1 spec pages | No, same reason |
| AMS Lite: 4 spools | Bambu Lab A1 Combo pages | No, same reason. Not used |
| Motion envelope X −48.2..267, Y −0.5..262.5 mm | Derived from the extremes of the vendor G-code moves | No: not a published Bambu figure, not checked on hardware |

All values are in `print_buddy/printers/bambulab/capabilities.py` with the same source labels.

## Print Buddy changes to the vendor profile

* `z_hop_types` and `filament_z_hop_types`: Normal Lift. The shared post-slice guard allows nothing else (the vendor uses Auto Lift).
* `enable_arc_fitting`: 0. The guard blocks arc fitting on every printer.
* `enable_prime_tower`: 0, single filament only.
* `brim_type`: `outer_only`, the brim mode Print Buddy's fit checks budget for.
* `printer_settings_id`, `print_settings_id`, `filament_settings_id` set to the profile names, and `filament_colour` set, so the post-slice provenance check can match them.

Nothing else is changed. In particular the vendor start, end, filament-change, timelapse and layer-change G-code are copied verbatim.

## Checks specific to the A1

* Bounds: the vendor start and end blocks park the head on the wiper at X −48.2, the cutter at X 267 and the purge lane at Y −0.5 and Y 262.5, and the per-layer timelapse block moves to X −48.2. So only the Orca toolpath between `; MACHINE_START_GCODE_END` and `; MACHINE_END_GCODE_START` is checked: every move inside the motion envelope, every extruding move on the 256 mm bed and under 256 mm. Tool changes are checked in the same span (the vendor blocks use the firmware's T1000 and T255).
* Temperatures: any M104/M109 above 300 °C or M140/M190 above 100 °C is refused.
* Materials: not-recommended materials are refused outright; abrasive filaments need `nozzle.type` hardened_steel.
* Nozzle: 0.4 mm only, stainless or hardened steel.
* Hardware record: its bed and height may not exceed the A1's, and its nozzle must be one of the above. `printer_state check` reads only the record and Spoolman, never Moonraker.

## Known limitations and follow-ups

* No real OrcaSlicer slice of the A1 templates has been run yet. The offline tests use synthetic G-code built around the vendor blocks; the next step is adding `bambulab.a1` to the real-slicer CI job and approving its protected-settings baseline (`config/protected-settings-baseline.bambulab.a1.json` is absent, so the baseline check only warns).
* Print Buddy writes plain `.gcode`. Whether the A1 prints a plain `.gcode` file from its microSD card, or needs Bambu's `.gcode.3mf` package, is unverified.
* Orca's plate type for the CLI slice is not set, so the vendor start's Textured PEI offset (`G29.1 Z-0.02`) only applies if Orca resolves the plate as Textured PEI. Unverified.
* The vendor G-code is copied from OrcaSlicer (AGPL-3.0) into this MIT-licensed repository. Check that this is acceptable before offering the change upstream.
* Next phases, each needing its own review: hardware validation of a hand-carried file, then live status, then upload and print control with explicit per-job authorization, then AMS Lite, then the P1S.
