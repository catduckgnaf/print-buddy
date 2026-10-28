# Diagnostics: error taxonomy, markers and the audit inventory (#390)

Print Handy's diagnostics overhaul (issue #390, milestone 2.1.6) gives every
failure one vocabulary, one searchable marker, and one operator-facing bar:
a message says **what failed**, the **most likely cause**, and **what the
operator can do about it**. No bare exception text, no silent drops, and no
telemetry — diagnostics leave the machine only when the operator explicitly
exports a bundle (Stage 3).

## Error taxonomy

Every failure at a main boundary is classified by
`print_handy.diagnostics.classify` into exactly one category:

| Category | Meaning | Typical remedy shape |
| --- | --- | --- |
| `transient` | Network weather: DNS, refused/reset connections, timeouts, 429/5xx | Wait and retry; then check the network path |
| `configuration` | A setting, profile or credential is wrong or missing | Fix the named setting; re-run the doctor |
| `hardware` | The printer or a physical subsystem did not do what was asked | Check the printer; nothing was started by the message |
| `programming` | A Print Handy bug | File a report with the marker and a diagnostics bundle |
| `unknown` | Nothing honest can be said yet | Run the doctor; include the marker in any report |

An explicit category from a boundary that knows better always wins over the
conservative heuristic fallback; an unrecognised failure is `unknown`,
never a guessed cause.

## Greppable markers

