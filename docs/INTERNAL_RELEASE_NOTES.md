# Print Handy Internal Release Notes

# Unreleased

- Fit options below 100% (live report, AD5X, a 231 x 157 x 135 mm single-body STL): the question described a turned size that fits at 96.3% but offered only "Shrink to 91.6%" and Cancel. The largest sizes that really fit are now buttons, best first (a turn or rotation, a rotation that needs supports only when it is larger than the no-support ones, and a plain shrink only when no turn beats it), and typed "shrink" or a percent resolve to them. The "type ..." hint lists only the actions offered, so it no longer says "split" when there is nothing to split, and the question shows the measured size instead of "measured dimensions unavailable". The tight-fit brim is now chosen only when the part stands on a small contact patch: a wide flat base gets no brim (it used to reserve 3 mm per side), a turned option is sized and sliced with its own brim rule rather than the authored layout's, and the 5 mm small-contact brim is budgeted into that option's size. A rotated single copy is now checked the way it is sliced (bed-centered, no re-arrange), which removes about 1 mm per side of false slack from the check. A single-body model skips the rearrange and split searches, and the convex-hull and vertex passes behind the size search are cheaper, so the check on that model drops from about 49 s to about 15 s. Cutting one oversized body into glued pieces is not built. Offline-tested; the timing and sizes above were measured with the real Orca on a development machine, not on the live bot.

# Version 2.2.0

**Release Date:** 2026-10-29
**First live check owed:** printing from chat on a screenless AD5X (`display_off=1`, which includes every HelixScreen setup) is new in this release and offline-tested only. See docs/DEVICE-AD5X.md.

