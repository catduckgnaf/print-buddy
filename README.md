<p align="center">
  <img src="assets/branding/logo-lockup.png" alt="Print Buddy logo" width="480">
</p>

# Print Buddy

[![CI](https://github.com/catduckgnaf/print-buddy/actions/workflows/ci.yml/badge.svg)](https://github.com/catduckgnaf/print-buddy/actions/workflows/ci.yml)

**Prepare and manage 3D prints from Discord, Telegram or Matrix, with an explicit confirmation before starting a print.**

Share a MakerWorld or Printables link, or upload an STL or 3MF. Print Buddy guides you through model preparation, filament choices and slicing with OrcaSlicer. For configured printers, it can submit an approved job through Moonraker and report progress back to your chat.

[Get started](#get-started) · [Documentation](https://catduckgnaf.github.io/print-buddy-docs/) · [Contribute](CONTRIBUTING.md) · [Releases](https://github.com/catduckgnaf/print-buddy/releases)

## Is it for your setup?

- **Printers:** built-in profiles for Flashforge AD5X, AD5M and AD5M Pro with ZMod, and the Flashforge Creator 5 and Creator 5 Pro with ZMod (four toolheads each), Sovol SV06, Prusa MK4S, CORE One, XL and MINI+ (PrusaLink LAN, opt-in) and Elegoo Neptune 4, 4 Pro, 4 Plus and 4 Max (Moonraker) plus the Centauri Carbon (SDCP LAN, opt-in), plus a generic Klipper/Moonraker adapter. A generic adapter is not a tuned or physically verified profile for every printer. The Bambu Lab A1, A1 mini, P1P, P1S, P2S, X1, X1 Carbon, X1E and H2S are supported for slicing, G-code checks and Bambu packaging, with opt-in LAN status, upload and gated print start; none has been tested on Bambu hardware, and the dual-nozzle H2D, H2D Pro, H2C and X2D are not supported yet. Bambu Lab printers slice with Bambu Studio by default (set `printer.slicer: orca` to use OrcaSlicer); everything else uses OrcaSlicer. See [ZMod printers](docs/ZMOD.md), [Bambu Lab printers](docs/BAMBU-LAB.md), [Prusa printers](docs/PRUSA.md) and [Elegoo printers](docs/ELEGOO.md).
- **Computers:** Raspberry Pi 4 or 5 with 64-bit Raspberry Pi OS, or any 64-bit Debian or Ubuntu machine.
- **Chat platforms:** the standalone Python bot runs on Discord, Telegram or Matrix with the same handlers, prompts and safety gates; only the transport changes. The Telegram and Matrix bots are pure bots with no LLM: unmatched text gets the command list, and no LLM setting is consulted for them. On Discord you can instead use the Hermes plugin. Use only one mode with a given bot token. See [Discord bot setup](docs/DISCORD-BOT-SETUP.md), [Telegram bot setup](docs/TELEGRAM-BOT-SETUP.md) and [Matrix bot setup](docs/MATRIX-BOT-SETUP.md).
- **The roast:** print-started posts can end with a one-line roast (exactly one per print, when printing begins; completion posts never carry one) of the model, written by `vision.roast_model`. It is enabled by default whenever an LLM/vision endpoint is available (`services.vision_chat_url` plus `CLIPROXY_API_KEY`) — on every platform, Telegram and Matrix included — and `vision.roast_enabled` (env `PRINT_BUDDY__VISION__ROAST_ENABLED`) turns it off without affecting camera checks.
- **Slicing:** requires a compatible OrcaSlicer CLI and the correct printer, process and filament profiles. A Python install alone does not provide a slicer.
- **Offline delivery:** vendor profiles can offer Discord file delivery or an offline Bambu package after slicing. Delivery does not authorize printing. Bambu packaging is not verified in Bambu Studio or on hardware. See [printer profiles](docs/PRINTER-PROFILES.md).
- **Optional integrations:** Spoolman for filament records, camera checks, timelapses and print records. Requirements depend on the features you enable.

## Get started

### Docker

The single-container image ships with 2.1.4 (see [#117](https://github.com/catduckgnaf/print-buddy/issues/117) and [#214](https://github.com/catduckgnaf/print-buddy/issues/214)); the published 2.1.1 image keeps the older three-container stack. The image is at `ghcr.io/catduckgnaf/print-buddy` as a multi-arch manifest for `linux/amd64` and `linux/arm64`, built and checked offline by the publish workflow before it is pushed; see [Docker](docs/DOCKER.md#supported-platforms-192-353) for the platform matrix. 2.1.4 also published a slicer-free `-light` variant; from the next release only the one full image is published ([#353](https://github.com/catduckgnaf/print-buddy/issues/353)).

One container runs the three parts of Print Buddy, started and watched by a supervisor:

| Part | What it does |
|---|---|
| Chat bot | The interface on the configured platform (Discord, Telegram or Matrix): links, uploads, guided slicing, spool commands and print confirmation |
| Moonraker listener | Follows printer events and reports progress, alerts and timelapses back to the chat |
| Spoolman API | Bundled Spoolman 0.27.0 backend for filament and spool records. Print Buddy is its interface: no Spoolman web UI is included, and the API listens only on `127.0.0.1:8000` inside the container |

If any part stops, the container stops so Docker can restart it. The health check covers all three.

1. Copy `.env.example` to `.env` and fill in the token and channel/room for your chat platform (Discord by default; set `PRINT_BUDDY__BOT__PLATFORM` for Telegram or Matrix). Allowed users are optional: with no list, everyone in the print channel can use the bot.
2. Pin the image by digest, not a tag: set `PRINT_BUDDY_IMAGE=ghcr.io/catduckgnaf/print-buddy@sha256:<digest>`. The digest will be in the publish run summary and that release's notes.
3. Set `PRINT_BUDDY_DATA` to a persistent directory owned by UID 1000. Spoolman data lives in `PRINT_BUDDY_DATA/spoolman` unless you set `PRINT_BUDDY_SPOOLMAN_DATA`.
4. Run `docker compose up -d`.

Already run your own Spoolman? Set `PRINT_BUDDY__SERVICES__SPOOLMAN_URL` to it and `PRINT_BUDDY_BUNDLED_SPOOLMAN=false` in `.env`. Nothing is migrated either way. Unraid users can start from `docker/unraid/print-buddy.xml`.

The image also includes:

| Item | Detail |
|---|---|
| OrcaSlicer | Stable and alpha. `PRINT_BUDDY_ORCA_CHANNEL=stable` (default) or `alpha` picks one at startup, no rebuild. Any other value stops the container. Used for Flashforge and Sovol |
| Bambu Studio | Default slicer for every Bambu Lab printer |
| OpenSCAD | For CAD splitting (`cad_split.py --execute`) |

See [Docker setup](docs/DOCKER.md) for health checks, upgrades and rollback.

### Manual install

1. **Choose a mode:** [Docker](#docker) above is the packaged route. For a manual setup, the [standalone bot](docs/STANDALONE.md) is the direct route without Hermes — on Discord, or on [Telegram](docs/TELEGRAM-BOT-SETUP.md) or [Matrix](docs/MATRIX-BOT-SETUP.md) instead — and the [Hermes installation](docs/INSTALL.md) is for existing Hermes users. Both require Python 3.11 or newer.
2. **Configure your printer and access:** follow the chosen guide, then use [configuration](docs/CONFIGURATION-YAML.md) to set your printer model, Discord channel and authorized users, service addresses and slicer command. Keep local settings and tokens out of Git.
3. **Check before enabling printing:** confirm the selected printer profile, bed dimensions, nozzle, filament and service permissions. Review the guide's checks before starting the bot or listener. The doctor can contact configured services; it is not an offline-only check.

Start with the installation guide, not a production print. Installation and service startup are deliberate actions, not part of reading these docs.

## What you can do

- **Prepare models:** take links or files through guided choices for colors, fit, supported layouts and slicing. Models that need adjustment can require operator choices; not every shape has a validated automatic placement or cut strategy.
- **Manage filament:** use Spoolman and supported IFS integrations to match loaded spools and keep identity and material information consistent.
- **Run approved jobs:** confirm bed clearance, work through multi-plate plans and reprint archived jobs using guarded controls.
- **Follow a print:** receive configured printer events and timelapses, and keep job records.
- **Camera watchdog — spaghetti detection:** while a print runs, Print Buddy checks the printer camera at layer 2, layer 5 and then periodically, and a vision model classifies each frame. Spaghetti, a detached part, an empty bed, a stalled print, an uncertain frame or a failed check posts the camera photo to Discord with **Pause** and **It's fine** buttons; tap Pause and the paused post offers Resume and Cancel. The watchdog itself never touches the printer — it only alerts, and every printer action is an operator tap. Tune how readily it alerts with `visual_watch.sensitivity`, 1 (quietest) to 5 (most alerts, default 3), or switch it off with `visual_watch.enabled`; both are settable in YAML and as Docker environment variables (`PRINT_BUDDY__VISUAL_WATCH__SENSITIVITY`, `PRINT_BUDDY__VISUAL_WATCH__ENABLED`). It needs a camera snapshot (derived from the Moonraker host when unset) and a vision endpoint (`services.vision_chat_url`; empty disables camera checks). See [camera stall sensitivity](docs/PROJECT-REFERENCE.md#camera-stall-sensitivity) for what each level changes and [Docker](docs/DOCKER.md#camera-watch-visual_watch) for the container setup.
- **Set up and troubleshoot in Discord:** `/print-buddy setup` walks a fresh install through a saved, resumable checklist (nothing is written without an explicit `apply`), and `/print-buddy debugging` runs read-only, redacted checks. See [guided setup and debugging](docs/GUIDED-SETUP-DEBUGGING.md).
- **Optional Web UI:** an off-by-default local status page and picker configuration page for the same YAML settings file. See the [Web UI guide](docs/WEBUI.md).

Printer-specific capabilities and detailed commands are in the [project reference](docs/PROJECT-REFERENCE.md). Optional vision and conversational features may use a model; the standalone command and slicing workflow does not require one.

## Safety and support boundaries

A fitting bounding box is not proof of a printable orientation. Offline tests are not a live hardware test. Check support needs, bed and brim clearance, profile compatibility and generated G-code before physical use. Keep confirmation and artifact guards enabled. Do not treat an alert or camera classification as a guarantee of safe unattended printing.

Only use models you are allowed to download and process. Never attach private models, credentials or personal printer logs to a public issue without reviewing them first.

## Find the right guide

| Task | Guide |
| --- | --- |
| Install and configure | [Documentation site](https://catduckgnaf.github.io/print-buddy-docs/) · [Documentation home (source)](docs/README.md) |
| Run Print Buddy for two or more printers | [More than one printer](docs/MULTI-INSTANCE.md) |
| Set up the bot on Telegram or Matrix | [Telegram bot setup](docs/TELEGRAM-BOT-SETUP.md) · [Matrix bot setup](docs/MATRIX-BOT-SETUP.md) |
| Understand commands, settings and integrations | [Detailed project reference](docs/PROJECT-REFERENCE.md) |
| Report a problem or contribute | [Contribution guide](CONTRIBUTING.md) · [Issues](https://github.com/catduckgnaf/print-buddy/issues) |
| Read shipped changes | [GitHub releases](https://github.com/catduckgnaf/print-buddy/releases) |
| Write or review release notes | [Release-note guide](docs/RELEASE-NOTES.md) · [Internal history](docs/INTERNAL_RELEASE_NOTES.md) |

Draft pull requests describe pending work, not installed or released capabilities.
