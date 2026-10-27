# Diagnostics: error taxonomy, markers and the audit inventory (#390)

Print Buddy's diagnostics overhaul (issue #390, milestone 2.1.6) gives every
failure one vocabulary, one searchable marker, and one operator-facing bar:
a message says **what failed**, the **most likely cause**, and **what the
operator can do about it**. No bare exception text, no silent drops, and no
telemetry — diagnostics leave the machine only when the operator explicitly
exports a bundle (Stage 3).

## Error taxonomy

Every failure at a main boundary is classified by
`print_buddy.diagnostics.classify` into exactly one category:

| Category | Meaning | Typical remedy shape |
| --- | --- | --- |
| `transient` | Network weather: DNS, refused/reset connections, timeouts, 429/5xx | Wait and retry; then check the network path |
| `configuration` | A setting, profile or credential is wrong or missing | Fix the named setting; re-run the doctor |
| `hardware` | The printer or a physical subsystem did not do what was asked | Check the printer; nothing was started by the message |
| `programming` | A Print Buddy bug | File a report with the marker and a diagnostics bundle |
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
in `print_buddy.diagnostics.LEGACY_MARKERS` and likewise never changes.

## Staged plan

1. **Stage 1 (this page's PR):** taxonomy + markers + the operator-message
   builder (`print_buddy/diagnostics.py`), first wiring in the Spoolman
   client's failure warning, and this audit inventory.
2. **Stage 2:** Discord message audit fixes — apply the operator-message
   bar to the surfaces the inventory below marks as failing it.
3. **Stage 3 (done):** diagnostics bundle — `/print-buddy bundle` in the bot
   and `python3 -m print_buddy.diagnostics_bundle` on the host assemble
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

The fail-soft posture is preserved throughout (#235): warnings never block
a print, and no print path changes behaviour beyond reporting.

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
