# Docker

Run Print Buddy from a published image with Docker Compose or on Unraid. No local build, no Hermes.

The image contains Print Buddy, a pinned OrcaSlicer CLI and their runtime. Everything else is an external endpoint you point it at:

| Service | In this stack | Configure with |
|---|---|---|
| Klipper + Moonraker (+ Fluidd or Mainsail), ZMod | No, runs on the printer | `PRINT_BUDDY__SERVICES__MOONRAKER_URL` |
| OctoPrint (Marlin printers) | No | `PRINT_BUDDY__SERVICES__OCTOPRINT_URL`, `OCTOPRINT_API_KEY` |
| Spoolman | External by default; optional bundled service | `PRINT_BUDDY__SERVICES__SPOOLMAN_URL`, or `docker-compose.spoolman.yml` |
| OrcaSlicer CLI | Yes, 2.5.0-alpha | [OrcaSlicer channel](#orcaslicer-channel) |
| Hermes | No | |

Every setting: [SETTINGS.md](SETTINGS.md).

> **Current limitation, standalone mode (#73).** The container runs the Moonraker event listener: it follows the printer, runs the camera watchdog and spool sync, and passes its health check without Hermes. Discord intake (links, uploads, slash commands) and the listener's plain text posts still go through Hermes (`hermes send`), which this image does not contain, so they are not delivered yet; posts with buttons use `DISCORD_BOT_TOKEN` directly. The standalone Discord bot from #73 replaces the runtime with no change to volumes, settings or Compose files. The runtime is named once, in the image `CMD` (see the `Dockerfile`). Until then, a Hermes install ([INSTALL.md](INSTALL.md)) remains the full-featured path. OctoPrint printers have no listener: the listener needs Moonraker.

## Images

`ghcr.io/catduckgnaf/print-buddy`, for `linux/amd64` and `linux/arm64` (64-bit Raspberry Pi OS, Apple silicon, ARM servers). 32-bit ARM is not supported: OrcaSlicer publishes no build for it.

| Tag | Meaning |
|---|---|
| `2.1.0` (exact version) | Immutable: CI refuses to republish an existing version. Use this in production. |
| `2.1` | Latest patch of that minor version |
| `stable` | Moving release channel: the newest release |
| `2.2.0-rc.1`, `next` | Pre-releases and the moving pre-release channel |

Images are only published from a pushed version tag, after the same commit's image passed the tests on both architectures. Each image carries a build provenance attestation (SLSA, `mode=max`) and an SPDX SBOM. Inspect them with:

```bash
docker buildx imagetools inspect ghcr.io/catduckgnaf/print-buddy:2.1.0 --format '{{ json .Provenance }}'
docker buildx imagetools inspect ghcr.io/catduckgnaf/print-buddy:2.1.0 --format '{{ json .SBOM }}'
```

The OCI labels name the source commit, version and bundled OrcaSlicer (`io.print-buddy.orcaslicer.version`).

## Requirements

* Docker Engine 24+ with the Compose plugin v2.24+ (`docker compose version`).
* 2 CPU cores and 4 GB RAM for Print Buddy: the Compose default limits (`PRINT_BUDDY_CPUS`, `PRINT_BUDDY_MEMORY`). Idle use is small; slicing is the peak and grows with the model and the number of merged plates, so raise the memory limit if slices of large multi-plate models are killed. Bundled Spoolman is limited to 512 MB.
* About 2.5 GB of disk for the image (about 600 MB download), plus the data folders: the archive grows by the G-code of each job.
* Network access from the Docker host to the printer (Moonraker port 7125, or OctoPrint) and to Spoolman.

## Install

On a clean host, with no checkout and no build:

```bash
mkdir print-buddy && cd print-buddy
base=https://raw.githubusercontent.com/catduckgnaf/print-buddy/main
curl -fsSLO $base/docker-compose.yml
curl -fsSLO $base/docker-compose.spoolman.yml
curl -fsSL -o .env $base/.env.example
chmod 600 .env
"${EDITOR:-nano}" .env            # printer, Spoolman, Discord and secrets; see Setup
mkdir -p data/hermes data/archive data/records data/cache data/spoolman
sudo chown -R 1000:1000 data       # or your PUID:PGID from .env
docker compose pull
docker compose up -d
docker compose ps                  # print-buddy should turn "healthy" within about a minute
```

Using a release instead of `main` for the Compose files works the same: replace `main` with the version tag.

## Setup

Edit `.env`. The minimum for a Klipper printer:

```bash
PRINT_BUDDY_TAG=2.1.0                                  # an exact release
PRINT_BUDDY__PRINTER__MODEL=sovol.sv06                 # or flashforge.ad5x, klipper.generic, octoprint.marlin
PRINT_BUDDY__SERVICES__MOONRAKER_URL=http://printer.example:7125
PRINT_BUDDY__SERVICES__SPOOLMAN_URL=http://spoolman.example:7912
PRINT_BUDDY__DISCORD__CHAT_ID=<channel id>
DISCORD_BOT_TOKEN=<bot token>
```

For OctoPrint, set `PRINT_BUDDY__PRINTER__MODEL=octoprint.marlin`, `PRINT_BUDDY__SERVICES__OCTOPRINT_URL` and `OCTOPRINT_API_KEY` ([OCTOPRINT-MARLIN.md](OCTOPRINT-MARLIN.md)).

Scalar settings come from `PRINT_BUDDY__SECTION__KEY` variables. Lists and tables (`orca.command`, `printer.bed_mm`, `material_temps`, `cold_pull`) need a YAML file: create `config/local.yaml` next to `docker-compose.yml`, uncomment its volume line in `docker-compose.yml`, and set `PRINT_BUDDY_CONFIG=/app/config/local.yaml`. That file replaces the image's `config/docker.yaml`, so copy its keys in first. Legacy TOML keeps working: mount it at `/app/config/docker.toml` and set `PRINT_BUDDY_CONFIG=/app/config/docker.toml`.

Restart after any change: `docker compose up -d` (it recreates the container when `.env` changed). A wrong value stops startup and the log names the setting.

The printer hardware record (`printer_hardware.json`) that slicing reads lives in `data/hermes/state/`. Copy it from a working install, then check everything with:

```bash
docker compose exec print-buddy python3 -m print_buddy.doctor
```

### Secrets

Secrets are environment variables only, never YAML: `DISCORD_BOT_TOKEN`, `OCTOPRINT_API_KEY`, `MOONRAKER_API_KEY`, `CLIPROXY_API_KEY`, `OPENVIKING_API_KEY` ([SETTINGS.md](SETTINGS.md#secrets)). Keep them in `.env` with mode 600, never commit or paste it, and leave the shipped `.env.example` free of real values. `docker compose config` prints secrets: do not share its output. For the timelapse archive, mount the SSH key read-only (for example `./secrets/timelapse_key:/run/secrets/timelapse_key:ro`) and set `PRINT_BUDDY__TIMELAPSE__SSH_KEY` to the container path.

## Networking

Print Buddy only makes outbound connections and publishes no port. It must reach:

* **Moonraker** on the printer, normally `http://<printer>:7125` (HTTP and the `/websocket` endpoint). Fluidd and Mainsail are the printer's own web UIs; Print Buddy does not use them, and Klipper is reached only through Moonraker. On ZMod, Moonraker listens on 7125 as well. If Moonraker has `[authorization]` trusted clients, add the Docker host's address (or subnet) to `trusted_clients`, or set `MOONRAKER_API_KEY`.
* **Flashforge stock API** for IFS presence: the printer host on `services.stock_api_port` (8898).
* **Camera**: `services.camera_snapshot_url`, derived as `http://<printer>/webcam/?action=snapshot` when empty.
* **Spoolman**, **OctoPrint**, the vision endpoint and Discord, as configured.

Use host names or addresses that resolve from inside a container. A printer on your LAN normally works over the default bridge network. A service on the Docker host itself is `http://host.docker.internal:<port>` (the Compose file maps it). If the printer is only reachable from the host (VPN, unusual routing), uncomment `network_mode: host` in `docker-compose.yml`. A firewall on the printer or host must allow the Docker host to open these connections.

## Spoolman

**External (default).** Set `PRINT_BUDDY__SERVICES__SPOOLMAN_URL` to your Spoolman server. Nothing else runs.

**Bundled.** Uncomment `COMPOSE_FILE=docker-compose.yml:docker-compose.spoolman.yml` in `.env` and run `docker compose up -d`. This adds Spoolman 0.27.0 (`SPOOLMAN_TAG`) with its SQLite database in `data/spoolman`, publishes its UI on host port 7912 (`SPOOLMAN_PORT`), sets Print Buddy's Spoolman URL to `http://spoolman:8000` (overriding `.env`) and starts Print Buddy only once Spoolman is healthy. `data/spoolman` must be owned by `PUID:PGID`.

### Switching without losing data

Print Buddy stores Spoolman spool IDs (for example the slot bindings in `data/hermes/state/printer_hardware.json`), so move the Spoolman database itself. Re-entering spools or a CSV import creates new IDs. Use the same or a newer Spoolman version on the receiving side: Spoolman upgrades a database on start but cannot downgrade one. The bundled service uses SQLite. If your external Spoolman uses PostgreSQL or MySQL, keep it external.

External to bundled:

1. Wait until no print is running, then `docker compose stop print-buddy`.
2. On the external Spoolman, run a backup (`curl -X POST http://spoolman.example:7912/api/v1/backup` returns the path), then stop it so no change is lost.
3. Copy its `spoolman.db` (from its data directory, or the backup just made) to `data/spoolman/spoolman.db` and `chown PUID:PGID` it.
4. Uncomment the `COMPOSE_FILE` line in `.env`, then `docker compose up -d`.
5. Open the bundled Spoolman, check spools and IDs, run `docker compose exec print-buddy python3 -m print_buddy.doctor`. Keep the old server's data until you are satisfied.

Bundled to external:

1. `docker compose stop print-buddy`, then `curl -X POST http://localhost:7912/api/v1/backup`, then `docker compose stop spoolman`.
2. Copy `data/spoolman/spoolman.db` into the external Spoolman's data directory and start it.
3. Comment out `COMPOSE_FILE` again, set `PRINT_BUDDY__SERVICES__SPOOLMAN_URL` to the external server, and run `docker compose up -d --remove-orphans`.
4. Keep `data/spoolman` as a backup until the external server is verified.

## Volumes and backups

| Host (`PRINT_BUDDY_DATA`, default `./data`) | Container | Contents | Back up |
|---|---|---|---|
| `hermes` | `/data/hermes` | `state/` (job and spool state, printer hardware record, health heartbeat), `logs/` | Yes |
| `archive` | `/data/archive` | Sliced jobs and G-code | Yes |
| `records` | `/data/records` | Obsidian print records | Yes |
| `cache` | `/data/cache` | Previews, slicer work files, container `HOME` and `TMPDIR` | No, regenerable |
| `spoolman` (bundled only) | Spoolman data | `spoolman.db`, Spoolman's own `backups/` | Yes |

The image filesystem is read-only, so these are the only places anything is written. All of them must be owned by `PUID:PGID` (default 1000:1000); the container refuses to start and says which folder is wrong otherwise.

Back up with the stack stopped, or at least idle, so state files and the Spoolman database are consistent:

```bash
docker compose stop
tar -czf print-buddy-backup-$(date +%F).tar.gz data .env
docker compose start
```

Restore by extracting the archive in place, fixing ownership, and starting the same (or a newer) image tag. `.env` is in the archive because it holds the configuration, which also makes the archive secret.

## Health checks and logs

The container is healthy when its settings load, the bundled OrcaSlicer is present, and the runtime's event loop wrote a heartbeat (`data/hermes/state/heartbeat.json`) within the last 90 seconds. A printer that is switched off does not make it unhealthy, because restarting Print Buddy cannot fix that; the heartbeat records the printer connection instead:

```bash
docker compose ps
docker compose exec print-buddy python3 -m print_buddy.healthcheck --json
```

The listener logs to `data/hermes/logs/moonraker_event_listener.log`; `docker compose logs print-buddy` shows startup errors. Docker restarts the container if it exits (`restart: unless-stopped`). Docker itself does not restart an unhealthy container; Unraid and most monitoring tools show the health state.

## Upgrade

Releases keep your data folders, settings and the state formats compatible within a major version; read the release notes before a major-version upgrade.

```bash
docker compose exec print-buddy python3 -m print_buddy.healthcheck   # confirm the current one is healthy
docker compose stop && tar -czf print-buddy-backup-$(date +%F).tar.gz data .env && docker compose start
# set PRINT_BUDDY_TAG=<new version> in .env, then:
docker compose pull
docker compose up -d
docker compose ps                                                     # wait for "healthy"
docker compose exec print-buddy python3 -m print_buddy.doctor
```

Do not upgrade while a print is running: the listener restarts. With `PRINT_BUDDY_TAG=stable`, `docker compose pull && docker compose up -d` moves to the newest release; pinning a version keeps upgrades deliberate and makes rollback exact.

### From the earlier build-it-yourself Compose file

The data folders keep their paths, so nothing moves. Three things changed:

1. The container no longer runs as root. Give the existing data to the new user: `sudo chown -R 1000:1000 data` (or your `PUID:PGID`).
2. Spoolman is no longer bundled by default and the image's default Spoolman URL is now empty. To keep the Spoolman you had, enable `COMPOSE_FILE=docker-compose.yml:docker-compose.spoolman.yml` in `.env`; it uses the same `data/spoolman` folder, so your spools stay. Otherwise set `PRINT_BUDDY__SERVICES__SPOOLMAN_URL`.
3. The stack pulls `ghcr.io/catduckgnaf/print-buddy` instead of building `print-buddy:local`. Remove the old containers once with `docker compose down --remove-orphans` before the first `docker compose up -d`.

## Rollback

```bash
# set PRINT_BUDDY_TAG back to the previous version in .env, then:
docker compose pull
docker compose up -d
```

The data folders are reused unchanged. If the newer release migrated state that the older one cannot read, restore the backup taken before the upgrade (stop the stack, extract it, start). Spoolman follows the same rule: roll back `SPOOLMAN_TAG` only together with a database backup from that version.

## OrcaSlicer channel

The image bundles one OrcaSlicer build, pinned with its SHA-256 in `docker/orcaslicer.lock`:

* `alpha` (default): OrcaSlicer 2.5.0-alpha. CI runs the slicer tests and the full Discord flow corpus inside the image with this build on every pull request.
* `stable`: OrcaSlicer 2.5.0, once released. It is empty in the lock until then and a build with it fails rather than guessing.

The setting `orca.command` stays `/opt/orcaslicer/AppRun` on either channel, so moving between them needs no configuration change: pick the image release that bundles the build you want (its `io.print-buddy.orcaslicer.version` label says which).

Switching the release to stable 2.5.0 (maintainers):

1. From the [v2.5.0 release page](https://github.com/OrcaSlicer/OrcaSlicer/releases), copy the `OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.5.0.AppImage` and `..._aarch64_V2.5.0.AppImage` names and their SHA-256 digests into the `ORCA_STABLE_*` entries of `docker/orcaslicer.lock`.
2. Build and test it: `docker compose -f docker-compose.yml -f docker-compose.build.yml build --build-arg ORCA_CHANNEL=stable`, or push a branch and let the Docker workflow test both channels that are pinned.
3. Change `ARG ORCA_CHANNEL=alpha` to `stable` in both stages of the `Dockerfile`, `ORCA_DEFAULT_CHANNEL` in the lock, and the `ORCA_CHANNEL` default in `docker-compose.build.yml`. `tests/test_docker_release.py` checks they agree.
4. Release as usual. Users roll back to the alpha build by pinning the previous image version.

To build a different channel locally: `ORCA_CHANNEL=stable docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`. Offline or cached builds can supply the AppImages with `docker buildx build --build-context orca-cache=<folder> .`; the digests are still checked.

## Build from source

```bash
git clone https://github.com/catduckgnaf/print-buddy && cd print-buddy
cp .env.example .env    # and edit
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Add `-f docker-compose.spoolman.yml` for the bundled Spoolman. Builds work on either architecture; the OrcaSlicer AppImage is unpacked, never run, during the build.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Container exits: `/data/... is not writable by uid ...` | The host folder's owner is not `PUID:PGID`. `sudo chown -R 1000:1000 data` (or your IDs). |
| Exits: `services.moonraker_url is not configured` | Set `PRINT_BUDDY__SERVICES__MOONRAKER_URL`. The listener needs Moonraker; OctoPrint-only setups wait for #73. |
| Exits with `SettingsError: ... unknown setting` or a type error | A misspelt `PRINT_BUDDY__` name or bad value in `.env`; the message names it. Compare with [SETTINGS.md](SETTINGS.md). |
| `unhealthy`, `no heartbeat ... yet` or `heartbeat is ...s old` | The runtime is not running or is stuck. Check `docker compose logs print-buddy` and `data/hermes/logs/`. |
| Healthy, but `"moonraker_connected": false` in `healthcheck --json` | The printer is off or unreachable from the container. `docker compose exec print-buddy curl -fsS $URL/printer/info`; see [Networking](#networking). |
| `doctor` fails `spoolman` | Wrong URL, or the bundled Spoolman is not healthy: `docker compose ps spoolman`, `docker compose logs spoolman`. |
| Bundled Spoolman restarts with permission errors | `data/spoolman` is not owned by `PUID:PGID`. |
| `doctor` fails `hardware record` | Copy `printer_hardware.json` into `data/hermes/state/`. |
| Slicing is killed or very slow | Raise `PRINT_BUDDY_MEMORY` / `PRINT_BUDDY_CPUS`; check `docker stats`. |
| No Discord posts | Expected until standalone mode (#73) lands, except button posts, which need `DISCORD_BOT_TOKEN` and `PRINT_BUDDY__DISCORD__CHAT_ID`. |
| `exec format error` | The host is 32-bit ARM, which is not supported. |

## Unraid

The template is [`docker/unraid/print-buddy.xml`](../docker/unraid/print-buddy.xml). It applies the same hardening as Compose (read-only filesystem, no capabilities, `no-new-privileges`, memory and CPU limits) and runs as `nobody:users` (99:100), which owns Unraid's appdata.

1. In a terminal on the Unraid server, download the template into the user templates folder:
   `curl -fsSL -o /boot/config/plugins/dockerMan/templates-user/my-print-buddy.xml https://raw.githubusercontent.com/catduckgnaf/print-buddy/main/docker/unraid/print-buddy.xml`
2. Create the appdata folders: `mkdir -p /mnt/user/appdata/print-buddy/{hermes,archive,records,cache} && chown -R 99:100 /mnt/user/appdata/print-buddy`.
3. Docker tab, **Add Container**, choose **print-buddy** under user templates.
4. Set the printer model, Moonraker (or OctoPrint) URL, Spoolman URL, Discord values and secrets. Replace `stable` in **Repository** with an exact version to control upgrades. Further settings: **Add another Path, Port, Variable**, named `PRINT_BUDDY__SECTION__KEY` ([SETTINGS.md](SETTINGS.md)).
5. **Apply**. The Docker tab shows the health state after about a minute.

Spoolman on Unraid: use your existing server, or install the Spoolman container from Community Applications and set the Spoolman URL to `http://<Unraid server>:7912`. To move between them, follow [Switching without losing data](#switching-without-losing-data) with `/mnt/user/appdata/spoolman` as Spoolman's data folder.

Upgrade: set the new version in **Repository** (or, on `stable`, **Check for Updates**) and **Apply**. Roll back by setting the previous version. Back up `/mnt/user/appdata/print-buddy` first, for example with the Appdata Backup plugin.
