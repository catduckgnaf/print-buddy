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
4. **Stage 4:** structured logging consistency — per-subsystem verbosity
   (see [Settings](SETTINGS.md) `[logging]`), `printer_id` on
   multi-printer records, and supervisor/healthcheck output that names
   the failing child and the reason instead of a bare exit status.
5. **Stage 5:** doctor / `bot check` tripwires — every failure mode the
   earlier stages make detectable gets a named doctor row with a remedy,
   and a Web UI status equivalent where one exists.

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
| Intake / slicing / delivery posts (`core/model_job.py`) | Many outcomes carry a `reason`; some failure posts are still built from raw exception text | Mixed; per-post audit needed | 2 |
| Listener heartbeat (`healthcheck.py`, `bot/health.py`) | `(ok, reason)` strings name staleness/identity/connection states | Names what failed; no remedy, no marker | 5 |
| Container supervisor (`docker/supervise.sh`) | A required child's exit is reported as a bare status; listener exits name the printer and the restart budget | Required-child exit does not name the child | 4 |
| Container healthcheck (`docker/healthcheck.py`) | One row per subsystem with a reason string | Mostly meets bar; rows get markers in Stage 5 | 5 |
| Doctor (`doctor.py`) | `FAIL <check>: <detail>`; several details already include the remedy (e.g. the #384 platform row) | Mostly meets bar; new detectable modes get rows in Stage 5 | 5 |
| Web UI status (`webui/status.py`) | Status/health JSON for the same checks | Stage 5 adds equivalents for new doctor rows where a surface exists | 5 |
