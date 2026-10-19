# Repair, test-blocker, and launch-card rules

Load before an assigned repair, a test-dependency blocker report, or an orchestrator launch card.

## Test dependency blockers

Run the suite from the repo checkout with `python3 -m pytest tests`. Print the exact Python executable and the `pytest` version before collection when reporting a problem.

A test-dependency blocker is justified only when the dependency is unavailable or fails to import under the interpreter that runs `python3 -m pytest tests`, and collection fails for that same dependency. A blocker report must include the exact command, resolved interpreter, whether collection began/completed, and the first causal error. If collection succeeds, report scoped test outcomes separately from unrelated suite failures.

### Routine execution versus authorized repair

Routine status, preparation and launch use documented entry points. An explicit diagnosis or repair assignment permits scoped source inspection, public documentation research, printer code edits and offline tests within this repo. The routine restrictions below do not prohibit assigned repairs. Neither scope permits bypassing physical authorization, credential isolation, failed validation or duplicate submission guards.

For repairs, state the concrete defect and decisive test before changing code. Read the exact failing source and one relevant reference, reproduce offline, apply the smallest justified change, then exercise the normal CLI with fake transport. Do not keep reinterpreting cosmetic details after tests establish the contract. Preserve originals and successful physical artifacts. Missing evidence remains unknown, not proof of readiness or a reason to guess.

The loaded plugin limits identical terminal commands to two per identified turn. A refusal is final for that action; do not rephrase to evade it.

A native launch requires the reviewed shared startup validator and contiguous heater/start block. Faithful Orca fixtures must cover the actual M73/M106 preamble; do not infer arbitrary preamble skipping from benign slicer commands. Comments may intervene; executable motion or tool selection may not. Reject contradictory immediate declarations. Later object heater commands cannot prove startup compatibility. Heater T0 addresses the single heater independently of logical color T1. Regenerate MD5 after finalization and validate the exact resulting bytes before upload.

Accepted, heating, executing and completed are separate outcomes. Never park on an unspecified listener: identify its actual destination and failure path, or report monitoring as incomplete. Event driven monitoring and an explicitly assigned bounded reconciliation are permitted; uncertain submissions never authorize another start.

### Reviewed artifact launch: short execution path

For a launch card, use the exact JOB.json path and command packet supplied by the orchestrator. Read the card and canonical skill once. Do not reread historical review prose or reprove completed offline geometry/slicing review. Live machine checks still apply.

1. Verify the supplied artifact SHA256 once. The job must already contain existing local G-code/config paths and the selected filament. If a referenced file is missing, stop immediately and report that exact path to the orchestrator. Do not try alternate tools, edit the manifest, substitute a bare G-code path, or recreate the deleted workspace.
2. If current operator authorization (bed clear plus start) is supplied, run the documented print-now command once on the JOB.json or the exact G-code path the card names; print-now binds a G-code path to its JOB.json itself. It performs busy-state, mesh, G-code/hardware, filament, upload and start readback gates. Do not duplicate its checks with separate status, check, verify-gcode or help calls merely for reassurance.
3. Report the actual command outcome. Accepted/preparing is not extrusion or completion. Request first-layer observation only after actual extrusion. On refusal, block once with the exact unresolved prerequisite, not a promise that the next session will succeed.

Notifications are optional and never a launch prerequisite. The Moonraker listener posts start and finish cards; do not block, delay or research notification destinations before a launch. A session reset grants no physical authorization.

Never say all preflight checks passed when a path, hardware field or physical gate remains unresolved. Mention authoritative persisted Z offset separately from stale hardware summary text. Keep duplicate-command protection; routine execution should need fewer calls without preventing authorized repair.

