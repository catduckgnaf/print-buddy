# Supervised AD5X bed mesh routine

Use the installed `moonrakerctl mesh-run` once, not a hand-built shell sequence. No source reads, macro listing, help, separate routine receipt, status prelude, repeated backup, or repeated calibration on continuation. Ordinary status is still one unchanged `moonrakerctl status` call.

## Invocation

After the operator explicitly confirms bed clear, hands/tools clear and continued presence for THIS calibration, capture the actual confirmation epoch as AUTH. Never substitute the execution time for an old confirmation. Authorization must be no more than 120 seconds old when this command starts. Existing verified config archive and old mesh are reused, not redownloaded.

```bash
CTL=bin/moonrakerctl
$CTL mesh-run --state-dir $ARCHIVE/calibration/UNIQUE-RUN \
  --authorized-at "$AUTH" --bed-clear --hands-clear --present \
  --backup /EXISTING/klipper-config.tar.gz --old-mesh /EXISTING/old-mesh.json \
  --interface bin/mesh-interface.json
```

Use a unique run directory bound to this authorization, not a date-only directory reused for unrelated requests. Run with foreground terminal timeout 600. Each synchronous Moonraker command may use whatever remains of the whole-routine deadline, 20 minutes from confirmation (the AD5X screenless probe runs past 5 minutes); any longer tool execution must retain verified completion/failure delivery and operator supervision. Never detach calibration silently. If hands enter the machine, cancel immediately using the documented safety controls. The command cannot sense physical presence or cancel an in-flight server-side motion from a client timeout.

The routine emits its own typical-duration receipt. Its one initial combined query refuses busy, paused, shutdown, unknown, wrong screen mode, changed mesh count or changed offset/force-control authority. In screenless mode the reviewed interface invokes `AUTO_FULL_BED_LEVEL EXTRUDER_TEMP=220 BED_TEMP=60 PROFILE=auto SAVE=0`; ZMod owns heating, homing, nozzle cleaning and load-cell preparation. The legacy native-screen branch remains 60 C bed / 150 C hotend and must never be selected for screenless operation. Both branches verify a full 5 by 5 auto mesh, turn heater targets off, explicitly save auto, then persist config. SAVE_CONFIG may disconnect Klippy with HTTP 503; that is not success. Bounded reconnection and comparison of persisted config points with the new mesh decide success. Finally auto is explicitly loaded and applied points, heater targets and saved offset authority are checked. No offset or force threshold is written; no upload or print happens.

## Continuation

Use ONE local inspection command after interruption:

```bash
$CTL mesh-run --state-dir $ARCHIVE/calibration/UNIQUE-RUN --inspect
```

Completed checkpoint: report its recorded result as historical, not a fresh live state. No command is resent. Prepared checkpoint before first actuation: rerun the original command with genuinely fresh authorization; evidence paths are reused and checksums checked. A `*.pending` checkpoint means actuation may have started and its result is unknown. Stop. Do not delete it, reuse its directory, or guess completion.

`failed_cooldown_verified` is a finished failure, not an ambiguous resume. Keep that directory and its checkpoint, backup, old mesh, and checksums byte-for-byte. Do not rerun mesh-run against it. One later calibration uses a new unique state directory and the same unchanged `--backup`, `--old-mesh`, and reviewed interface. Fresh bed, hands, and presence confirmation is still required. Do not change offset, current, endstop, or config to get past the old failure. A cooldown that was not verified stays stopped until heater targets are read back at 0.

Failure attempts bounded cooldown and records whether zero heater targets were verified, with the failure cause in the checkpoint and stderr. INT exits 130 and TERM exits 143; a rejected SAVE_CONFIG or reconnect deadline exits nonzero through the same cleanup, never resending SAVE_CONFIG or loading an unverified mesh. A timeout can leave Klipper executing the original command and can block cooldown; report that exact limitation and have the present operator use physical emergency controls if needed. Never claim targets-off if its readback failed. No SAVE_CONFIG occurs after an incomplete probe.

## Version evidence and limitations

Interface is bound to the installed AD5X ZMod 1.7.4-51 / native stock firmware 3.1.6 and a successful physical command trace, run 824, session 20261004_171751_200ee5, messages 46555–46556. That trace contained masked SAVE_CONFIG HTTP 503 and ended with blank applied mesh. New stored points existed, but the old report was insufficient to prove an applied mesh. This routine corrects both failures. Firmware changes require a reviewed interface packet, not improvised generic Klipper commands. Script tests are offline only; the new routine has not been physically exercised.

Do not use `python3 -m print_handy.core.model_job routine-status` to prove this routine complete: idle_timeout Ready alone proves neither a fresh probe nor persistence. Use this routine's checkpoint. Keep the existing 12 terminal-call and exploration/repetition caps. No plugin restart or cap increase is needed.
