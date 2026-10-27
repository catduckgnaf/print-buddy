# Proven offline workflow

Resolve all paths against the active `$HERMES_HOME`, not the orchestrator's home. Existing recovery evidence lives under `state/research/ad5x-public-source-multicolor/coupon/sol_recovery/`.

## Evidence to read before adapting

* `README.txt`, `attempt_results.json`, `AUDIT.json`, `MANIFEST.json`.
* `three/command.txt`, `four/command.txt`, corresponding `tool_mapping.json`, `audit.json`, `slice/result.json` and logs.
* `build_and_slice.py`: actual component geometry construction and one-based per-part extruder metadata. This is a coupon-specific builder, not a general model converter; inspect before any reuse because running it regenerates artifacts.
* `audit.py`: actual audit implementation. Inspect its assumptions before applying to different models. It is evidence code, not authority for hidden firmware motion or native feeder behavior.
* `machine_multicolor_candidate.json`, `process_multicolor_positioned_candidate.json`: preserved copies. Recorded slice commands used the matching presets one directory above this recovery directory. Check content hashes before substituting copies.

The verified installed version was Flatpak OrcaSlicer 2.4.2. Both jobs exited zero with Success and no warnings. Exported native projects were retained as deliverables; native project reimport was not verified. Use the core geometry imports for reproducibility.

## Invocation pattern

Through `terminal`, adapting only verified paths and materials:

```bash
flatpak run com.orcaslicer.OrcaSlicer \
  --debug 3 \
  --load-settings "$MACHINE_JSON;$PROCESS_JSON" \
  --load-filaments "$FILAMENT_JSONS" \
  --slice 0 \
  --outputdir "$OUTPUT_DIR" \
  --export-3mf reviewed_project.3mf \
  "$CORE_GEOMETRY_3MF"
```

`FILAMENT_JSONS` is a semicolon-separated, logical-tool-ordered list of actual per-filament JSONs. Capture the exact resolved command and process exit code. Empty successful stdout is not itself an error; inspect result.json and emitted files. CLI internal error numbers and shell exit codes are different quantities.

## Demonstrated mappings and boundaries

Three-color coupon: source extruders 1/2/3 correspond to T0/T1/T2, intended colors in three physical slots. Four-color coupon: source extruders 1/2/3/4 correspond to T0/T1/T2/T3, intended White/Pink/Black/Green in slots 1/2/3/4. Both begin with T1. These are intended mappings, not proof that an arbitrary printer launch interprets them correctly.

The tower used X15/Y150 and width45. Candidate PLA temperatures were nozzle210/bed60; not universal recommendations. Existing start was `START_PRINT BED_TEMP=60 EXTRUDER_TEMP=210 MESH=MESH_DATA`. Preserve the installed startup/mesh authority rather than transplanting this line to every job.

## Recovery startup contract, October 5

The earlier statement that later heater lines were sufficient was wrong. Shared native_startup.py now requires immediate M190 Sbed / M104 Snozzle T0 at startup, accepting the documented leading prefix and previously successful immediately-post-START_PRINT pair. Recorded ZMod FAQ specifies heater T0 for single_extruder_multi_material; initial logical T1 remains Pink slot2. Normal finalize-gcode inserts the documented prefix and regenerates MD5; verify-gcode rejects later-only heater declarations. Regression:151passed31subtests, including old stalled header refusal, successful immediate header, initial T0/T1, conflicts and idempotence.

One authorized recovery cancellation verified native cancel and Moonraker standby at17:45:37 New York time; original guard preserved with disposition. Replacement SHA25634965f4815e200ed259bed9af7b5194f2b35a8817b58a2f9cad705645d10beab submitted once via normal print-now with same four-tool mapping. At17:50:21 nozzle210.2/target210 and bed49.87/target60 confirm heating, but Moonraker still standby with zero extrusion and native progress0. This is not yet machine completion or verified physical colors. See state/audits/t_1f2df8ab-hardening/RECOVERY.txt and replacement.diff. Never replay either guarded submission.

## Documentation and GitHub review

For native mapping, review the official ZMod project at https://github.com/ghzserg/zmod and the documentation linked from its README. Use the installed version and actual macro implementation to verify `SET_ZCOLOR`, T0 through T3 handling, native start selection and purge behavior. Do not invent command parameters from memory or assume upstream HEAD equals the installed firmware. Record exact URLs and commit/version in the job packet. Slice-only preparation must not contact the printer simply to prove a documentation claim.

## Shared finalization and mapped native launch, October 5

From the repo checkout, tested normal commands:

    python3 -m print_handy.core.model_job finalize-gcode ~/3d-prints/ad5x-four-color-reviewed/four_color.gcode --tool-map state/research/ad5x-public-source-multicolor/coupon/sol_recovery/four/tool_mapping.json
    python3 -m print_handy.core.model_job verify-gcode FILE
    python3 -m print_handy.core.model_job print-now FILE

The last command requires current physical authorization and verified notification delivery. Loading this reference grants neither. Original source and `.before-finalize` backup remain untouched. Shared `multicolor_contract.py` serves existing Orca single-color finalization, mapped finalization, verify-gcode and normal print-now. No executable startup, heater, tool or extrusion lines were edited. The reviewed original already contained literal M104 S210. Missing MD5 is generated after metadata edits; corrupt existing MD5 is refused.

Offline result: 137 tests plus 31 subtests passed across test_multicolor_contract.py, test_model_job.py, test_orca_adapter.py, test_native_contract.py and test_native_idle.py. Wrapper: 13 checks passed. Public CLI tests exercise three/four-color finalization -> verification -> fake launch, bare/wrapped upload receipts, missing/corrupt checksum, missing mapping, mismatched/malformed materials, single-color shared finalization/verification, byte-identical refinalization and replay refusal. Invalid artifact cases stop before upload. Fake transport is not hardware success.

The installed SET_ZCOLOR scans fresh color metadata when ALLOWED_TOOL_COUNT is omitted; supplying that parameter bypasses fresh scanning. Do not supply it on this route. Four-color mapped launch uses AUTO_ASSIGN=0 LEVELING=0 T0=1 T1=2 T2=3 T3=4. Native mode is required; screenless multicolor is unproven. Live RGB/material, known native errors, head protection, remote SHA256 and saved-mesh startup checks remain gates. `.launch.json` persists pending submission before transport and blocks replay; `.upload.json` retains acknowledgement. print record records retain mapping separately from active-spool accounting.

Actual candidate SHA256: bafdd0d8256ff9bc0c02221e39425486803d9469e27eecc9f76fa35e2af108d8. October 5 about5:35PM New York time: one SET_ZCOLOR submission, transport resultok, native receipt Status: OK and all four intended mappings. Subsequent readback: native printing with zero progress/duration and zero heater targets, Moonraker standby. This establishes accepted preparation, NOT extrusion or completion. Applied mesh during extrusion, completion and physical colors remain unresolved. Do not replay this submission or claim physical multicolor success.
