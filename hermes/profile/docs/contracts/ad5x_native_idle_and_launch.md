# Native idle, backup and silent launch rules

## Authority and evidence
Use the saved calibration baseline snapshot while native display is on. Native zProbeOffset and zLevelOffset are different fields from the probe trigger value and from the screenless saved offset. Do not substitute one for another or assign a generic user offset without measurement. Nozzle changes invalidate authority.

Assume the feeders the operator lists as loaded are loaded unless they report otherwise. Occupancy differs from current engaged feeder and logical tool assignment. Never ask to reload solely because an unrelated ZMod presence flag disagrees.

## Cleared does not mean status ready
Pinned ZMod CANCEL_PRINT sends native M26. Successful cancellation leaves native status cancel. Existing clear_job.safe_idle accepts ready/cancel/cancelled only with Moonraker ready + standby and all native and Moonraker heater targets zero. clear_job intentionally avoids replaying cancellation against a retained canceled filename.

For an explicitly mapped ZMod launch, printers/flashforge/zmod/native_idle.require_idle additionally requires empty errorCode and zero native duration/progress; missing fields or active/unknown state refuse. This corroborates idle, not firmware acceptance of a new job. Do not use homing, offset resets, or invented endpoints to force readiness. If native start explicitly rejects Busy after cancellation, corroborated cold idle alone is insufficient. A user-authorized installed ZMod REBOOT can recover the native daemon: observed cancel to ready with retained filename cleared after roughly two minutes. Verify persisted calibration separately afterward. Native telemetry zAxisCompensation was 0 immediately after reboot while persisted zProbeOffset remained 0.025; do not treat those as interchangeable or overwrite the persisted baseline. Do not reboot merely to cosmetically replace an idle status label. Legacy model_job.validate_native_start remains stricter for filename-only routing; it is not the explicit mapped multicolor route. Never weaken its currentLoadSlot check merely to start a different feeder.

## Backup and restore
Preserve full local profile privately, including credentials. Verify captured files by archive readback hashes. Fresh TAR_CONFIG output in installed ZMod 1.7.4-51 is mod_data/config_1.7.4-51.tar.gz, not config.tar.gz. Wait for gcode_store completion and use actual returned filename; accepted macro response is not archive completion. Download and inspect members including usr/prog/config/Adventurer5M.json and opt/config/mod_data/variables.cfg. A generic URL 404 is not a reason to rerun the macro.

Documented restore: upload captured archive as mod_data/config.tar.gz then RESTORE_TAR_CONFIG, only under explicit restore authorization. Archive coverage does not prove restoration of every firmware-side flow calibration effect. Do not test restore merely for confidence.

## Launch and monitoring
Use source pinned to installed firmware/ZMod. SET_ZCOLOR with SILENT=1 AUTO_ASSIGN=0 LEVELING=0 T0=1 T1=4 maps two colors via materialMappings. SILENT=0 prompts web UI, not native touchscreen. No touchscreen action required. Native PRINT_ZCOLOR hardcodes flowCalibration=true; exact firmware behavior remains unknown and Never describe it as proven harmless.

Require artifact checksum, runtime macro parity, live hardware/calibration check, corroborated idle, current bed-clear authorization, and completion AND failure delivery to the originating chat room. TUI subscriptions do not deliver to chat. One submission owner; uncertain acceptance means inspect, never blindly repeat.

Tests: test_native_idle.py exercises canceled/ready idle acceptance and rejection of active state, nonzero targets, errors and unknown activity. Test transport/mapping offline separately. A passing idle test is not a successful physical print.

Sources: https://wiki.zmod.link/Zmod/#tar_config ; https://wiki.zmod.link/Global/#silent ; installed source commit 75bcec539196aa022243c56397eba9a17e0577cc. Full evidence remains in state/audits.
