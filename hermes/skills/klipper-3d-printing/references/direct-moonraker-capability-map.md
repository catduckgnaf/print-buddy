# Direct Moonraker Capability Map

This map audits the retired `Charleslotto/klipper-mcp` feature set against the 3D Printer specialist's direct replacements. The transport is gone. The actual capabilities remain through Moonraker REST, Klipper macros, Spoolman REST, local shell analysis, and Hermes notifications.

## Routine printer control

| Prior feature family | Direct path |
|---|---|
| Full status and printer objects | `moonrakerctl status`, `objects`, or `/printer/objects/query` |
| Raw G-code and macros | `moonrakerctl gcode` or `/printer/gcode/script` |
| Start, pause, resume, cancel | `start`, `pause`, `resume`, `cancel` |
| Heater targets and waits | `heat-hotend`, `heat-bed`, `heat`, `cool`, `wait-temp` |
| Homing | `home`, subject to the bed-clear and movement safety gates |
| Emergency stop and restarts | `emergency-stop`, `klipper-restart`, `firmware-restart` |

## Calibration, drivers, and effects

| Prior feature family | Direct path |
|---|---|
| Bed mesh state and profiles | `mesh`, `mesh-load`, `mesh-clear`, `mesh-calibrate`, `mesh-save` |
| TMC status and register dumps | `tmc`, `tmc-dump` |
| TMC current and field writes | Explicit `SET_TMC_CURRENT`, `SET_TMC_FIELD`, or Klipper macro after confirmation |
| TMC autotune | Inspect Klipper objects and config; invoke installed autotune macros only if exposed |
| LED effects and scenes | Invoke `SET_LED_EFFECT`, `STOP_LED_EFFECTS`, `SET_LED`, or configured macros when those objects exist |
| StealthChanger and toolchanger | Invoke installed `Tn`, drop, initialization, alignment, and dock-test macros when objects exist |

The printer currently exposes TMC drivers but no LED effect or toolchanger objects. Those generic Voron features are therefore capability-on-demand, not missing functionality.

## Files, G-code, and backups

| Prior feature family | Direct path |
|---|---|
| List and inspect G-code files | `files`, `metadata`, `/server/files/list`, `/server/files/metadata` |
| Upload and delete files | `upload`; deletion uses `/server/files/<root>/<path>` with explicit confirmation |
| Config file listing and reading | `/server/files/list?root=config` and `/server/files/config/<path>` |
| G-code searching and comments | Local `grep` or `jq`, or download the file and inspect it locally |
| Validate and analyze G-code | `python3 -m print_buddy.core.model_job verify-gcode`, Moonraker metadata, local shell parsing |
| Extract layers and compare files | Local shell tools after downloading the G-code |
| Back up configuration | `backup-config DIR`; restore is intentionally manual and confirmation gated |

## Camera, history, statistics, and diagnosis

| Prior feature family | Direct path |
|---|---|
| Webcam list and snapshot | `webcams`, `camera-snapshot` |
| Timelapse settings and operations | `timelapse`, direct `/machine/timelapse/*`, or configured `TIMELAPSE_*` macros |
| Print history and cumulative totals | `history`, `/server/history/list`, `/server/history/totals` |
| Temperature history and alerts | Moonraker subscriptions and Hermes scheduled checks when requested |
| G-code history | `gcode-store` |
| MCU and Klippy diagnostics | `status`, `objects`, `gcode-store`, `/printer/info` |
| Host CPU, memory, disk, and network | `system-info`, `proc-stats` |
| Klippy log parsing and failure analysis | Moonraker logs downloaded through files API, then local shell analysis and skill troubleshooting guidance |
| Full data export | Collect JSON from status, history, system, Spoolman, and file metadata endpoints |

## Spoolman, notification, and maintenance

| Prior feature family | Direct path |
|---|---|
| Active spool | `spool` or `/server/spoolman/spool_id` |
| Spools, vendors, filaments, low-filament checks | Direct Spoolman REST API on the trusted LAN |
| Material usage | Moonraker history plus Spoolman records |
| Discord, push, TTS, and alerts | Hermes platform messages, Home Assistant, or existing completion watcher |
| Maintenance schedule and records | Existing 3D printing records and print record workflow |
| Audit trail | Hermes session history, Moonraker history, logs, and print records |

## Host administration

| Prior feature family | Direct path |
|---|---|
| Update status and refresh | `updates`, direct `/machine/update/status` and `/machine/update/refresh` |
| Update a component | `update COMPONENT I_UNDERSTAND` |
| Service state and restart | Moonraker machine endpoints; restarts require `I_UNDERSTAND` |
| Reboot and shutdown | `reboot I_UNDERSTAND`, `shutdown I_UNDERSTAND` |
| Moonraker config and object inventory | `system-info`, `objects`, and config file API |

The removed MCP also offered aliases that duplicated one another and server-side convenience analysis. Replacing aliases with a small command surface reduces latency and tool clutter without deleting the underlying endpoint or workflow.
