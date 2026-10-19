# print-buddy regression prevention plan (2026-10-12)

## What keeps happening
1. Synthetic tests pass while real artifacts fail: the 2026-10-05 Orca preamble rejection, and the PLA+ vs PLA spool mismatch fixed in commit b13a980.
2. Fixes land in one prompt path, while sibling paths keep the old behavior: Cancel existed on some prompts only, and typed replies were routed on some prompts only.
3. Nobody tests latency, so a 34 second parser ran twice before anyone noticed.

## Rules
1. **Golden corpus.** `tests/golden/` holds real, sanitized artifacts: the Orca G-code from the last 5 successful prints (headers plus the first and last 2,000 lines), MakerWorld API JSON (the 902337 case and a profileId case), Spoolman spool JSON (PLA+, Matte PLA, PETG), and the Migelo STL. Every parser and matcher change must pass the full corpus. Synthetic cases cannot replace this corpus.
2. **Bug-first tests.** Every reported bug gets a failing test built from the real artifact before it is fixed. The test name cites the date and symptom.
3. **Invariant tests over the whole flow, not one prompt:** every `ask()` offers Cancel; every `ask()` registers under the live session key; fit warnings always carry a Render button; quantity choices never exceed the copies that fit; nothing is sent as a blank image.
4. **Performance budgets:** slice-to-start post-processing stays under 15 s on the 24 MB golden G-code, and bounds parsing stays under 8 s on 1M lines. A test enforces each budget.
5. **Commit gate:** CI and `scripts/home-update.sh` run `python3 -m pytest tests` and refuse or roll back a bad update.
6. **Old/new oracle:** when a safety function is rewritten, the old implementation stays in the test file as a reference, and a differential test runs both over the golden corpus.
7. **Live acceptance after deploy:** one real Discord dry run (link, buttons, Cancel), then one real print. Watch the timestamps: click to "Preparing" must take under 90 s.
