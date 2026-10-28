# AD5X timelapse verification

The old container host mkuf container and Intel Arc installation recipe is retired. The active Moonraker is on the AD5X at `PRINTER_HOST:7125`. Do not rebuild a retired container or create another container to restore old instructions.

1. Read `/server/info` to identify loaded components and `/server/files/roots` for actual timelapse storage.
2. Read the live timelapse settings through the endpoints exposed by this installation. A file root alone does not prove capture or rendering works.
3. Preserve the active print and current configuration. Do not trigger render, calibration, restart, or capture macros during an audit.
4. Verify completion against a real saved video before claiming timelapse works. If no recent video exists, report rendering as unverified.
5. The installed component is mainsail-crew moonraker-timelapse, mode `layermacro`, autorender on. It names renders `timelapse_<full gcode filename including .gcode>_<YYYYMMDD_HHMM>.mp4` and serves them at `GET /server/files/timelapse/<name>`. The printer root account does not accept the container host SSH key, so never SCP the printer. Download over HTTP, then copy the local file to `root@PRINTER_HOST:the configured archive folder`.
6. Orca layer change gcode must emit `TIMELAPSE_TAKE_FRAME`. The listener waits up to three minutes after a real completion, then attaches a local copy. A missing render is a log line, not a failed print announcement. Already sliced jobs do not gain the frame macro until they are sliced again.
7. Retention: the archive host at `the configured archive folder` is the durable copy and is kept indefinitely. The HTTP staging copy is deleted once the archive publishes. Discord attachment copies in `~/.cache/print-handy/moonraker-announcements/*.mp4` are pruned after `PRINT_TIMELAPSE_LOCAL_RETENTION_DAYS` (default 14; 0 disables). Hermes never deletes renders on the printer, so its 6 GB timelapse root needs occasional manual cleanup.

Container work belongs to the orchestrator and requires the operator's specific creation approval. This reference does not authorize installations or printer changes.
