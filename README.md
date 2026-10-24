# Print Buddy

[![CI](https://github.com/catduckgnaf/print-buddy/actions/workflows/ci.yml/badge.svg)](https://github.com/catduckgnaf/print-buddy/actions/workflows/ci.yml)

**Prepare and manage 3D prints from Discord, with an explicit confirmation before starting a print.**

Share a MakerWorld or Printables link, or upload an STL or 3MF. Print Buddy guides you through model preparation, filament choices and slicing with OrcaSlicer. For configured printers, it can submit an approved job through Moonraker and report progress back to Discord.

[Get started](#get-started) · [Documentation](docs/README.md) · [Contribute](CONTRIBUTING.md) · [Releases](https://github.com/catduckgnaf/print-buddy/releases)

## Is it for your setup?

- **Printers:** built-in profiles for Flashforge AD5X with ZMod and Sovol SV06, plus a generic Klipper/Moonraker adapter. A generic adapter is not a tuned or physically verified profile for every printer. The Bambu Lab A1 and P1S are supported offline only: slicing, G-code checks and an untested Bambu package, no printer connection. Bambu Lab printers slice with Bambu Studio by default (set `printer.slicer: orca` to use OrcaSlicer); everything else uses OrcaSlicer. See [Bambu Lab printers](docs/BAMBU-LAB.md).
- **Computers:** Raspberry Pi 4 or 5 with 64-bit Raspberry Pi OS, or any 64-bit Debian or Ubuntu machine.
- **Discord:** run the standalone Python bot without Hermes or an LLM, or use the Hermes plugin. Use only one mode with a given bot token.
- **Slicing:** requires a compatible OrcaSlicer CLI and the correct printer, process and filament profiles. A Python install alone does not provide a slicer.
- **Offline delivery:** vendor profiles can offer Discord file delivery or an offline Bambu package after slicing. Delivery does not authorize printing. Bambu packaging is not verified in Bambu Studio or on hardware. See [printer profiles](docs/PRINTER-PROFILES.md).
- **Optional integrations:** Spoolman for filament records, camera checks, timelapses and Obsidian records. Requirements depend on the features you enable.

## Get started

### Quick install (Raspberry Pi or Debian/Ubuntu)

```bash
curl -fsSL https://raw.githubusercontent.com/catduckgnaf/print-buddy/main/scripts/install-light.sh | bash
```

To install a specific release instead of the latest code:

```bash
curl -fsSL https://raw.githubusercontent.com/catduckgnaf/print-buddy/main/scripts/install-light.sh | bash -s -- --ref 2.1.0
```

The setup wizard asks for your printer brand and model (or Other / generic), the connection, nozzle, filament, slicer, Spoolman, camera and timelapse, your Discord bot, and whether to run as a Hermes profile or a standalone bot. It installs the stock Flathub OrcaSlicer or Bambu Studio; it does not bundle Spoolman (it can run the official Spoolman installer if you ask). See [light install](docs/INSTALL-LIGHT.md) and [Discord bot setup](docs/DISCORD-BOT-SETUP.md).

### Docker

The 2.1.0 image is `ghcr.io/catduckgnaf/print-buddy` (amd64 only). It is built and checked offline by the publish workflow before it is pushed.

1. Pin the image by digest, not a tag: set `PRINT_BUDDY_IMAGE=ghcr.io/catduckgnaf/print-buddy@sha256:<digest>` in `.env`. The digest is in the publish run summary and the 2.1.0 release notes.
2. Copy `.env.example` to `.env` and fill in the Discord token, channel and allowed users. Set `PRINT_BUDDY_DATA` to a persistent directory owned by UID 1000.
3. Run `docker compose up -d`. Add `docker-compose.spoolman.yml` if you want Spoolman as a separate container.

What the image includes:

| Item | Detail |
|---|---|
| OrcaSlicer | Stable and alpha. `PRINT_BUDDY_ORCA_CHANNEL=stable` (default) or `alpha` picks one at startup, no rebuild. Any other value stops the container. Used for Flashforge and Sovol |
| Bambu Studio | Default slicer for every Bambu Lab printer (A1, P1S) |
| OpenSCAD | For CAD splitting (`cad_split.py --execute`) |
| Not included | Spoolman (separate container), KiCad (deferred) |

See [Docker setup](docs/DOCKER.md) for health checks, upgrades and rollback.

### Manual install

1. **Choose a mode:** the [light installer](docs/INSTALL-LIGHT.md) above is recommended. For a manual setup, the [standalone Discord bot](docs/STANDALONE.md) is the direct route without Hermes, and the [Hermes installation](docs/INSTALL.md) is for existing Hermes users. Both require Python 3.11 or newer. For Docker, see [Docker](#docker) below.
2. **Configure your printer and access:** follow the chosen guide, then use [configuration](docs/CONFIGURATION-YAML.md) to set your printer model, Discord channel and authorized users, service addresses and slicer command. Keep local settings and tokens out of Git.
3. **Check before enabling printing:** confirm the selected printer profile, bed dimensions, nozzle, filament and service permissions. Review the guide's checks before starting the bot or listener. The doctor can contact configured services; it is not an offline-only check.

Start with the installation guide, not a production print. Installation and service startup are deliberate actions, not part of reading these docs.

## What you can do

- **Prepare models:** take links or files through guided choices for colors, fit, supported layouts and slicing. Models that need adjustment can require operator choices; not every shape has a validated automatic placement or cut strategy.
- **Manage filament:** use Spoolman and supported IFS integrations to match loaded spools and keep identity and material information consistent.
- **Run approved jobs:** confirm bed clearance, work through multi-plate plans and reprint archived jobs using guarded controls.
- **Follow a print:** receive configured printer events, camera alerts and timelapses, and keep job records.

Printer-specific capabilities and detailed commands are in the [project reference](docs/PROJECT-REFERENCE.md). Optional vision and conversational features may use a model; the standalone command and slicing workflow does not require one.

## Safety and support boundaries

A fitting bounding box is not proof of a printable orientation. Offline tests are not a live hardware test. Check support needs, bed and brim clearance, profile compatibility and generated G-code before physical use. Keep confirmation and artifact guards enabled. Do not treat an alert or camera classification as a guarantee of safe unattended printing.

Only use models you are allowed to download and process. Never attach private models, credentials or personal printer logs to a public issue without reviewing them first.

## Find the right guide

| Task | Guide |
| --- | --- |
| Install and configure | [Documentation home](docs/README.md) |
| Understand commands, settings and integrations | [Detailed project reference](docs/PROJECT-REFERENCE.md) |
| Report a problem or contribute | [Contribution guide](CONTRIBUTING.md) · [Issues](https://github.com/catduckgnaf/print-buddy/issues) |
| Read shipped changes | [GitHub releases](https://github.com/catduckgnaf/print-buddy/releases) |
| Write or review release notes | [Release-note guide](docs/RELEASE-NOTES.md) · [Internal history](docs/INTERNAL_RELEASE_NOTES.md) |

Draft pull requests describe pending work, not installed or released capabilities.