**Needs a migration on the box:** the setup wizard's preset-answer environment variables are renamed `PB_<KEY>` → `PRINT_HANDY_WIZARD_<KEY>` (clean break, no alias; #590, following the #446/#504 pattern). Only operators who preset wizard answers in their shell environment are affected, and only at their next wizard run — a running install never reads these variables. Diagnostics reference codes in chat, logs and doctor rows are likewise renamed `PB_...` → `PH_...`; nothing to migrate there, and docs/DIAGNOSTICS.md lists the old → new codes.
- The second OrcaSlicer channel is renamed from `alpha` to `preview`, and the CI slicer jobs are renamed with it (#600): channel names and job names now describe the role, not the upstream stage, so they stop drifting every time upstream moves from alpha to beta to a release candidate. The channels are `stable` and `preview` (`PRINT_HANDY_ORCA_CHANNEL=stable|preview`); the CI jobs are "Slicer test (stable)", "Slicer test (preview)" and "Slicer test (bambu)", and branch protection on `main` now requires "Slicer test (stable)" in place of the old `real-slicer` check. What installs need to do: nothing is required — `PRINT_HANDY_ORCA_CHANNEL=alpha` still works as an alias for `preview` in this release and prints a startup notice saying so, but switch it to `preview` when convenient, because the alias will be removed in a later release. Which OrcaSlicer build each channel pins did not change (both pin v2.5.0-beta); the exact pinned build is recorded in `docker/orca-prebuilt.sh` and in the image's build-info files, nowhere else.
- Direct file links (#607): a public link straight at a `.stl` or `.3mf` file now works on any host, not just the known model sites — including Dropbox share links (`/s/` and `/scl/`, rewritten to the download form), which is the route for files too big for Discord. The fetch is guarded because the URL comes from chat: the destination must resolve to a public address before connecting and again after every redirect (5 max), the download streams under the shared 200 MiB intake limit, the file is named from `Content-Disposition` or the final URL, and the saved bytes are sniffed (a web page under a file name, or a non-archive `.3mf`, is refused with the cause named) before entering the same check/audit preparation path as an upload. Failures post in chat with the cause and remedy via a curated direct-link error branch in prepared intake. Links that are not files keep the unsupported-link refusal, which now mentions direct file links. Nothing changes for existing sites or uploads.
- Bundled OrcaSlicer bumped from v2.5.0-alpha to v2.5.0-beta (upstream prerelease, published 2026-10-27, tag commit `345efec64c7b95a05ce5cf96df0dde66a158835c`): both channels in `docker/orca-prebuilt.sh` pin the beta AppImages (amd64 `15b0e9f9…`, aarch64 `941ea21d…`), the real-slicer CI legs download the beta flatpak (`2d2f6979…`), and every generated-template vendor pack gains checked 2.5.0-beta identities (tree + packed cache, computed from the beta source tree and the SHA-verified beta AppImage with the shared flatten pipeline; BBL `02.08.00.16`, Anycubic `02.04.00.10`, Elegoo `02.04.00.13`, QIDI `02.04.00.19`, Prusa and Creality kept their alpha vendor versions). The alpha channel keeps its name — it is the prerelease channel; it pins the same beta build until upstream publishes a newer prerelease. Alpha and 2.4.2 identities are retained, so folders generated from them keep verifying. Not verified on live hardware.

**What users can do now:**
- Container timezone: the Docker image now carries a timezone variable, `TZ`, defaulting to `America/New_York` (the tz database is installed and `/etc/localtime` points at the default zone). Compose passes `TZ=${TZ:-America/New_York}`, and `.env.example`, the Unraid template and the settings docs carry the variable. Set `TZ` to any IANA name (for example `Europe/London`) to run the container in another zone; an unknown name is logged at startup and the default is used. Log timestamps, scheduled and timed features and the bundled Spoolman now follow the container zone out of the box instead of UTC. Chat display times still follow `discord.timezone`.
- One connect flow for every model site that needs a credential, and `/print-source` (#462, #464): a MakerWorld, Thingiverse or Cults3D link with no token or key saved no longer dead-ends either; the bot offers **Connect <site> account** with that site's own steps and a link to its docs section, and carries on when the operator presses **Saved, try again**. An expired or refused login is offered as **Renew <site> login**. Every credential can also be a variable (`MAKERWORLD_TOKEN`, `THINGIVERSE_TOKEN`, `CULTS3D_TOKEN`, `CREALITYCLOUD_TOKEN`, `THANGS_TOKEN`, `NEXPRINT_TOKEN`, `MYMINIFACTORY_OAUTH_TOKEN`; a saved file wins). New `/print-source` lists every site and whether it is connected, expired, listing-only or unsupported, without ever showing a value. Thingiverse was verified end to end with an operator App Token on 2026-10-29.
- Cults3D links work against the live API now (#462): the lookup shipped in #553 had only been tested offline and never matched a real creation (it asked for a Relay `node` with a padded base64 id; Cults' ids are unpadded). It now uses Cults' `creation(slug:)` query and also reports the listing's license. Verified live on 2026-10-29 with an operator key. Downloads are still not possible: Cults' API exposes no files, by design.
- MyMiniFactory downloads now work through MyMiniFactory's documented OAuth sign-in (#464): MyMiniFactory links were inventory-only; now the bot's **Connect MyMiniFactory account** button walks through registering an app once (Account Settings, Developers), signing in on MyMiniFactory's own page, and saving the resulting address as `~/.config/myminifactory/oauth_token` (or `MYMINIFACTORY_OAUTH_TOKEN`). Verified end to end on 2026-10-29. The sign-in lasts 7 days. Downloads never carry the sign-in token to MyMiniFactory's file-storage host, and a Cloudflare robot check is a plain stop.
- Thangs and Nexprint (Elegoo) model links are now supported, and MakerOnline (Anycubic) links are recognized inventory-only (#464). Thangs and Nexprint are built the same way as Creality Cloud: the model summary and STL/3MF list come from the JSON API each site's own web app uses, with no login, and the download uses the operator's login token saved as `~/.config/<site>/token`. Both were verified end to end with operator tokens on 2026-10-29 (a real download from each). Thangs login tokens last 7 days, so expect a weekly reconnect. MakerOnline lists a model's files and then stops with a named gap: with a valid login token its download service still refused every request without a browser device-fingerprint token, which Print Handy never fakes. When a download needs a login that is missing, expired or refused, intake no longer dead-ends: the bot offers a **Connect <site> account** button, posts the walkthrough (sign in, which cookie to copy, the exact command to save it on the Print Handy machine; the token is never pasted in chat), and retries the same download when the operator presses **Saved, try again**. This covers Creality Cloud too. Also fixed in Creality Cloud downloads, all found by the first live download on 2026-10-29: the API refuses the login token unless the account's user id is sent beside it, so the saved login is now `model_user_id:model_token` (both cookies); the success answer lists files under `downloadUrls`, which the parser now reads, taking the requested file's entry; and a `.3mf` source was refused because a 3MF is itself a zip and was unpacked as an archive. Creality Cloud downloads are now verified end to end. Thangs downloads a whole model (a zip is unpacked to the chosen part), and paid or membership models are never bought or unlocked.
- Creality Cloud model links are now supported (#604): pasting a `crealitycloud.com/model-detail/...` link runs the same intake as the other model sites — the model summary and its source-file list come from the JSON API the Creality Cloud web app itself uses (no login needed for those), the file the link's `profileId` points at is offered first, and the chosen STL/3MF is resliced locally; site print profiles and pre-sliced G-code are never used. Downloads need the account login token the web client keeps in its `model_token` cookie, saved as the only content of `~/.config/crealitycloud/token` (see PROJECT-REFERENCE, "Creality Cloud login token"); without it, intake stops at download time naming that file, and a refused or expired token is named as a token problem. A model whose file list has no source files stops with that reason named. Live-verified 2026-10-29: model lookup, file list and the token gate; the download leg itself awaits a first run with an operator token. The supported-source enumerations name it as well: the bot help and unrecognized-command reply, SETTINGS' token-file notes, the STANDALONE and DESIGN guides, and the Hermes model-source retrieval reference.
- Oversized multi-part models that fit one plate once rearranged just print: when the author's layout doesn't fit the bed but every part fits one plate at 100% after moving or turning parts, Print Handy does it and says so in one line ("… does not fit the bed as the author laid it out, so I rotated and rearranged the 9 parts onto one plate at 100%.") instead of asking. It still asks when no full-size one-plate arrangement exists, and never overrides a size or orientation you already chose. The fit check's progress is one status message that names what is being tried and the time so far ("Still checking the fit: trying rotations and smaller sizes (40 s)."), edited in place on Discord, Matrix and Telegram.
- Denser plates by default: part gaps and margins are now one setting, `layout.spacing` (`minimum`, `low`, `medium` (Standard), `high`; environment `PRINT_HANDY__LAYOUT__SPACING`). The default `minimum` uses the smallest values measured safe with the real Orca slicer — 2 mm between parts, 1 mm from the bed edge (plus the brim width when a job has a brim), the prime tower 3.5 mm from parts and 4 mm from the bed edge — instead of the old fixed 5–10 mm gaps, so more models fit one plate (the 9-part Duplo swing now fits one multicolor plate with its prime tower). `medium` restores the previous gaps; any individual gap key still overrides the preset. `printer_state check` prints the active preset and values. docs/SETTINGS.md has the table and how each minimum was measured.
- See the real reason when a model link fails: when the cause is a known, operator-fixable one — a missing or expired MakerWorld, Thingiverse, MyMiniFactory or Cults3D token, a site robot check, a site whose files cannot be downloaded through Print Handy, or Spoolman not answering — the chat post now names the cause in plain words and says what to do (for a token: the site, the credential, and the docs section that explains it), instead of a generic "stopped before it was ready". Resending the link is only suggested when the failure is transient and a retry can help; a genuinely unknown failure keeps the `/print-handy bundle` hint. Issue: #590.
- Never type a hex color, and never lose a slice to a missing one: every spool records a color code derived from its color name and finish ("matte white" → white; a blend like "rose red blue green" records its first color plus all of them as Spoolman multi-color hexes), a picked swatch or label read wins, and the new-spool walkthrough asks with swatch buttons only when the name cannot be read. Picking a spool for a slot confirms that slot's color. Slicing falls back from the slot record to Spoolman, the printer's reported slot color and the name, and only then to neutral gray — which chat says before slicing; existing blank slots are backfilled on read and by the listener at startup, never overwriting a valid color. Live failure 2026-10-29 (AD5X multicolor and one-color jobs).
- Understand a refused slice: a deterministic refusal now says why in plain words ("Slot 1 (Matte white PLA) was never confirmed as loaded … Is Matte white PLA loaded in slot 1?"), carries `PB_SLICING_CONFIGURATION` instead of `PB_SLICING_UNKNOWN`, and offers the safe one-tap fix instead of a blind retry that would fail the same way.
- Use a pre-sliced job sliced for a Sovol-style Klipper printer: a job led by a bare `START_PRINT` (Sovol stock style, for example the Sovol Zero profiles) is no longer refused as "missing PRINT_START" — the start check proves its bed and nozzle temperatures from the file's `M190`/`M109` heater lines, or from `BED_TEMP`/`EXTRUDER_TEMP` arguments when the macro call carries them, before anything prints. Jobs Print Handy slices itself are unchanged. Issue: #612.
- Running the AI features on Cloudflare's free tier: a new guide, [docs/CLOUDFLARE.md](CLOUDFLARE.md), sets up chat and design through Workers AI's OpenAI-compatible endpoint (`llm.chat_url`, `llm.model`, `LLM_API_KEY`), the camera watchdog through `PRINT_VISION_URL`, and lookup by meaning through `PRINT_FUZZY_URL`, with the free-tier limits, a rough usage estimate per feature, and what each feature sends out of the house. Two reference Workers ship with it under `examples/cloudflare/`: `fuzzy-lookup` (the `PRINT_FUZZY_URL` contract from #468: Workers AI embeddings, stateless, exact matches answered without a model call, embeddings cached in memory, quota or model errors reported as `degraded`, a capped request size) and `vision-verdict` (the `PRINT_VISION_URL` contract: a Workers AI vision model whose answer is mapped onto the verdicts, anything unreadable becoming `uncertain`). Both carry their secret in the URL path and answer 404 without it. Not live-tested: no Cloudflare account was available, so the Workers are tested only against a mock AI binding (`node --test "examples/cloudflare/**/*.test.mjs"`, also run by `tests/test_cloudflare_examples.py` when Node is installed). Cloudflare's prices and limits were checked against its documentation on 2026-10-29.

**Fixes and reliability:**
- AD5X on screenless ZMod (`display_off=1`, HelixScreen or no screen): Print Handy can start prints from chat. It used to fail with a traceback that kept the plate claimed, because the start route read the stock firmware's API, which does not answer screenless. Screenless starts now use one `SET_ZCOLOR`, as ZMod's own print-file macro does, with the idle check from Moonraker (ready, standby, both heater targets 0) and slot presence from `zmod_color`, shared with the listener's screenless reader. An unknown screen mode refuses before upload. Offline-tested; the first screenless print from chat is its live check.
- `/print-firmware` no longer says "up to date" when the printer did not report the latest version. A live AD5X on ZMod 1.7.5-2 reports `?` for every git component, so it was always told it was current. Those rows now say "latest version not reported", the report says it cannot tell, and `/print-firmware update` refuses that component instead of guessing.
- `/print-calibration mesh` turns the heaters off (`TURN_OFF_HEATERS`, checked by readback) as soon as the new mesh reads back, instead of leaving the bed and nozzle hot while the Accept/Discard question waits. If the readback cannot confirm it, the result says so.
- Camera checks and roasts work with a local OpenAI-compatible server (Ollama, LM Studio, llama.cpp) that takes no key: `CLIPROXY_API_KEY` is no longer required when `services.vision_chat_url` points at this machine or the LAN. A hosted endpoint still needs its key. New SETTINGS section "Model endpoints" lists which URL, model and key each AI feature uses.
- Docs: the fuzzy matching shipped in #468 (typo-tolerant `/print-lookup`, did-you-mean for commands, the `/print-again` pick-list) is now in the README and project reference; ZMOD.md no longer says Print Handy ignores the 1.7.5 3MF path, the AD5X guide states that `auto` already sends `.gcode.3mf` on 1.7.5 and that KAMP sees no object labels, and the live-verified claims across ZMOD, CALIBRATION and DEVICE-AD5X now agree.
- Docker: a Telegram or Matrix bot now starts in the container. The supervisor started the bot only when `DISCORD_BOT_TOKEN` was set, so a Telegram- or Matrix-only container ran no bot while the healthcheck reported it fine; a new gate (`python3 -m print_handy.bot_gate`) checks the configured platform's own token, and the healthcheck uses the same decision.
- Web UI: on a loopback install without an access token, a request whose `Host` (or, on a POST, `Origin`) is not a loopback name is refused, closing a DNS-rebinding route by which a hostile web page could read the form token and change settings.
- A brim no longer crosses the bed edge on rearranged multicolor plates: the merge planner and the per-slot rearranger now keep the edge margin plus the job's brim, as the single-plate arranger already did (this mattered since the `minimum` spacing preset made the margin 1 mm).
- An expired or invalid MakerWorld token is named as such (and offered as **Renew MakerWorld login**) instead of a raw "HTTP Error 401" with the generic bundle advice.
- `/print-design` with a model link keeps the real cause of a failed download (a missing token, a robot check, a size limit) instead of "check the link is public".
- A slice is no longer reused after the layout spacing or prime-tower settings change: they are part of the slice recipe now (recipe version 2; slices stored under version 1 are re-sliced, not reused).
- Printing one color of a multi-filament project works again on OrcaSlicer 2.5.0-beta: a plate derived from a 3MF that declares more filaments than the plate uses (a per-color plate, a one-color merge, or a two-filament MakerWorld file printed in one color) was rejected with Orca error -5 ("filament_is_support's count 1 not equal to filament_colour's size 2"). The derived plate's project settings now declare exactly the one filament the plate uses; OrcaSlicer 2.4.2 still slices the same plates. Real-slicer tests now cover a two-filament source.
- Per-part color jobs with "100% · rearrange 1 plate" no longer fail to slice with "part group does not fit the target bed without cropping" (seen live on the AD5X with a 9-part Duplo swing): slicing now applies the rearrangement — one multicolor plate when the parts and the prime tower fit, otherwise one packed plate per color — and a per-part job is only offered a one-plate rearrangement the slicer can honor.
- The fit question no longer contradicts itself ("does not fit … as one plate" next to a "rearrange 1 plate" button): it says whether the author's layout or a rearranged one is meant.
- The fit check is much faster on dense multi-part models: the split planner no longer re-parses the whole 3MF for every part (a 9-part, ~200k-triangle model went from 89 s to 6 s for that step), the split checks stop once a full-size one-plate fit is known, and the generic split check is skipped when a concrete split plan exists.
- Failures that carry a specific, user-safe cause are no longer reported as `*_UNKNOWN`: the intake path and the other diagnostics surfaces classify them into a real category (for example a missing MakerWorld token is now `PH_INTAKE_CONFIGURATION`, not `PB_INTAKE_UNKNOWN`), and the reference codes themselves say `PH_` (Print Handy) instead of `PB_` (the old Print Buddy name) everywhere users see them. Issue: #590.
- Cleaner chat text during model intake: a long model summary is cut at a word with an ellipsis (no more "so I extended the."); color questions for identical parts name the part once ("Choose one color/material for the 4 chains (15 x 87.7 x 6 mm, author made them Pink)") instead of repeating it four times; the summary before slicing groups identical parts ("2× frameLeg: Matte white PLA"), starts with "Ready to slice" and no longer ends with a stray "time after slicing"; and material names display normalised (Pla shows as PLA, silk pla as Silk PLA) in that summary and on slot buttons. Spoolman and job records are not changed.
- Container logs no longer carry `TIMING {...}` lines on stdout: launch timing goes to the debug log (and still to each job's `TIMING.jsonl`).
- `python3 -m print_handy.doctor` no longer reports a false `FAIL  orca cli: ... --help exited -6` inside the Docker container. OrcaSlicer writes `00000.log` into its working directory and aborted because `docker exec` starts in `/app`, which the container user cannot write; the doctor's OrcaSlicer probe and the `/print-handy debugging` slicer version check now run from a temporary directory. Slicing was not affected.
- Docker docs: Unraid users are pointed at the Community Applications template's new optional **Account tokens** path (`/data/.config`), which keeps MakerWorld, Thingiverse, MyMiniFactory and Cults3D tokens across container updates.
- `/print-macros` no longer describes one printer's macros with another printer's registry entry: macro classification and the run confirmation are scoped to the configured printer model, so a Sovol `START_PRINT` is no longer shown as ZMod's AD5X `START_PRINT` (or the other way round). A discovered name with no registry entry for that printer is listed as defined by the printer's own config, with no borrowed description or safety note. Issue: #612.

**Technical details:**
- CI: a new `spelling` check watches prose a pull request adds (Markdown files and the PR description) for British spellings in the color/honor family and asks for the American form; it scans only added lines, offers an allow marker for quoted text, and is not a required check.
- Color codes and the printer screen stay in step (CHANGE_ZCOLOR consistency): mapped launch refuses a slot whose recorded hex differs from the HEX the printer reports in `zmod_color` ("live RGB mapping mismatch"), so the backfill now takes the hex the printer already reports for a slot ahead of Spoolman's color and ahead of any name guess (`filament_color.resolve(prefer_printer=True)`); adopting the screen's own value cannot create a mismatch. A code derived at `/spool` binding is sent to the screen by the existing bind screen sync (`CHANGE_ZCOLOR`, deferred while printing). The listener backfill still sends nothing to the printer: a slot filled from Spoolman or the name while the printer reports no hex is logged as needing `/spool sync`. The IFS insertion prompt stays inventory-only (it never issues a printer command), so a slot bound there with a derived code is reconciled to the printer's hex by the next backfill, or by `/spool sync`.
- The module is `print_handy/core/filament_color.py` (US spelling); the `filament_colour` key inside 3MF project settings belongs to OrcaSlicer and is unchanged. Typed color names still accept the British spellings of "color" and "gray".
- Repository cleanup: a stray OrcaSlicer startup log (`00000.log`, written by Orca into its working directory) was committed to the repository root by accident alongside the OrcaSlicer beta bump; it is removed, and the name is gitignored so it cannot be committed again. No code or behavior change.
- The second OrcaSlicer channel is renamed from `alpha` to `preview`, and the CI slicer jobs are renamed with it (#600): channel names and job names now describe the role, not the upstream stage, so they stop drifting every time upstream moves from alpha to beta to a release candidate. The channels are `stable` and `preview` (`PRINT_HANDY_ORCA_CHANNEL=stable|preview`); the CI jobs are "Slicer test (stable)", "Slicer test (preview)" and "Slicer test (bambu)", and branch protection on `main` now requires "Slicer test (stable)" in place of the old `real-slicer` check. What installs need to do: nothing is required — `PRINT_HANDY_ORCA_CHANNEL=alpha` still works as an alias for `preview` in this release and prints a startup notice saying so, but switch it to `preview` when convenient, because the alias will be removed in a later release. Which OrcaSlicer build each channel pins did not change (both pin v2.5.0-beta); the exact pinned build is recorded in `docker/orca-prebuilt.sh` and in the image's build-info files, nowhere else.
- Bundled OrcaSlicer bumped from v2.5.0-alpha to v2.5.0-beta (upstream prerelease, published 2026-10-27, tag commit `345efec64c7b95a05ce5cf96df0dde66a158835c`): both channels in `docker/orca-prebuilt.sh` pin the beta AppImages (amd64 `15b0e9f9…`, aarch64 `941ea21d…`), the real-slicer CI legs download the beta flatpak (`2d2f6979…`), and every generated-template vendor pack gains checked 2.5.0-beta identities (tree + packed cache, computed from the beta source tree and the SHA-verified beta AppImage with the shared flatten pipeline; BBL `02.08.00.16`, Anycubic `02.04.00.10`, Elegoo `02.04.00.13`, QIDI `02.04.00.19`, Prusa and Creality kept their alpha vendor versions). The alpha channel keeps its name — it is the prerelease channel; it pins the same beta build until upstream publishes a newer prerelease. Alpha and 2.4.2 identities are retained, so folders generated from them keep verifying. Not verified on live hardware.

# Version 2.1.9

**Release Date:** 2026-10-29
**Upgrade note:** on ZMod 1.7.5+ printers the default `printer.zmod_delivery_format: auto` now sends prints as `.gcode.3mf`, because the ZMod version is finally readable. Set it to `gcode` to keep plain G-code until the 3MF on-printer checks (#564) are done.

**What users can do now:**
- Calibrate the printer from chat: `/print-calibration` runs calibrations with a before/after accept pattern — Print Handy shows the current values first, asks with the heat/motion/noise warnings, runs only while the printer is idle, then shows the new values and the signed differences and asks again before anything is saved, and writes a record either way (`/print-calibration records` lists them). On ZMod printers: full bed mesh via AUTO_FULL_BED_LEVEL with SAVE=0 on screenless installs (report + screen guide on native installs, whose screen owns the mesh), extruder/bed PID via raw PID_CALIBRATE at a temperature you pick — never ZMod's auto-saving PID_TUNE macros; discard restarts Klipper to drop the unsaved values — input shaper via ZSHAPER, and the report-only belt check; bed screws are a guide (the tune waits for its own confirmation at the printer) and the Z offset is report + guide in every mode (the native screen and the screenless store are separate values; both are adjusted during printing, not from chat). Generic Klipper printers get BED_MESH_CALIBRATE, PID and SHAPER_CALIBRATE, plus a driven SCREWS_TILT_CALCULATE measure/adjust/re-measure loop where configured. Vendor forks and non-Moonraker printers are refused plainly, and a calibration is offered only when live discovery finds its primitive on the printer. Nothing is live-hardware verified. Issue: #565 (stages 0–1).
- Check and update printer firmware from chat: `/print-firmware` reports each Moonraker component's current and available versions (on ZMod printers it also flags an OS↔`zmod` version pairing mismatch and an out-of-step Klipper 13 MCU when the data exposes them), `/print-firmware update <component>` applies one component update behind a confirmation showing the exact version change — ZMod and vanilla Klipper printers only, idle printers only, verified afterwards by re-reading the firmware state — and `/print-firmware guide zmod` / `guide stock` walk through the manual ZMod base and stock firmware updates on the AD5X family. Vendor Klipper forks (Neptune 4, Creality, QIDI, Kobra 2) are reporting-only by design — Elegoo warns upstream updates break the Neptune 4 — and Bambu, Prusa, Centauri Carbon, stock Flashforge and OctoPrint/Marlin printers get their manual update guidance instead; the full matrix is docs/FIRMWARE-UPDATE.md. Nothing is live-hardware verified. Issue: #561.
- Use Print Handy with Anycubic printers: the Klipper-based Kobra 2 family (Kobra 2, 2 Neo, 2 Pro, 2 Plus, 2 Max) gets a dedicated `anycubic` vendor with per-model dimensions and identity-pinned generated Orca templates — on installs where Moonraker is exposed, since the family's stock firmware is Anycubic's closed Klipper-derived firmware with no stock Moonraker endpoint (community firmware such as Rinkhals exposes one; the caveat is stated up front in the new Anycubic doc) — and eight Marlin models (i3 Mega S, Vyper, Chiron, 4Max Pro 2, Kobra, Kobra Neo, Kobra Plus, Kobra Max) ship as OctoPrint presets with real dimensions. The Kobra 3 / S1 generation is deliberately not covered: its profiles open with Anycubic's proprietary G9111 start command, which no Moonraker host runs, and the new guard refuses G9111-led files. Nothing is live-hardware verified. Issue: #552.
- Look things up with typos: `/print-lookup` now forgives misspellings ("adheison", "nozzel clog") and ranks the entry you meant first, using a deterministic on-device similarity score — no LLM and no network involved, and exact matches behave exactly as before. A near miss is only ever a ranked suggestion; lookup stays read-only. Issue: #468 (stage 1).
- Reprint by an almost-right name: `/print-again funco shelf` now answers with a numbered "Did you mean one of these?" list instead of a flat no-match, and you pick by number as usual. A fuzzy match never starts a reprint by itself, and print numbers stay exact. Issue: #468 (stage 2).
- Typo a command and get asked, not stuck: `/spol list` now gets a "Did you mean `/spool list`?" prompt with Yes/No buttons (60 seconds to answer). Nothing runs unless you say yes, and the command still shows its own confirmation before anything prints. It works with no AI chat configured, and plain chat never triggers it. Issue: #468 (stage 3).
- Optional, for operators who run one: set `PRINT_FUZZY_URL` to a semantic-search endpoint and a `/print-lookup` that matches nothing locally ("bed won't stick") can come back with meaning-level suggestions, labelled as the endpoint's. It is off unless configured, stateless, and any endpoint failure quietly keeps the local answer. Local installs that never set it see no change. Issue: #468 (stage 4).
- Serve two printers from one Discord channel: when a channel is claimed by more than one printer, dropping a model link (or running a printer-bound command) asks which printer to use first — one question, answered by button or typed reply — and the job binds to that printer from there; lifecycle posts in a shared channel name their printer. Channel-per-printer routing is unchanged for installs that prefer it. A picker raised inside a thread is posted in that thread, and a typed reply that could belong to two printers' open questions resolves neither rather than crossing answers. Issue: #536.
- Add a printer to a running install from Discord: `/print-handy add-printer` walks through the model, the display name the shared-channel picker shows, and the connection fields for that printer's kind, tests the connection live against the real printer before anything is saved (a failure loops back to the field that failed), and writes the roster entry only at the explicit `apply`. Secrets are never collected in chat — each step names the environment variable to store the value in (per-printer names for Bambu Lab and PrusaLink; the shared OctoPrint and stock FlashForge names are called out as shared when a second such printer is added). A legacy single-printer settings file is converted into the roster on the way, a timestamped backup is kept, and the new printer's first hardware record is created. Nothing is restarted: the flow says plainly that a restart brings the printer live. Issue: #537.
- Get bad-print detection with no LLM and no cloud service: set `vision.local_detector_enabled: true` (`PRINT_HANDY__VISION__LOCAL_DETECTOR_ENABLED=true`) and the camera watchdog judges frames with a built-in ONNX failure detector on this machine (the Obico / The Spaghetti Detective model, AGPL-3.0 weights). The pinned model is about 202 MB — larger than the original research estimated — so it is not in the container image: it downloads once, SHA-256 verified, into the Hermes home and is reused from there; `vision.local_model_path` names your own file instead for a fully offline install. Endpoint routes keep precedence (a configured `PRINT_VISION_URL` or vision chat endpoint is used exactly as before, and the local detector only answers when neither is configured), the watchdog stays alert-only, and any detector failure degrades to `uncertain`, which alerts. The detector recognises failures only: auto light-off still needs a vision endpoint (it cannot certify an empty plate), and roasts and spool-label photo reads are unchanged. Its accuracy on real printer cameras is unverified — the tests are offline fixture frames. Issue: #455.
- The local failure detector now escalates over time, not just per frame: a weak possible-failure detection stays `uncertain` on its first check, but if the next camera check sees a positive too, the verdict escalates to `spaghetti` (checks are minutes apart, so consecutive positives are a sustained failure); a strong detection is still `spaghetti` at once, and its alert text says *confirmed across N consecutive checks* when earlier checks also saw it. A clean frame clears the run, the run is per printer and resets when the print ends, and a detector error neither builds nor clears it. Single-frame thresholds are unchanged, and idle plate checks still judge single frames. Covered by offline sequence tests; live-camera accuracy remains unverified. Issue: #455.
- The local failure detector uses a GPU when the host offers one: at model load it picks the most preferred accelerated ONNX Runtime execution provider the host reports (CUDA, then TensorRT, OpenVINO, CoreML, DirectML, ROCm), always keeps CPU as the fallback, and retries on CPU alone if the accelerator cannot initialise. There is no setting — selection is automatic; the active provider is logged at load and shown on `bot check`'s local detector row. Selection is tested offline against simulated provider lists; live GPU proof on real hardware is still outstanding. Issue: #455.
- Cults3D links are recognised: with an API key stored as `nickname:key` in `~/.config/cults3d/token` (create one at cults3d.com/en/api/keys), the bot confirms the listing through Cults' GraphQL API — and then stops with the gap named, because Cults' API exposes a listing's details only, never its 3D files; downloads happen only through the signed-in website, so the workaround is to download the file in a browser and upload or drop it in the chat. Without the token file, Cults3D intake stops with a message naming the file. Built and tested offline against the documented API shape; live verification waits on the operator's key. Issue: #462.
- ZMod printers can receive prints as `.gcode.3mf`: with the default `printer.zmod_delivery_format: auto`, a print uploads as a `.gcode.3mf` package (the sliced G-code, byte-identical inside) when the printer reports ZMod 1.7.5 or newer — colour mapping is instant with no MD5 preprocessor step and KAMP data is instant, per ZMod's own documentation — and as plain `.gcode` when the version is older or unknown; `gcode` and `3mf` force one format. Every check Print Handy runs still runs on the G-code before packaging, and the plain `.gcode` path is unchanged when it is selected. Nothing is live-hardware verified; the on-printer checks are listed on the issue. Issue: #564.
- See the installed ZMod version in the firmware report: `/print-firmware` on a ZMod printer now always states the ZMod version — the `zmod` component version Moonraker's Update Manager reports — or reports it as unknown when Moonraker does not report one, instead of the report silently having no ZMod line. Nothing gates printing on the version, and docs/ZMOD.md now records ZMod 1.7.5 as the version Print Handy's ZMod contracts were audited against. Issue: #562.
- Know the ZMod version from the doctor and the diagnostics bundle: the doctor (and the Web UI status page's doctor section) now has a `zmod version` row that reads the installed ZMod version live from Moonraker on ZMod printers, and the diagnostics bundle — which embeds the doctor output — carries it into bug reports. A version Moonraker does not report, or a Moonraker that cannot be reached, shows as unknown, named as such; the row never fails the doctor run. Issue: #562.
- Host the Hermes-mode bot in a dedicated profile under any name: the print-feedback plugin no longer hard-codes the profile name `3dprinting` — it derives which profile it is running in from the install (`paths.hermes_home`, or the profile its plugin symlink lives in), so a dedicated Hermes profile named anything works end to end. Existing `3dprinting` installs derive the identical identity and behave exactly as before, and standalone mode is untouched. The dedicated profile itself is still required in Hermes mode — messages the bot does not claim reach the hosting profile's agent by design, and the profile is what bounds that agent — and docs/INSTALL.md now says so and why. When the identity cannot be derived, `bot check` fails its hosting profile row and the plugin logs the problem instead of quietly answering nothing; the tool guards likewise log when they stand down for another profile's session. Issue: #574.

- Read best practices for your printer: the docs gain a "Best practices on specific devices" section, starting with the FlashForge AD5X on ZMod 1.7.5 in screenless mode with HelixScreen — Z offset, bed mesh, purge modes (Nopoop), QuickSwap order and risks, 3MF delivery, and what is and is not verified on hardware. PR: #584.
- `/print-macros` lists ZMod's `_USER_PREPARE_PRINT` as a firmware hook you can fill in, noting that it runs after Print Handy's readiness checks; it is never runnable from the bot. Issue: #562 (#585).

**Fixes and reliability:**
- The supervised AD5X bed mesh no longer gives up after 5 minutes while the printer is still probing, so the new mesh is saved and verified. (#578)
- ZMod screenless mode (Helix or no screen): IFS slot presence is read from Klipper again, so insertion prompts, refill/empty tracking and runout detection work and the listener log no longer fills with a traceback every 15 seconds. A cancel from Helix or Fluidd no longer force-restarts Klipper; answering a runout no longer triggers a second "swap" question; a pause in the first seconds with an empty unused slot is no longer called a runout; a printer-screen error is not reposted after a listener restart. (#579)
- `/print-calibration`: long mesh, PID, shaper, screws and belt runs report their result instead of "The send did not succeed"; an accepted mesh is saved as the profile prints load (`auto` on ZMod), probed at 220 °C / 60 °C; results are found on printers with a long console history; an unanswered Accept/Discard prompt sends nothing; Accept and Discard refuse if a print started meanwhile; the `LOAD_ZOFFSET_NATIVE` guidance is corrected. (#580)
- AD5X multicolour slicing follows ZMod's purge mode: with Nopoop (`USE_TRASH_ON_PRINT=0`) colour changes purge into the prime tower; the default trash-chute mode is unchanged and an unreadable mode keeps it; slicer-controlled mode (`2`) refuses multicolour slicing for now. `printer_state check` shows the purge mode. (#581)
- Completion posts attach the print's own timelapse again, and a reprint no longer gets the previous job's video. A Klipper shutdown wraps up the light, paused prompt and timelapse; a listener restart mid-print keeps the timelapse, auto light and watchdog; "Stop asking for this print" lasts the whole print; an "ok" vision verdict no longer alerts and a dark camera gives one notice instead of repeated alerts. (#582)
- A cancelled print's report shows the real print time and filament used, once instead of twice. Standalone installs with a Hermes home under a profiles folder answer commands again; Docker `add-printer` explains up front that the built-in settings file can't change; multi-printer uploads go to the right printer; alerts no longer repeat the material. (#583)
- Print Handy now sees the installed ZMod version on real printers: Moonraker reports ZMod's components as `?`, so the version is read from the printer's OS info (for example `1.7.5-2`) and `/print-firmware` and the doctor say so. `?` is no longer counted as an available update for Fluidd or Mainsail. With the version readable, `zmod_delivery_format: auto` now selects `.gcode.3mf` on ZMod 1.7.5+. (#585)
- `/print-calibration` Accept no longer reports a failed send after saving: SAVE_CONFIG restarts Klipper and Moonraker answers 503, which is now treated as the expected restart; Accept waits for Klipper to be ready and then confirms the save (seen live on the AD5X; the mesh had saved correctly). (#588)
- ZMod `.gcode.3mf` packages now carry the plate's filament types and colours in `slice_info.config`, where ZMod reads them for colour mapping; before, a 3MF print reached the printer with no colours. (#586)
- A MyMiniFactory link sent to the design flow now stops with the named download gap (MyMiniFactory downloads need a login this build does not have) instead of falling through to the Printables lookup and failing with a misleading "check the link" error. MyMiniFactory links in normal intake were already inventory-only with the gap named. Issue: #462.

# Version 2.1.8

**Release Date:** 2026-10-28
**Needs a migration on the box:** the internal OrcaSlicer override variable is renamed `PB_ORCA_CMD` → `PRINT_HANDY_ORCA_CMD` (clean break, no alias), completing the Print Handy rename (#504). Only installs that set it by hand are affected; the container sets it itself from `PRINT_HANDY_ORCA_CHANNEL`.

**What users can do now:**
- Load a new spool by answering questions instead of typing a command: the conversational intake walks through material (quick-pick buttons, Silk PLA included), colour/finish and weight one step at a time, shows the Spoolman spool number it will get right away — “Preparing new **Spool #N**” — so the number can be written on the spool before anything exists, and creates the spool only at the final confirmation. If the slot already holds a spool, the walkthrough asks what happens to it (back on the shelf, archive it, archive as depleted, or delete) and recommends archive-as-depleted at 0 g. Material variants adjust slicing the same way for every filament — Silk PLA runs the nozzle 10 °C hotter and the outer wall slower — unless the filament's temperatures are recorded in Spoolman, which are always used unadjusted. Issue: #512.
- Or skip the typing: send a photo of the spool's label and the intake reads it — through the vision endpoint when one is configured, or the label's barcode/QR code and on-device text recognition when it isn't — and pre-fills brand, material, colour, weight and temperatures into the same walkthrough. Nothing is created until the confirmation. Issue: #514.
- The new-spool walkthrough no longer asks for the spool's brand by default. Set `spool.prompt_brand: true` (`PRINT_HANDY__SPOOL__PROMPT_BRAND=true`) if you want brand tracked and asked for again.
- Change a nozzle with guidance (#513): the nozzle-change flow heats the hotend for the hot-tighten step, applies the new nozzle type's temperature offset across all filaments (a temperature recorded on the Spoolman filament still wins, unadjusted), and prompts for the calibration prints afterwards.
- Opt in to auto light-off with `vision.auto_light_off_minutes` (30 is the suggested value; off by default): the printer's light turns on when a print starts, and off again after the camera has seen the plate empty for that many minutes once a print ends. A part left on the plate keeps the light on indefinitely — there is no long-idle override. Any print the listener sees counts, whoever started it. The light target is covered on Moonraker printers (named with `vision.light_object`, or auto-discovered when the printer lists exactly one `led` / `neopixel` / `output_pin` object), Bambu Lab chamber lights, and Elegoo SDCP chamber lights (turn-on works there today; auto-off waits on a verified SDCP camera source). PrusaLink, OctoPrint, stock FlashForge and offline printers have no light to switch, and `bot check` says so for those. See docs/SETTINGS.md (Auto light-off). Issue: #516.
- Pick the Qidi X-Plus 4 as `printer.model` (`qidi.xplus4`): a 305×305 bed, 280 mm build height and a 370 °C hotend ceiling, with templates generated from the printer's Orca profile like the rest of the Qidi pack (#500). Not verified on live hardware; see docs/QIDI.md.
- See which version is running at a glance: the startup line of the standalone bot and of every listener (Moonraker, family and Bambu) names the running Print Handy version, and `/print-handy status` in chat shows it as its first line.
- The custom camera-check endpoint contract is written down (#501): if you set `PRINT_VISION_URL`, docs/SETTINGS.md now states exactly what Print Handy posts (image + prompt JSON, no Authorization header), the verdict words it accepts, the 30-second timeout, and that any failure is treated as `uncertain` — which alerts rather than passing silently. A failed call also logs the underlying error, while chat alerts stay in the plain language of #467.
- New home installs default to the standalone bot: an unset `bot.mode` now resolves to `standalone` instead of `hermes`, the shipped `config/home.yaml` / `config/home.toml` templates and the setup wizard offer standalone first, and Docker was already standalone-only. `bot.mode: hermes` remains a supported explicit choice — an existing config that states it is unchanged — with Hermes demoted to an optional `[agent]` endpoint for stray chat. Migration notes for Hermes installs are in docs/INSTALL.md. Issue: #524.
- On a Hermes install, set `discord.clarify_ui = true` to have Print Handy draw its own questions there too (#524 stage 2): it activates its own prompt registry and posts questions by direct Discord REST, resolving clicks and typed answers itself, so Hermes mode renders exactly what standalone (and the README mockups) show. Off by default — Hermes' adapter keeps rendering, unchanged — and `bot check` reports the renderer on its clarify ui row. The standalone bot always used its own renderer and is unaffected.
- With `discord.clarify_ui` on, the Hermes workarounds for host-drawn questions retire for that install (#524 stage 2): the plugin no longer patches Hermes' clarify hint text, and the pre-print Stop step no longer posts a separate Stop prompt there — the standing question is retired in place when the step finishes, or becomes the refusal guidance with its Retry button after a safe refusal. Appearance is unchanged; with the setting off, both workarounds install exactly as before.
- On Discord installs hosted by Hermes, stray chat now follows the same rules as the standalone bot (#524 stage 3): `discord.chat_llm_enabled = false` really means no chat model call — unmatched text gets the short not-understood reply and the Hermes profile agent never sees it; a configured `[agent]` endpoint (or `[llm]`) answers stray chat through Print Handy's own lane instead of the in-process agent, including the honest "the chat agent didn't answer" reply when the endpoint fails. With the switch on and no lane configured, the profile agent keeps answering exactly as before.

**Fixes and reliability:**
- Spool intake is hardened at its two trust points (#522, review fixes on #515): the walkthrough claims its step before finishing, so a double-tap or a retried delivery cannot create the spool twice, and the confirmed spool is verified in Spoolman before any disposition (shelf / archive / delete) runs against it.

**Technical details:**
- Bot independence (#524) landed in stages beyond the user-facing bullets above: listener posts go through the bot's own REST sender in Hermes mode too, with an honest fallback message when a timelapse cannot be attached (#528); the bot's own recent-links file is the only model-link recall source — the Hermes state.db fallback is gone (#525); print-next, spool-change and print-stop prompts register under the live session key (#526); the plugin-owned clarify renderer was built (#529) and then wired (#534, above); /print-design uses the `[design]`/`[llm]` HTTP transport in every mode, with the Hermes profile pin only as the fallback when no endpoint is configured (#530); the bot no longer resets or archives Hermes sessions — that is Hermes' own housekeeping now (#531); and the standalone bot gained its `[agent]` stray-chat lane (#532), whose Hermes-mode parity is the stray-chat bullet above (#539).
- print_alert_buttons builds every Discord API URL from the single shared bot.rest base, so anything that redirects the REST base (including the #358 sandbox) covers button posts too (#502).
- Removed the unreachable `maintenance_airprint_reminder` stub from the listeners (#503).
- README rewritten friendlier: printers grouped by connection, the Docker start shown, LLM vs no-LLM features spelled out, and a bigger Discord walkthrough (#523).

# Version 2.1.7

**Release Date:** 2026-10-28

**What users can do now:**
- The project is renamed **Print Handy** (was Print Buddy), as a clean break with no aliases or fallbacks: the Python package is `print_handy`, every `PRINT_BUDDY...` environment variable is now `PRINT_HANDY...`, state files are `print_handy_*`, the container image is `ghcr.io/catduckgnaf/print-handy` (the old `ghcr.io/catduckgnaf/print-buddy` package stays frozen at the last Print Buddy release), the standalone systemd units are `print-handy-bot` / `print-handy-listener`, the Discord command group is `/print-handy`, and the ZMod plugin and macros are `print-handy` / `PRINT_HANDY`. Existing installs migrate by hand with `scripts/migrate-names.sh` and `docs/RENAME-MIGRATION.md`. Issue: #446.
- Start and pause posts reach the non-Moonraker families too: one shared family control/event mechanism drives the Prusa, Elegoo, Bambu and stock Flashforge listeners (#470).
- Stock Flashforge (AD5X) prints started through Print Handy now get a completion post from a launched-print monitor, with a timelapse attached when `[timelapse] capture_enabled` is on and the printer advertises a camera source. The AD5X has no built-in camera — a camera accessory is required — and the endpoint is protocol-documented but not yet verified on a live AD5X; see docs/FLASHFORGE-STOCK.md.
- Prusa prints started through Print Handy now get a completion post from a launched-print monitor, with a timelapse attached when `[timelapse] capture_enabled` is on and the printer registers a camera with PrusaLink (a USB camera, or the CORE One's built-in camera). A printer or firmware with no camera registered gets the completion post without a video. The camera endpoints are protocol-documented but not yet verified on a live Prusa printer; see docs/PRUSA.md.
- Elegoo Centauri (SDCP) prints started through Print Handy now get a completion post from a launched-print monitor. Timelapse capture is wired into the monitor but stays off in practice: no SDCP camera endpoint is verified, so the post carries no video yet and the log says why; see docs/ELEGOO.md.
- Bambu Lab prints started through Print Handy now get a timelapse attached to the completion post when `[timelapse] capture_enabled` is on: A1/P1 frames come from the port-6000 stills camera (a low-frame-rate stills camera, so expect a slideshow-style video), and X1-family frames — and X1 camera stills generally — come through the go2rtc fan-out of the printer's RTSPS stream, which needs go2rtc enabled with that stream as its source (see docs/BAMBU-LAB.md). Not yet verified on a live Bambu printer.
- Pick a Qidi or Creality printer as `printer.model` and slice for it with per-model profiles instead of the generic Klipper defaults: Qidi Q1 Pro, X-Plus 3, X-Max 3 and X-Smart 3 (`qidi.*`), and Creality's Klipper/Creality OS line — Ender-3 V3, V3 KE, V3 Plus, K1, K1C and K1 Max (`creality.*`) — all on Moonraker with templates generated from your own OrcaSlicer. Creality's Marlin printers are not covered by the new vendor; they keep the OctoPrint route. Neither vendor is verified on live hardware yet; see docs/QIDI.md and docs/CREALITY.md.
- Creality's Marlin printers get built-in OctoPrint presets: Ender-3, Ender-3 Pro, Ender-3 V2 and Ender-3 V3 SE (`octoprint.*`) (#465).
- Prepare models from more places: Thingiverse links resolve through Thingiverse's official API (bring an app token), MyMiniFactory links have their file inventory checked (downloading isn't supported yet, and the bot says so), and Printables models whose files carry no usable geometry are refused up front with the reason (#469, #482).
- `/spool` is guided with buttons: a bare `/spool`, an incomplete `/spool new` or `/spool change`, or a plain request like “add new filament” starts the button flow with no LLM needed; the complete typed forms work exactly as before (#479).
- A spool created directly in Spoolman's own UI now prompts once in Discord — **Load into a slot**, **Leave on the shelf** or **Dismiss** — and loading walks the guided steps. Archived arrivals and deletions stay silent, and a prompt lost to a chat outage is retried (#493, #497).
- A runout pause is classified from the head sensor and slot state, and its post offers reload and resume (#452).
- Discord can run as a pure bot: with `discord.chat_llm_enabled: false`, unmatched text gets the command list instead of a model, while `[llm]` stays available for `/print-design` (#473). Failure and refusal posts are written in plain language that says what to do next (#474), and typing `print 42` reprints job 42 (#449).
- The camera watchdog never posts a dark camera frame as a print alert, and its alerts carry a **Stop asking for this print** button (#480).
- `/print-handy debug on` captures DEBUG logs from the bot and the listener for 30 minutes with no restart, then delivers a sanitized log export in chat, ready to attach to an issue. Nothing is uploaded anywhere (#481).
- Set `logging.level`, `logging.format` (`text` or `json`) and an optional `logging.file` to control how much Print Handy logs and where. Log lines carry a time with offset, severity and component, and the intake id while an intake runs.
- Find slicing trouble in the logs: each OrcaSlicer or Bambu Studio run records its exit code and elapsed time, and a switch to the Bambu fallback is a warning with the reason.
- On Telegram and Matrix installs, completion timelapses are now sized to that platform's own upload limit instead of Discord's: Telegram keeps up to its 50 MB instead of being squeezed to about 9.5 MB, and a Matrix homeserver with a smaller limit gets a video shrunk to fit it.

**Fixes and reliability:**
- A missing timelapse is no longer misreported as a render timeout (#540): `archive_completed_timelapse` now returns an `ArchiveOutcome` (`archived` / `archive_off` / `archive_failed` / `not_rendered`), and the completion flow names each path's actual state — with the SSH archive destination unset the log records that the printer-rendered lookup was skipped (no wait ran) and whether in-container capture was disabled or produced no video; a rendered video that failed to archive is reported as an archive failure in the log and in the completion post ("archiving it failed", not "didn't arrive"); "not rendered within the wait" is reserved for a bounded wait that actually elapsed. The ordinary text completion post is intact in every state. Docs: the two timelapse paths, the off-by-default capture choice, the per-family camera-source requirements and the environment-over-file precedence of `PRINT_HANDY__TIMELAPSE__CAPTURE_ENABLED` (pinned by a contract test in both directions) are covered in docs/DOCKER.md, docs/SETTINGS.md and the Unraid template; the guided setup step itself lands with #537. Offline tests: `tests/hermes/test_timelapse_states.py`, plus state assertions in `tests/hermes/test_print_messages.py`.
- A print that ends at the printer while paused (stopped from the printer screen, job removed, or the printer restarted) now posts its cancelled notice in Discord instead of silence, and the paused message's Resume/Cancel buttons are retired when any print ends, so nobody can tap a button on a job that is already gone.
- Intake failures, fit check failures and slice failures now log the full traceback instead of only a short message in the receipt.
- Credentials are redacted from every log line and traceback.
- A Matrix homeserver whose upload limit is below the smallest shrinkable timelapse no longer loses the video silently: the completion post says the timelapse was recorded but is too large for that server's upload limit.
- The camera watchdog stays off on installs with no vision endpoint configured (including no-LLM installs) instead of posting false print alerts (#499).
- Multi-copy jobs quote time and filament for all copies, not one (#456); Bambu Studio filament totals are read from the 3MF header and its output is recognised by the G-code guard (#448, #441); the Unraid WebUI link points at port 8088 and the bundled Spoolman API can be exposed on the LAN (#445, #439); Matrix print confirmations register under the live session key (#429).

**Technical details:**
- New `print_handy/logs.py` (`configure`, `bind`, `stage`, `redact`). The standalone bot and the listener call `configure()`; the Hermes plugin path does not, so the gateway's own logging is untouched.
- The listener's `log()` helper still writes its legacy file and also feeds the shared logger, so existing tests and `listener.log` readers are unaffected.
- Issue: #150. Offline tests: `tests/test_logs.py`.
- The listener resolves one effective cap in `_media_upload_limit()` (bot-core `core.delivery.upload_limit`, plus the Matrix homeserver's reported `m.upload.size` as a runtime clamp) and `discord_sized_video()` is generalised to `platform_sized_video()`, writing `<name>.sized.mp4`; shrunk files cached under the old `.discord.mp4` name are simply re-shrunk once. Discord's cap, bitrate strategy and fallback wording are unchanged. No live Telegram/Matrix testing was possible (needs the operator's tokens); all proof is offline. Issue: #314. Offline tests: `tests/hermes/test_platform_media_sizing.py`.
- The shrink's compression is ffmpeg's (it always was — the encoder was hard-coded libx264 in the command). It now takes the `[timelapse] encoder` choice (`cpu` default; `vaapi`/`qsv`/`nvenc` for a passed-through GPU) through the `vertical_short` encoder seam, using live_stream's vendor and ffmpeg encoder names (#311); any hardware-encode failure retries the attempt with the CPU encoder, so the never-fail-the-announcement contract stands. No live GPU encode was performed (no GPU on the build machine); selection and fallback are pinned offline with the stubbed-ffmpeg harness. Issue: #314.
- Stock Flashforge timelapse (#373): new `print_handy/hermes/stock_watch.py` launched-print monitor (the #295 Stage 2 adapter-polling pattern, mirroring the Bambu monitor) started by `_print_flashforge_stock` on a confirmed start; new `printers/flashforge_stock/camera.py` reads the `/detail` `cameraStreamUrl` the printer advertises (validated: http, no userinfo, the configured host) and drives `streamCtrl_cmd` through a new `StockClient.control`; `timelapse_capture` gained an MJPEG first-frame reader and an explicit-source `begin(url=...)`, so stock sessions share the #246 storage/caps/retention discipline. Frames encode through the `vertical_short` seam and `platform_sized_video`. Camera facts are from Parallel-7/flashforge-api-docs (the stock client's own protocol source): the AD5X has no built-in camera, `cameraStreamUrl` is empty without an accessory, MJPEG on :8080 `?action=stream`; **not verified on a live AD5X**. Offline tests: `tests/hermes/test_stock_watch.py`, `tests/hermes/test_timelapse_capture.py`, `tests/printers/test_flashforge_stock_camera.py`, `tests/printers/test_flashforge_stock.py`.
- PrusaLink timelapse (#295, stage 1 of the approved Prusa → SDCP → Bambu order): new `print_handy/hermes/prusa_watch.py` launched-print monitor (the #295 Stage 2 adapter-polling pattern, mirroring the stock monitor) started by `_print_prusa` on a confirmed start; new `printers/prusa/camera.py` resolves the camera PrusaLink itself registers (`GET /api/v1/cameras`, first connected) and fetches its stills (`GET /api/v1/cameras/<id>/snap`) through two new `PrusaLinkClient` reads, transcoding the PNG still to a JPEG frame with Pillow so Prusa sessions share the #246 capture storage/caps/retention discipline and the stock monitor's encode seam (`stock_watch.encode_frames` + `platform_sized_video`) unchanged. Camera facts are from Prusa's published PrusaLink OpenAPI specification (the LAN client's own protocol source) and the Prusa-Link-Web frontend built on it: snapshots are PNG-only (204 = no image yet, 304 = unchanged), there is no stream, and which models/firmware expose a camera is the printer's business — an empty list or a 404 reads as "no camera source", logged once; **not verified on a live Prusa printer**. Offline tests: `tests/hermes/test_prusa_watch.py` (including a full lifecycle: real capture session, real PNG stills transcoded, real ffmpeg encode, ffprobe-valid H.264 under the limit), `tests/printers/test_prusa_camera.py`.
- Elegoo SDCP monitor (#295, stage 2 of the approved Prusa → SDCP → Bambu order): new `print_handy/hermes/elegoo_watch.py` launched-print monitor (the #295 Stage 2 adapter-polling pattern, mirroring the Prusa monitor) started by `_print_elegoo_sdcp` on a confirmed start; new `printers/elegoo_sdcp/camera.py` is the vendor's camera seam and resolves to "no source": the SDCP client implements discovery, status (Cmd 0), start/pause/stop/resume (Cmds 128–131) and file list/info (Cmds 258/260) only — no camera command, and no snapshot or stream URL is recorded in the vendor facts or docs; the only other recorded commands (386/403, docs/ELEGOO.md) are chamber light/fan. The monitor's capture leg is fully wired through the shared seam (`stock_watch.encode_frames` + `platform_sized_video`, the [timelapse] settings) so a source verified later slots into the seam unchanged; until then a launched print gets the completion post with no video and a once-per-print log line naming the unverified camera. **Not verified on a live Centauri printer** (the vendor's standing status). Offline tests: `tests/hermes/test_elegoo_watch.py` (lifecycle, standby/error terminals, dedupe, supersede, the fail-soft paths, the production no-source posture through the real adapter normalisation, and a full real-ffmpeg lifecycle through an injected source), `tests/printers/test_elegoo_sdcp_camera.py`.
- Qidi + Creality vendor packs (following the printer-support audit; the #251 Prusa/Elegoo pattern): new `print_handy/printers/qidi/` (Q1 Pro, X-Plus 3, X-Max 3, X-Smart 3) and `print_handy/printers/creality/` (Ender-3 V3, V3 KE, V3 Plus, K1, K1C, K1 Max) packages — Moonraker vendors subclassing the Klipper adapter with per-model sourced facts, identity-pinned generated Orca templates (`scripts/qidi-templates.py`, `scripts/creality-templates.py`) and per-vendor guards. Every dimension is the pinned Orca profile's printable area/height (2.4.2 + 2.5.0-alpha trees and the 2.5 packed cache, three identity pins per model); both vendors renamed their generic PLA filaments in 2.5, so generation takes a 2.5.0-alpha install, the Prusa precedent. Guard asymmetry is deliberate: Qidi's own start macro is `PRINT_START` (never a foreign marker there) and Creality's is `START_PRINT` (the Ender-3 V3 KE's start is fully inline, so no start shape is required). `creality` was previously pinned as a REJECTED vendor in tests/printers/test_vendor_profiles.py; that pin is deliberately reversed (the unknown-vendor case now uses a made-up name, with positive creality/qidi resolution asserted). Registry gains all ten models (42 total). **Not verified on live hardware** (no Qidi or Creality printer available). Offline tests: `tests/printers/test_qidi.py`, `tests/printers/test_creality.py`, plus the shared adapter/vendor-profile suites.
- Rename delivered by #471 with follow-ups #490, #491 and #492; in the same window, release surfaces gate on docker-publish and the docs auto-sync dispatch (#431), a real Bambu Studio CI leg (#435) and the complex slicer corpus (#472) landed.

# Version 2.0.6

**Release Date:** 2026-10-20
**What users can do now:**
- Status steps such as "Checking whether it fits the bed" and slicing now show a single Stop button. The "Other (type answer)" button no longer appears on these steps.

**Fixes and reliability:**
- Fix intake freezing at the fit check and other Stop-guarded steps. The step's result is now returned as soon as the work finishes, instead of waiting up to an hour for someone to press Stop. Stop still cancels a step that is still running. The fit geometry itself was never at fault.
- Remove the Stop button from the message once its step finishes, so a stale Stop cannot be pressed.

# Version 2.0.5

**Release Date:** 2026-10-20
**What users can do now:**
- Control an intake from Discord with Cancel or Stop at supported stages; resume a saved intake after a prompt timeout; and continue an intake after confirming its saved decisions while a background slice is safely reused. Closes #61, #62, and #63.
- Configure supported nozzle diameter and material, with validation, abrasive-on-brass safety refusal, and refusal when no tuned nozzle profile exists. Closes #59.
- Recover from supported printer-side emergencies with guarded panic utilities; load IFS slots while idle; and remap a single-color print to another loaded slot. These controls are software capabilities; they do not imply physical validation here. #88.
- Set Discord prompt timeout values in configuration. #89.
- See clearer start readback that distinguishes preparing, printing, and confirmed extrusion. #87.

**Fixes and reliability:**
- Preserve verified plates when a derived plate fails a safety guard, and bind background slicing to the confirmed source and decisions. #77, #93.
- Harden Spoolman and IFS color/identity synchronization and prevent direct raw stock API requests. #78, #81.
- Make JOB.json writes atomic to prevent concurrent readers from seeing truncated data; repair related offline CI regressions. #79.
- Sanitize foreign 3MF settings and gate unsupported z-hop settings. #86.
- Correct fit margin accounting and feature-aware clearance, including explicit brim handling for tight fits. #85.
- Make Print Buddy scripts ignore the gateway's `HERMES_HOME`; make prompt timeouts configurable. #72, #89.

**Technical and packaging changes:**
- Add a Docker image and setup documentation, plus native Spoolman and configurable Orca runner support in CI. #75, #80, #82.
- Update printer naming in the README. #71.
- Pull request references: [#71](https://github.com/catduckgnaf/print-buddy/pull/71), [#72](https://github.com/catduckgnaf/print-buddy/pull/72), [#75](https://github.com/catduckgnaf/print-buddy/pull/75), [#77](https://github.com/catduckgnaf/print-buddy/pull/77), [#78](https://github.com/catduckgnaf/print-buddy/pull/78), [#79](https://github.com/catduckgnaf/print-buddy/pull/79), [#80](https://github.com/catduckgnaf/print-buddy/pull/80), [#81](https://github.com/catduckgnaf/print-buddy/pull/81), [#82](https://github.com/catduckgnaf/print-buddy/pull/82), [#85](https://github.com/catduckgnaf/print-buddy/pull/85), [#86](https://github.com/catduckgnaf/print-buddy/pull/86), [#87](https://github.com/catduckgnaf/print-buddy/pull/87), [#88](https://github.com/catduckgnaf/print-buddy/pull/88), [#89](https://github.com/catduckgnaf/print-buddy/pull/89), [#90](https://github.com/catduckgnaf/print-buddy/pull/90), [#91](https://github.com/catduckgnaf/print-buddy/pull/91), [#92](https://github.com/catduckgnaf/print-buddy/pull/92), [#93](https://github.com/catduckgnaf/print-buddy/pull/93).

---

# Version 2.0.4

**Release Date:** 2026-10-19
**Needs a migration on the box:** run `scripts/migrate-names.sh --dry-run`, then without it, then restart the listener; printer steps in `docs/RENAME-MIGRATION.md`.
**What shipped:**
- Rename: Print Bitch is Print Buddy everywhere (Klipper macro `PRINT_BUDDY`, plugin `print-buddy`, `print_buddy_*` state files, `PRINT_BUDDY_*` env vars). `[discord] bot_name` sets the bot's name. Closes #53.
- Printer models: one file per printer under `print_buddy/printers/<brand>/` (`flashforge.ad5x`, `sovol.sv06`, `klipper.generic`); `[printer] model` replaces `family`; printer defaults come from the model file; ZMod code moved to `printers/flashforge/zmod/`. Orca inputs for the AD5X and SV06 are unchanged (golden test). Closes #56.
- Stray state files: doctor warns, update and install remove empty or duplicate strays; other profiles are report-only. Closes #60.
- Discord flow corpus: six models run through the intake with fake clicks on every PR, and through real Orca in CI; a gateway `HERMES_HOME` regression test. Closes #58.
- State stays in the Print Buddy profile when the gateway sets `HERMES_HOME` (#57). Camera stall alert sensitivity 1 to 5 (#50).
- CI: Node 24 actions, runner pinned to Ubuntu 24.04.

---

# Version 2.0.3

**Release Date:** 2026-10-19
**What shipped:**
- `model_job._job_for_gcode`: `record_start` matches the started G-code against `JOB.json["gcode"]`, `derived_plates[].gcode` and `multipart_plan.parts[].gcode_path`. Before, only plate 1 resolved, so plates 2+ started with no `multipart_plan_id` and completions never advanced the plan (Valentine's Headphones Stand plates 2 and 3 were reconciled by hand). Closes #48.
- `model_job.copies_supported`: false for multi-plate audits, `full_size_split_plan`, `plate_mode == "separate"` and per-part colors. `prepared_intake` caps the quantity picker at 1 for those jobs and says so; `slice_job` clamps `copies` to 1 and records it. Closes #37.
- `print_mapped_native`: slot material check uses `printer_state.same_material` (PLA == PLA+).
- `scripts/home-update.sh`: interpreter order `$PYTHON`, Hermes agent venv, `python3`. `tests/test_home_update.py` strips `settings.LEGACY_ENV` from the subprocess environment.
- Tests: regression tests for #37 and #48 fail on 2.0.2 and pass here.

---

# Version 2.0.2

**Release Date:** 2026-10-19
**What shipped:** the full runtime moved into this repo with a symlink installer and a personal overlay; settings file and update script with rollback; printer families (flashforge_zmod, generic_klipper, sovol_klipper) routed through the adapter on the print-now path; plate picker and combined multi-plate timelapse; spool swap override; per plate estimates; CI with real Orca and Spoolman. Closes #19.

---

# Version 2.0.1

**Release Date:** 2026-10-18
**What shipped:**
- `model_job.filament_usage_by_selection` (private): extruder usage shared by several parts is split by part volume, and a volume guess is clamped to the scraped source plate total (`source_site_estimate`). Valentine's Headphones Stand: 5 x 247.8 g = 1,239 g before, 160 g after (MakerWorld: 160.03 g over 4 plates, 20,520 s).
- `prepared_intake.preview_sentence` (private): uses plate `prediction_s` and `weight_g` from the scraped instance instead of "unknown".
- `source_colors.py` (public): `_annotate_parts` and `_shape_word` read `3D/3dmodel.model` bounds and transforms to label generic primitives; volume guessed extruder stats carry `estimated: True`; the per part `[uses ~Ng]` suffix was removed.
- Moonraker listener (private): oversized timelapses are re-encoded under the Discord limit, with a text fallback.
- Tests: 797 passed in the deployed suite; 24 passed in this repository.
- Known open: the duplicate clarify title in Discord is an upstream Hermes adapter change, tracked separately.

---

# Version 2.0.0

**Release Date:** 2026-10-18
**What shipped:** The offline core under `print_buddy/core/`, example Orca templates, an MIT license, and one hardware-free test file. Discord, Moonraker, spool, and archive code stayed off the public tree. This number skips the 1.10 line so it is not read as version 10.

---

# Version 1.10.0

**Release Date:** 2026-10-17  
**Target Hardware:** FlashForge Adventurer 5X (AD5X) on ZMod Klipper + Moonraker with 4-slot IFS. OrcaSlicer 2.4.2 primary, Bambu Studio CLI fallback (both Flatpak).

---

## 1. Inch-Unit STL Detection and Auto-Scale

### Problem Statement
- An STL exported in inches (2.30 x 2.55 x 4.02 units) was read as millimeters, producing a 4 mm model. Orca returned `-100 Failed slicing the model`, which hid the cause. A direct-upload retry carried no `scale` in `JOB.json`, so it failed identically.

### Implementation Details
- **`model_job.py`**:
  - Explicit scale now uses `scale if scale is not None else job.get("scale")`, so a falsy check can no longer drop a user value; non-positive scales raise.
  - When no explicit scale is set, the source is `.stl`, and `max(sx, sy, sz) < 10.0`, the job is scaled by `25.4` if the result fits `bed_mm` and `max_print_height_mm`; otherwise it raises with the measured and would-be sizes.
  - `job["auto_scale"] = {factor, reason: "inch units", original_mm, final_mm}`; the key is removed when no auto-scale applies.
- **`orca_adapter.py`**: The `0 < scale <= 1` cap was removed (scale must only be `> 0`). Direct STL jobs with a scale or rotation transform vertices before slicing, so every slicer receives identical resolved geometry.
- **`discord_print_summary.py`**: Slice summary adds `Auto-scale: <orig> mm treated as inches, scaled 25.4x -> <final> mm`.
- **Field result:** the same ghost STL auto-scaled to 58.42 x 64.77 x 102.11 mm, sliced, and is printing.

## 2. Bambu Studio Fallback and Percent Line Widths

- Orca remains primary. Bambu Studio runs only after an Orca slicer failure or exhausted Orca conflict handling. Validation and placement refusals stay fail-closed and never invoke Bambu. Provenance records the producing slicer, and Discord is alerted on fallback.
- Bambu Studio CLI reads Orca percent widths (`110%`) as millimeters and exits `-18` / `238` with `too large line width`. The fallback-only process copy now resolves `inner_wall`, `outer_wall`, `top_surface`, `sparse_infill`, and `support` line widths against the machine `nozzle_diameter` (0.4 mm: 110% → 0.44, 93.75% → 0.375). The Orca template is unchanged A malformed width fails closed instead of passing a percent value to Bambu.

## 3. Acceleration Profile

| Feature | Before | 1.10.0 (mm/s²) |
|---|---:|---:|
| Default | 1,000 | 4,500 |
| Outer wall | 5,000 | 3,200 |
| Inner wall | 5,000 | 4,500 |
| Sparse / internal solid infill | 1,000 / 7,000 | 4,500 / 4,500 |
| Top surface | 2,000 | 3,000 |
| Travel | 10,000 | 4,500 |
| Initial layer / initial travel | 500 | 500 / 500 |

- Binding limit: X input shaper EI at 52.4 Hz recommends 4,747 mm/s². Moonraker reports `max_accel` 20,000, `minimum_cruise_ratio` 0.5, `square_corner_velocity` 9.0 (read only).
- Offline Orca estimate, Raskog large bin: 14h 26m → 10h 38m (26% less). Physical quality is validated by subsequent real prints only.

## 4. Multi-Copy Clone Placement

- For transformed STL input with `copies > 1`, clones are laid out in a grid with 10 mm gaps and written to `clones.stl`; the slicer receives one pre-placed mesh. A job raises when the grid does not fit the bed.

## 5. Reliability Fixes (Fast Track)

- **State:** `require_idle_settled` rereads Moonraker and native state together (up to 90 s, 5 s interval) before reporting preparing or idle.
- **Cancel:** listener posts a short acknowledgement first and collects the Klipper report asynchronously; bot-originated cancels no longer auto-restart firmware.
- **Notifications:** completion and timelapse are coalesced into one post; lifecycle notices are deduplicated by job identity (history id or filename plus start time) persisted in profile state, so reconnects do not replay them.
- **Color mapping:** explicit color decisions resolve to IFS slot and Spoolman spool identity, independent of the active spool.
- **Translation:** part name dictionary extended (for example `peine` → `comb`), bound to the 3MF part key and extruder.
- **Orca conflicts:** conflict logs map to overlap or intersection remediation; no redundant estimate slice.
- **Slice guard:** pre- and post-slice checks pin `machine_start_gcode` (SHA256, mesh name normalized), `machine_end_gcode`, `post_process`, `host_type`, and `printer_technology` to an approved baseline.
- **Service:** the Moonraker listener is `PartOf` the gateway, so a gateway restart always reloads listener code.

## 6. Test Suite Verification

- Deployed suite: **724 passed, 46 subtests passed** (2026-10-17 17:16 ET).
- New regressions: inch STL auto-scales and Orca receives scaled geometry; explicit scale overrides; oversize after 25.4x fails with size message; auto-scaled two-copy STL exports distinct geometry; Bambu fallback converts percent widths to absolute mm.
- Offline: auto-scaled ghost STL sliced with two copies; Bambu fallback produced G-code on the scaled model.

---

# Version 1.9.1

**Release Date:** 2026-10-15  
**Target Hardware:** FlashForge Adventurer 5X (AD5X / AD5M architecture) on ZMod Klipper + Moonraker with a 4-slot IFS (Internal Filament System) multi-material feeder.

---

## 1. Hardware Boundary Analysis & Margin Tuning

### Mechanical & Stepper Analysis
- **Physical Build Plate:** FlashForge spring steel build sheet measures **235 x 235 mm**.
- **Klipper Stepper Limits (`printer.cfg`):**
  - **X Stepper:** `position_min: -20.0`, `position_max: 225.0`, `position_endstop: 220.0` (Total physical stroke: 245 mm).
  - **Y Stepper:** `position_min: -20.0`, `position_max: 232.0`, `position_endstop: 220.0` (Total physical stroke: 252 mm).
  - **Z Stepper:** `position_min: -10.0`, `position_max: 230.0`.
- **Slicer Bed Configuration:** Nominal printable area remains **220 x 220 mm** (origin `[0, 0]` to `[220, 220]`), preserving standard slicer profile compatibility.

### Margin Contracts
- **`color_geometry.py`**:
  - Centering bounding box margin reduced from `5.0 mm` to `1.0 mm`.
- **`orca_adapter.py`**:
  - `SINGLE_COPY_EDGE_MM`: Reduced from `3.0 mm` to `1.0 mm`.
  - `MULTI_COPY_EDGE_MM`: Reduced from `8.0 mm` to `3.0 mm`.
- **Empirical Validation**:
  - Strandbeest Plate 1 (legs), spanning 215.9 x 217.3 mm, previously threw `RuntimeError: part group does not fit the target bed without cropping` because centered width 217.3 mm exceeded `220 - 2 * 2.5 = 215 mm`.
  - Under the 1.0 mm margin, Plate 1 fits at 100% scale and sliced cleanly to G-code with actual extrusion/travel extents:
    - X: `[2.23, 217.76]` (span: 215.53 mm)
    - Y: `[1.53, 218.47]` (span: 216.94 mm)
  - Both extents remain safely within the 220x220 mm origin coordinates and well clear of the physical stepper travel limits (`-20.0` to `225.0` / `232.0`).

---

## 2. Multi-Plate Capacity Evaluation & Bounding Box Decoupling

### Problem Statement
- In prior versions, `orca_adapter.py:orca_plate_capacity` blindly returned `1` for any multi-plate 3MF file to avoid false negative zero-capacity reports.
- Meanwhile, `verified_scale_choices` evaluated model dimensions by extracting `source_triangles` across the entire 3MF file. In multi-plate Bambu/Orca projects, plates are placed side-by-side in global coordinate space. For the 4-plate Strandbeest, this produced a global bounding box of **501 x 529 mm**, causing `verified_scale_choices` to conclude the model required scaling to `<= 0.41`.

### Implementation Details
- **`_multi_plate_capacity(source, state, scale, single_margin)`**:
  - Inspects `plate_manifest(source)` to extract individual plate object assignments.
  - Uses `color_geometry._world_bounds(archive, object_ids)` to compute the bounding box of each plate independently.
  - Compares each plate's scaled dimensions `(dx, dy, dz)` against usable bed boundaries (`eff_w = bed[0] - 2 * margin`, `eff_d = bed[1] - 2 * margin`, `max_h`).
  - Supports 90-degree bed rotation (`fits = (dx <= eff_w and dy <= eff_d) or (dy <= eff_w and dx <= eff_d)`).
  - Returns `0` if any plate exceeds usable dimensions; returns `1` only if all plates fit.
- **`verified_scale_choices(source, state)`**:
  - Multi-plate 3MF files bypass whole-canvas `source_triangles` extraction.
  - If capacity at 1.0 is `> 0`, returns `[1.0]`.
  - If capacity at 0.5 is `< 1`, returns `[]`.
  - Runs an integer binary search `low, high = 50, 99` over `orca_plate_capacity(..., scale=middle / 100.0)` to find the maximal scale where all plates fit.
  - Returns `_scale_ladder(best_scale)` (for Strandbeest, Plate 3 circular fan at 231 mm yields best scale `0.94`, returning `[0.94, 0.75, 0.5]`).

---

## 3. Multi-Plate Slicing Isolation & Per-Part Grouping Fix

### Problem Statement
1. In `model_job.py:1668`, `_slice_per_plate` contained:
   ```python
   if fit is not None:
       object_plate = {key: 1 for key in object_plate}
   ```
   If a scale factor was passed to a multi-plate model, all parts across all plates were reassigned to Plate 1 and sliced together onto a single plate.
2. In `model_job.py:per_part_fit_options`, parts were grouped strictly by filament slot:
   ```python
   groups.setdefault(slot, []).append(part['key'])
   ```
   For multi-plate models where multiple parts on different plates share slot 3, this attempted to fit all parts from all plates simultaneously onto one bed during fit testing, triggering `RuntimeError` and yielding empty fit options `{'scales': [], 'rotations': []}`.

### Implementation Details
- **`_slice_per_plate`**:
  - Guard updated to `if fit is not None and len(plates) <= 1:`, preserving plate boundaries when scaling multi-plate projects.
  - Added support for per-plate scale overrides via `job.get('plate_scales')`, enabling individual plates to scale independently (e.g. Plate 3 fan at 94%, Plates 1, 2, 4 at 100%).
- **`per_part_fit_options`**:
  - Updated grouping to use `(plate_id, slot)` tuples:
    ```python
    p_id = object_plate.get(str(part['object_id']), 1) if plates else 1
    slot = view['choices']['part:' + part['key']]['slot']
    groups.setdefault((p_id, slot) if plates else slot, []).append(part['key'])
    ```
  - Fit choices `[0.94, 0.75, 0.5]` now correctly evaluate to `honored: True` across all plates.

---

## 4. Conversational Continuity & Link Recovery

### Problem Statement
- When the bot recommended a model and the user replied affirmatively ("Let's do it", "Print it", "Go ahead"), the gateway link dispatcher did not find a URL in `event.text`, skipped the intake pipeline, fell through to LLM chat, and prompted the user to send the link again ("Send a new link to try again").

### Implementation Details
- **`plugins/print-feedback/__init__.py`**:
  - Added `_is_affirmative_followup(text)` matching affirmative intent patterns (`let's do it`, `lets print that`, `go ahead`, `do it`, `start printing`, `yes please print`, `sounds good`, `yep`).
  - Added `_recent_model_link_from_db()`: Queries the 25 most recent messages in `state.db` for MakerWorld or Printables URLs.
  - If affirmative intent is detected without a link, prepends the retrieved URL to `event.text`, automatically triggering the full fresh model intake pipeline.
- **Intake Cleanup**:
  - Removed `"Send a new link to try again."` from `link_intake.py`, `prepared_intake.py`, and `plugins/print-feedback/__init__.py`.

---

## 5. Test Suite Verification

- **Repository Unit Tests (`tests/`):**
  - `python3 -m unittest discover -s tests -v`: 13/13 passed.
- **Scripts & Integration Test Suite (`scripts/`):**
  - `test_orca_adapter.py`, `test_model_job.py`, `test_prepared_intake.py`: 171 passed, 41 subtests passed.
  - `test_plate_merge.py`, `test_source_colors.py`, `test_color_geometry.py`: 42 passed.
  - Total: 213 unit/integration tests passed with 0 regressions.
- **Full Slice Verification:**
  - Strandbeest 4-plate project with scale `0.94` sliced end-to-end via `slice_job`, producing 4 valid G-code plates (Plate 1: 2h 22m, Plate 2: 2h 11m, Plate 3: 1h 14m, Plate 4: 1h 37m).
