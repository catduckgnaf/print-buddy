# Test coverage map

Which suites pin which subsystem, so feature work can see the gaps it is
adding to (#391 scope 5). Maintained by the test-expansion pass; update
this file when a suite is added, moved, or starts/stops pinning an area.

## Subsystem → suites

| Subsystem | Pinned by |
|---|---|
| Discord bot core, commands, runtime, typed replies | `tests/bot/test_runtime.py`, `test_prompts.py`, `test_typed_reply_scope.py`, `tests/corpus/` |
| Bot startup retry / transient classification (#364) | `tests/bot/test_startup_retry.py` |
| Platform adapters (Discord / Matrix / Telegram), access control | `tests/bot/test_platform.py`, `test_matrix.py`, `test_telegram.py`, `test_access.py`, `test_routing.py` |
| Guided setup | `tests/bot/test_guided.py`, `test_guided_multi.py`, `tests/test_setup_wizard.py` |
| Bot health / heartbeat / listener transport | `tests/bot/test_health_and_transport.py`, `tests/test_listener_health.py`, `tests/test_listener_gate.py` |
| Hermes profile platform switch (#384) | `tests/test_profile_platform.py`, `tests/hermes/test_profile_platform_intake.py`, doctor + bot-check rows in `tests/test_doctor.py` / `tests/bot/test_health_and_transport.py`, `tests/test_install_hermes.py` |
| Moonraker listener, announcements, completion delivery | `tests/hermes/test_lane_b.py`, `test_print_messages.py`, `test_completion_delivery.py`, `test_paused_job_gone.py`, `test_print_alert_buttons.py` |
| Timelapse: Moonraker delivery contract (#373) | `tests/hermes/test_timelapse_delivery_contract.py` |
| Timelapse: launched-print monitors (OctoPrint / stock / Bambu) | `tests/hermes/test_octo_watch.py`, `test_stock_watch.py`, `test_bambu_watch.py` |
| Timelapse: capture, encode, sizing, plan clips, vertical short | `tests/hermes/test_timelapse_capture.py`, `test_timelapse_encode.py`, `test_platform_media_sizing.py`, `test_plan_timelapse.py`, `test_vertical_short.py`, `test_timelapse_cli_transport.py` |
| Roast (one per print, #374) + roast generator fail-soft | `tests/hermes/test_print_messages.py`, `tests/pipeline/test_prepared_intake.py` |
| Intake / slicing pipeline / model job | `tests/pipeline/`, `tests/core/`, `tests/slicer/`, `tests/corpus/` |
| Spoolman best-effort contract (#387, #235) | `tests/core/test_spoolman_client.py`, `tests/pipeline/test_spoolman_best_effort.py`, `test_spoolman_wrapper_contract.py`, `test_spoolman_warning*.py` |
| Printers: roster, per-printer state, leases (#333–#337) | `tests/test_printers_roster.py`, `tests/test_per_printer_state.py`, `tests/test_multi_printer_walkthrough.py`, `tests/printers/` |
| Fail-soft state files (corrupt / partial) | `tests/test_state_file_failure_paths.py`, `tests/test_state_files.py`, `tests/test_live_gate.py` |
| Docker image, release contracts, supervisor, healthcheck | `tests/test_docker_release*.py`, `tests/docker/`, `tests/test_combined_supervisor.py`, `tests/test_go2rtc_container.py`, `tests/test_native_release_acceptance.py` |
| Web UI (status, config, login, roster) | `tests/test_webui_*.py` |
| Doctor / bot check surfaces | `tests/test_doctor.py`, `tests/bot/test_health_and_transport.py` |
| Settings / config loading | `tests/test_settings.py`, `tests/test_print_buddy_cfg.py`, `tests/test_webui_config*.py` |
| Docs / contribution policy / post-release surfaces | `tests/test_docs_index_contract.py`, `tests/test_contribution_policy.py`, `tests/test_post_release_surfaces_workflow.py` |
| Knowledge, macros, live stream | `tests/test_knowledge.py`, `tests/test_macros.py`, `tests/test_live_*.py` |

## #391 regression inventory (stage 1, 2026-10-26)

Fix PRs checked for a test that fails without the fix; gaps filled in
the stage-1 PR unless noted:

| Fix | Verdict |
|---|---|
| #373 Moonraker timelapse silent drop (#383) | Covered by its contract tests (working path, restart, no-render, drifted name, mismatched marker, archive-off). |
| #373 OctoPrint monitor (#385) / stock monitor (#377) | Covered except the MEDIA-post-refusal fallback in both monitors — added in stage 1; mutation-verified by removing the fallback in a scratch copy (both tests fail). |
| #364 Discord startup retry (#369) | Covered for DNS/refused/timeout/429/503/403/login/intents; classifier branches for certificate errors, gateway discovery, WS handshake statuses, generic connection errors, the full transient-errno table, connector-cause inheritance and jitter bounds were untested — added in stage 1; the whole file fails against pre-#369 code (37 failed, finished log). |
| #384 platform-disable detection (#389) | Reader's main states, doctor and bot-check disabled/enabled rows covered; string variants (`"no"`/`"off"`/case/whitespace), non-mapping sections, empty/comment-only files, the other-platform isolation, and the doctor/bot-check unreadable + unset + missing rows were untested — added in stage 1; the reader file fails against pre-#389 code (15 failed, finished log). |
| #374 one roast per print (#380) | Covered (warming start, already-printing start, replay, completion has none); the roast generator's own fail-soft branches (empty title, no key, no URL, HTTP failure, malformed payload) were untested — added in stage 1. |
| #387 Spoolman best-effort (#396) | Covered by its client + wrapper-contract + best-effort suites; not duplicated here (per #391 coordination rule). |
| #386 channel-access default (#397), #399 docker unblock | Covered by `test_access.py` / `test_docker_release_contract.py` in their own PRs. |
| Fail-soft state readers | Unparseable JSON already degraded correctly everywhere; parseable-but-malformed timestamps crash `recent_links`, `print_alert_buttons` and `print_next` — filed as bug #404 with strict-xfail pins in `tests/test_state_file_failure_paths.py` (no fix in this track, per #391's rules). |

Known remaining gaps for later #391 stages: the multi-printer
cross-product beyond the sampled Stage 2 matrix (scope 3), upload
timeout mid-flight and roster misconfiguration failure paths (scope 2
remainder), and the Matrix message-ordering flake root cause (scope 4).

## #391 stage 2 (failure paths: uploads)

- Bambu FTPS upload: a timeout mid-transfer and a timeout during the
  size verification both surface as the plain "may be incomplete"
  `BambuLanError` (failure type named, no access code, session closed);
  a failing `quit()` after a verified store does not fail the upload.
  Mutation-verified: removing the upload wrap in a scratch copy fails
  both new timeout tests (8 failed across the two mutated modules).
- OctoPrint upload: the client's `upload()` had no tests at all — now
  pinned for the one multipart POST shape, server-reported target
  verification (origin/path mismatch refuses, nothing started), a
  timeout as a plain not-retried error with no key leak and exactly one
  request, and bad filenames refused before any request.
- PrusaLink upload: a PUT timeout is not retried, leaks no key, and is
  followed by no verification read and no start (the storage lookup GET
  before it fails soft to the default storage, as designed).
- Roster misconfigurations were re-audited for this stage: duplicate
  ids, duplicate chat claims (including the global-channel fallback),
  cross-vendor keys, bad/missing ids, unknown keys and empty rosters
  are all already refused with named errors in
  `tests/test_printers_roster.py` — no gap found, nothing added.

## #391 stage 3 (multi-printer cross-product + flake investigation)

- Cross-family walkthrough added in `tests/test_multi_printer_walkthrough.py`:
  three listener families in one instance (Bambu LAN + Moonraker +
  OctoPrint) route their claimed channels plus the shared fallback,
  each printer's settings view carries only its own family's connection
  (no moonraker URL in the Bambu view, no LAN serial/host in the
  OctoPrint view, no OctoPrint URL in either), Spoolman stays shared,
  state folders stay distinct; and a printer with no channel claim and
  no platform home is unreachable by chat without breaking the others.
  The rest of the Stage 2 matrix was re-audited as already pinned:
  leases/approvals/hardware/maintenance/spool exclusivity per printer
  (`tests/test_per_printer_state.py`), channel routing and cross-channel
  prompt/plugin safety (`tests/bot/test_routing.py`), per-printer
  listener supervision and heartbeats (`tests/test_combined_supervisor.py`,
  `tests/test_listener_health.py`).
- Scope 4 (flake elimination) investigation, 2026-10-26: the Matrix
  message-ordering flake did NOT reproduce. Evidence: six consecutive
  local runs of `tests/bot/test_matrix.py` + `tests/bot/test_routing.py`
  were all green (43 passed each, finished logs), and the failed CI runs
  sampled from the last 60 (40430763841, 40419563602, 40415662779,
  40403501206) failed on other tracks' in-flight branches (design,
  state-files, supervisor timing) — none on a Matrix test. No root cause
  is claimed and no speculative fix is made; scope 4 stays open on #391
  until a failing run can be captured with its log.