Each (subsystem, category) pair has one stable marker,
`PB_<SUBSYSTEM>_<CATEGORY>` — for example `PB_SPOOLMAN_TRANSIENT`.
Markers are append-only: once one has shipped in a log line or a message
it is never renamed, so old support threads stay searchable. The pre-#390
marker `DISCORD_STARTUP_RETRY` (#364/#369) is registered as a legacy marker
in `print_handy.diagnostics.LEGACY_MARKERS` and likewise never changes.

## Staged plan

1. **Stage 1 (this page's PR):** taxonomy + markers + the operator-message
   builder (`print_handy/diagnostics.py`), first wiring in the Spoolman
   client's failure warning, and this audit inventory.
2. **Stage 2:** Discord message audit fixes — apply the operator-message
   bar to the surfaces the inventory below marks as failing it.
3. **Stage 3 (done):** diagnostics bundle — `/print-handy bundle` in the bot
   and `python3 -m print_handy.diagnostics_bundle` on the host assemble
   versions, image digest (when the environment records one), a redacted
   config summary (env-name indirection only; secret values never
   included), printer/roster summary, doctor output and a bounded
   recent-log tail. The bug-report issue form asks for the bundle. The
   bundle is only ever written to a local file the operator chooses to
   attach — nothing is uploaded.
4. **Stage 4 (done):** structured logging consistency — per-subsystem
   verbosity via `[logging] levels` (see [Settings](SETTINGS.md)),
   `printer_id` bound on every log line of a per-printer listener
   process, and the container supervisor naming the required child that
   exited (`Required child exited: bot (status 1); stopping container.`)
   instead of a bare exit status. The container healthcheck already named
   each subsystem with its reason and is unchanged.
5. **Stage 5 (done):** doctor / `bot check` tripwires — the doctor gained
   a `logging` row (a configured log file whose folder is missing or
   unwritable now fails loudly with the remedy and
   `PB_LOGGING_CONFIGURATION`, instead of silently falling back to
   stderr) and a `listener heartbeats` warning row naming each required
   printer whose heartbeat is unhealthy, with `PB_LISTENER_TRANSIENT`.
   Both rows also appear in the Web UI status page's doctor section,
   which reuses the same check functions. The heartbeat row is a warning,
   never a doctor failure: the container healthcheck owns failing on a
   dead listener, and a doctor run on a host where listeners are
   legitimately stopped must not fail.
6. **Stage 6 (done):** per-post audit of the Discord action handlers in
   `plugins/print-feedback` — the generic failure posts (color selection,
   next plate, stop, resume, print again, restart, plate picker, alert
   buttons) now go through one helper that keeps the operator detail and
   the state/remedy note and appends the greppable `PB_*` reference
   marker, redacted. The deliberate refusal posts (`NextPlateError`,
   `REFUSED: ... Nothing uploaded or started.`) already met the bar and
   are unchanged; `model_job`'s CLI exits are those same curated refusal
   texts. The design turn's `DesignError` post is the same class —
   a curated, operator-phrased error type — and is likewise unchanged.

## Plain-language pass (#467)

#390's bar was written for the operator debugging the system. #467 holds
the messages a person in chat actually reads to a plainer bar:

1. **First line in plain words** — what you asked for, what happened. No
   exception class names, no raw exception or stderr text, no ALL-CAPS
   failure prefix, no internal jargon.
2. **What did *not* happen**, where it matters — nothing started /
   nothing uploaded / nothing changed / your print is still running.
3. **One clear next step** — the button, command or check that fixes or
   retries it. If there is no user fix (it looks like a bug), the post
   says so and points at the diagnostics bundle (`/print-handy bundle`).
4. **Technical detail demoted, not deleted** — the `PB_*` marker rides as
   a secondary `Reference:` line, and the full detail stays in the log,
   the intake receipt and the bundle.
5. **Never silent, never a dead end.**

The shared builder is `print_handy.diagnostics.plain_post`; the Discord
handlers' `_failure_post` (#390) is built on it, so there is one wording
system. `tests/test_friendly_errors.py` pins the rewritten corpus,
including the negative pin: no inventoried chat post may contain a raw
exception string, a traceback fragment, or an ALL-CAPS failure prefix.

What changed, surface by surface:

| Surface | Before → after |
| --- | --- |
| Slicing failure (prepared intake) | `Slicing failed: {raw error}` → "Slicing this model did not work. No G-code was kept, and nothing was uploaded or started. Retry once from the saved model?" + `Reference: PB_SLICING_*`; the raw error stays in the receipt and log |
| Backup-slicer notice | `Bambu Studio sliced it because OrcaSlicer failed: {reason}` → "Sliced with the backup slicer (Bambu Studio) because the main slicer could not slice this model."; the reason is logged |
| Fit / resize checks unverified | trailing raw exception → plain unverified wording + resume step + marker |
| Preview failure | `Preview unavailable: {exc}` → "I could not make a preview image, so no image was sent…" |
| Slot/toolhead map problem | `Slot map problem: {exc}` → "Heads-up on the filament positions: …" (the adapter's own phrased reason) |
| Intake preparation failure | `New model preparation stopped: {exc}` → plain post + "Send the link or file again; … `/print-handy bundle`" + marker |
| Colour-selection failure (link intake) | `New model color selection stopped: {exc}` → plain post + retry step + marker |
| Delivery refusal | `Not delivered: …` → "The files were not sent here: …" (the `DeliveryRefused` reason is curated and kept) |
| Start failures (plugin next-plate / print-again / plate picker) | the raw print-now tail (`REFUSED:` / upload / start lines) was posted verbatim → `prepared_intake.plain_start_failure` translates it: a confirmed pre-upload refusal gets the specific plain guidance; anything else gets the honest "did not confirm whether the print started" wording |
| `model_job` pipeline exits (CLI) | `UPLOAD FAILED: {stderr tail}`, `START FAILED: …`, `REFUSED: live hardware check failed: …`, `G-CODE REFUSED: …` → plain first lines ("The file could not be uploaded to the printer, so nothing started…") with the raw detail demoted to a secondary `Detail:` line |
| Guided setup apply | `Applying the settings failed: {raw}` → "The settings could not be saved, so nothing was changed…" + bundle pointer; checklist and retry/manual/cancel replies unchanged |
| Guided debugging findings | `login check failed: {exc}` / `health probe failed: {exc}` → "the login check did not pass" / "the health check did not answer", with the existing Next step kept |
| `printer_state` warnings/problems | `Spoolman lookup failed: {e}`, `Moonraker active spool lookup failed: {e}`, `Moonraker unreachable: {e}`, `Calibration authority read failed: {e}` → plain wording naming the fallback ("the recorded spool was used; printing can continue") or the check to make; #235 fail-soft unchanged |
| Design turns | `DesignError` texts that embedded the raw service error → plain reasons ("the design service did not answer — wait a moment and try again"); the post leads "That design change did not work: … Nothing was sliced or started." |
| Print-control / spool / cold-pull / maintenance generic failures | `…: {exc}` posts → plain posts naming the state ("nothing was changed", "usage is still paused; answer again", "do not retry until the printer state is checked") |
| Vision-watch alerts | `vision check failed: {exc!r}` in the alert post → "the vision check could not be completed, so treat this as unreviewed…"; the raw error stays in the log |
| Spool sync results | `NOT updated ({exc})` / per-slot raw errors → plain "not updated — run `/spool sync`…" wording |
| Access refusal notice | "You are not on this bot's allowed list." → adds why and the next step ("…ask the person who runs Print Handy to add you"); the house "Not allowed. Nothing changed." posts are unchanged |
| Unmatched message | the full command list posted as an error response → a short reply: "I didn't understand that, so nothing happened." + the one common next step (post a link / drop a file) + the list on request via `/print-help`. Explicit `/print-help` / `help` still returns the full list, and the #437 LLM-first order is unchanged |

Deliberately unchanged, and why:

- The `REFUSED: …` lines inside `model_job` / `print_next` /
  `launch_state` remain the **transport contract** between the pipeline
  and its callers (`print_next` treats a trailing `REFUSED:` line as a
  confirmed pre-upload refusal; prepared intake extracts it). They are
  never posted raw any more — every chat path translates them — and the
  receipts keep them verbatim for support.
- Curated error types whose text is already operator-phrased —
  `NextPlateError` ("No next plate: …"), `DesignError`, guided-setup
  validation answers ("That answer does not work: reply with …") — keep
  their text; #467 removed the *raw machinery* interpolation under them.
- Logs, the diagnostics bundle, doctor/`bot check` rows and Web UI
  status keep full technical detail; only chat posts were rewritten.

The fail-soft posture is preserved throughout (#235): warnings never block
a print, and no print path changes behaviour beyond reporting.

## Debug log mode and sanitized exports (#478)

On top of the bundle and the static `[logging] levels` above, Print Handy
has a temporary **debug log mode** for reproducing a problem:

- **Surfaces.** `/print-handy debug on [minutes]` / `off` / `status` in the
  bot, the Debug log mode form on the Web UI status page, and
  `python3 -m print_handy.debug_mode on|off|status` on the host are all
  equivalent — they read and write one shared state file
  (`debug-state.json`) in the state folder. No config edit, no restart.
- **Duration.** `on` lasts **30 minutes by default** (an explicit number
  of minutes may follow, up to 24 hours), then the mode turns itself off.
  Starting it again ends the old session cleanly and starts a new one.
- **While on.** Print Handy's own loggers run at DEBUG; noisy library
  loggers (discord, websockets, asyncio) stay at INFO. Records are also
  written to a dedicated, size-bounded capture file
  (`debug-capture.log`, rotating, in the state folder), delimited by
  `DEBUG_SESSION_START` / `DEBUG_SESSION_END` markers carrying the
  session id. The capture exists whether or not a `[logging] file` is
  configured, so a Docker (stderr-only) install still produces logs.
  **Listener processes are covered**: the mode is shared state, not a
  per-process switch — every process applies it when it configures
  logging, the standalone bot re-checks it on its heartbeat, and the
  Moonraker, family and Bambu listeners poll it in their run loops.
  `bot check`, the doctor and the Web UI status page show a
  "debug mode: ON — session …, off in …" row (marker
  `PB_DEBUG_CONFIGURATION`) while a session is live.
- **Logging only.** Turning the mode on or off, and exporting, never
  changes print behaviour, confirmation gates or readiness guards.

**Sanitized export.** Turning the mode off in the bot builds the export
for that session's window (the capture lines between its markers) and
delivers the file **in chat**, after showing its sanitization report;
the CLI's `off` writes the same export to `state/debug-exports/`. The
file is named `print-handy-debug-<date>-<session>.md`. With no session
window, the export (and the #390 bundle, which uses the same path) falls
back to the existing bounded log tail. Nothing is uploaded anywhere:
the operator reviews the export and attaches it to the issue themselves,
and the bug-report form asks for the debug session ID and the
sanitization report next to the bundle field.

Exports are sanitized by `print_handy/sanitize_logs.py`, layered on
`logs.redact` (which already strips tokens, credentials and secret env
values). The export pass additionally removes:

- IP addresses and internal hostnames, in URLs and bare text — the URL
  scheme, port and path shape stay, so the line remains diagnosable;
- Discord/Telegram/Matrix user and channel IDs, plus IDs the config
  itself names — replaced with **consistent pseudonyms** within one
  export (`user-1`, `channel-1`, …) so lines still correlate;
- local file paths, email addresses, MAC addresses, serial-number-shaped
  values, and URL query strings.

A **verification pass** then re-runs the whole sanitizer over the result;
anything the first pass missed is removed there and counted too. Every
export carries the **sanitization report** — counts by category, never
the removed values (for example: "removed: 4 secrets/tokens, 6 IP
addresses, 3 user IDs. Verification pass found nothing further.") — so
the operator can see at a glance what was taken out before attaching it
to a public issue. The diagnostics bundle's config summary and log
sections use the same sanitizer and carry the same report.

## Audit inventory (Stage 1)

User-facing failure/warning surfaces, audited against the bar above.
"Meets bar" is a judgement from reading the code; the Stage 2 PR re-checks
each row as it changes it.

| Surface | What it does today | Bar verdict | Stage |
| --- | --- | --- | --- |
| Discord startup (`bot/client.py` `run_bot`) | `DISCORD_STARTUP_RETRY` log marker with attempt/backoff; token/intent failures print an actionable stderr line and exit 3 | Meets bar after Stage 2: the exhausted-retry line carries `PB_DISCORD_*`, and the token/intent exits name the remedy and `PB_DISCORD_CONFIGURATION` | 2 (done) |
| Spoolman unavailable (pipeline notice) | One-line notice that tracking was skipped; failure detail only in the WARNING log | Meets bar after Stage 2: the notice states the print continues and what to check; the log warning carries the exact `PB_SPOOLMAN_*` marker (Stage 1) | 2 (done) |
| Timelapse completion posts (#383) | Every degraded outcome posts a reason line instead of dropping the video silently | Meets bar — the reference pattern for Stage 2 | — |
| Intake / slicing / delivery posts (`core/model_job.py` + plugin handlers) | Curated refusal texts carry the reason and the state; generic handler failures were built from raw exception text with no marker | Meets bar after Stage 6: generic Discord handler posts carry the detail, the state/remedy note and the `PB_*` marker via `_failure_post`; deliberate refusals unchanged | 6 (done) |
| Listener heartbeat (`healthcheck.py`, `bot/health.py`) | `(ok, reason)` strings name staleness/identity/connection states | Names what failed; no remedy, no marker | 5 |
| Container supervisor (`docker/supervise.sh`) | A required child's exit is reported as a bare status; listener exits name the printer and the restart budget | Required-child exit does not name the child | 4 |
| Container healthcheck (`docker/healthcheck.py`) | One row per subsystem with a reason string | Mostly meets bar; rows get markers in Stage 5 | 5 |
| Doctor (`doctor.py`) | `FAIL <check>: <detail>`; several details already include the remedy (e.g. the #384 platform row) | Mostly meets bar; new detectable modes get rows in Stage 5 | 5 |
| Web UI status (`webui/status.py`) | Status/health JSON for the same checks | Stage 5 adds equivalents for new doctor rows where a surface exists | 5 |
