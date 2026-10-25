# Docker

## Combined runtime for 2.1.2

The 2.1.2 candidate replaces separate bot, listener and Spoolman services with ONE runtime container. Published 2.1.1 remains unchanged. Pin the immutable digest from a successful publication run; candidate source is not a published image.

Tini owns orphan reaping and process-group signals. The supervisor waits for the bundled API before starting the Moonraker listener and Discord bot. Any required child exit ends the container nonzero, including an unexpected clean exit. SIGTERM stops children with a bounded grace period. Docker restart reacts to process exit, not healthcheck failures alone.

An empty `DISCORD_BOT_TOKEN` disables only the Discord consumer for staging. Never run duplicate consumers/listeners against the same state. HEALTHCHECK verifies listener heartbeat, enabled bot readiness and Spoolman `/api/v1/health`. An offline printer does not make a reconnecting listener unhealthy. Dummy credentials do not prove Discord login.

## Included Spoolman

Spoolman 0.27.0 is built from exact upstream revision `bed3f14ee77a3a571d31b14215d54b0b88a7519c` with its committed uv.lock, isolated from Print Buddy dependencies. No third-party source is patched. No Node, npm or web UI assets are built or copied. A local static placeholder satisfies upstream's static-directory check. Print Buddy spool commands and slicing lookups are the interface; `/api/v1` remains available.

Default bind is `127.0.0.1:8000` inside the container. Print Buddy defaults to `http://127.0.0.1:8000`. Compose publishes no port. Optional LAN API access requires widening `SPOOLMAN_HOST` to all interfaces plus an approved port mapping in a local override, for example host 7912 to container 8000. Never expose this unauthenticated API publicly. Neither Compose nor the DockerMan template ships this mapping. Network changes require review.

Persist `/data/spoolman` separately, including database, config, logs and backups. Upstream Alembic migrations remain intact for existing 0.26.1/0.27.0 databases. Runtime migration acceptance is required before deployment; retaining migration files alone is not evidence of a successful migration. Preserve source data and reconcile inventory at final cutover. No automatic downgrade is provided.

For an existing external instance set `PRINT_BUDDY__SERVICES__SPOOLMAN_URL=http://spoolman.example:8000`. Its data is not migrated or reset; the local database remains separate. Optionally set `PRINT_BUDDY_BUNDLED_SPOOLMAN=false` to skip the local API, requiring a nonlocal URL. Healthcheck then checks the external API. Changing a URL never moves or deletes a database.

## First-run configuration

1. Copy `.env.example` to a private `.env`. Set `PRINT_BUDDY_IMAGE` to a tested digest. Configure Moonraker with `PRINT_BUDDY__SERVICES__MOONRAKER_URL`; do not use a real printer for offline validation.
2. Set `PRINT_BUDDY_DATA` to a persistent directory with `hermes`, `archive`, `records`, `cache` and `spoolman` subdirectories writable by UID/GID 1000:1000; `PRINT_BUDDY_SPOOLMAN_DATA` can point the Spoolman data elsewhere, such as an existing Spoolman data folder. They map separately to `/data/hermes`, `/data/archive`, `/data/records`, `/data/cache`, `/data/spoolman`.
3. Leave the token empty for staging. At separately authorized live cutover configure token, chat ID and allowed user IDs. Stop previous consumers before enabling the replacement. Live startup never authorizes heating, movement or printing.
4. Use `PRINT_BUDDY__SECTION__KEY` scalar overrides from [SETTINGS.md](SETTINGS.md), or mount YAML/TOML and set `PRINT_BUDDY_CONFIG`. Never bake secrets into images or mount host source over `/app`.
5. One Compose service, `combined`, uses 2 CPUs, 2 GiB RAM, 256 PIDs and 256 MiB shared memory by default. Real slicing may require more RAM. Capabilities are dropped and logs rotate.

## Unraid DockerMan

Use `docker/unraid/print-buddy.xml`, replacing the prior three templates. One entry runs all required processes; leave PostArgs empty. The template specifies UID/GID 1000:1000 and five persistent paths under `/mnt/user/appdata/print-buddy`. Set Repository to the tested immutable digest before deployment. It publishes no port; add an approved API mapping only as described under Included Spoolman. Image HEALTHCHECK covers the combined runtime.

This source template does not prove a Community Applications listing or an exercised Unraid installation. The host owner verifies deployment and final network mapping.

## Build dimensions and slicers

All OS stages use Debian 13 slim. `APP_CHANNEL=stable|development` labels provenance, not a source switch. `WITH_ORCA=true` includes Orca; default false omits it. `ORCA_SOURCE=prebuilt` includes stable 2.4.2 only; `source` builds pinned stable and alpha independently. `PRINT_BUDDY_ORCA_CHANNEL=stable|alpha` selects wrappers; absent executables and invalid selections fail closed. `/usr/local/bin/orca-slicer` remains the stable path. Existing entrypoint preserves Xvfb for headless slicing.

The official prebuilt archive is downloaded and extracted only inside approved hosted image builds, never installed on a Hermes host. Its SHA256 is pinned by `docker/orca-prebuilt.sh`. Source caches separate architecture, channel, revision and profile. `ORCA_BUILD_JOBS=auto` bounds CPU/memory usage; explicit values accept 1 through 64. See [SETTINGS.md](SETTINGS.md#build-arguments).

`WITH_BAMBU=false` is the publication default; enabling pinned source-built Bambu Studio needs its own runtime acceptance. OpenSCAD (`openscad`) is included for CAD splitting.

## Validation and publication

The existing manual `.github/workflows/docker-publish.yml` builds once, checks real offline headless slicing and runtime acceptance, and publishes only with `publish=true` after acceptance. Candidate inputs are `version=2.1.2`, `with_orca=true`, `orca_source=prebuilt`, `with_bambu=false`, `publish=false`. Preserve 2.1.1; never overwrite existing tags.

Hosted ubuntu-24.04 amd64 jobs have a 350 minute timeout. Buildx uses the Docker driver, not a persistent builder container. Runtime fixtures must remain isolated, use dummy credentials and clean up owned containers. Evidence is retained 30 days. No live Discord, printer, Home Assistant or household Spoolman endpoints are permitted. Native tests prove lifecycle logic, not image startup, migration or slicing. Report actual workflow evidence and immutable identities separately.

Upgrade: stop prior consumers, preserve source state and immutable digest, reconcile at final cutover and recreate with the same five paths. Never use `compose down -v`. Rollback requires a compatible schema and matching old image; no automatic database downgrade is supplied.

## Attribution

Standalone foundations originated in zaheria985/print-buddy commit fba5727184dd8f0070e59c8f1fc088751142a003 and merged through #132. Docker contribution #139 commit 3bb0984250c20eb336d11ba1da06633950b45182 (MIT) informed context filtering and listener heartbeat. Original notices remain. Spoolman is MIT; slicers retain upstream licenses. [DOCKER-117-PROGRESS.md](DOCKER-117-PROGRESS.md) contains historical evidence, not acceptance of this candidate.
