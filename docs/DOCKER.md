# Docker

No image has been published yet. Docker was deferred from 2.1.0; the first image is planned for 2.1.1 at `ghcr.io/catduckgnaf/print-buddy` (amd64), tracked in [#117](https://github.com/catduckgnaf/print-buddy/issues/117). When it is published, pin it by digest (`@sha256:<digest>` from the publish run summary), not by tag. The quick start is in the [README](../README.md#docker).

## Base image

Every stage (Orca build, Bambu Studio build, runtime) uses `debian:13-slim` (Debian 13 "trixie", Python 3.13). It has no stock UID 1000
user, so the runtime user `buddy` takes UID 1000 directly. Not yet built on Debian: the first
`docker-image-validation` run is the acceptance check.

## First GHCR publication

`.github/workflows/docker-publish.yml` is the maintainer-dispatched workflow for publishing an amd64 image to `ghcr.io/catduckgnaf/print-buddy`. It builds the selected variant once, runs the offline acceptance harness, and only after acceptance pushes the requested version and `latest` tags. The first package is planned for 2.1.1. The `publish` input defaults to false: dispatch a candidate on the intended branch with `version=2.1.1`, `with_orca=true`, `orca_source=prebuilt`, `with_bambu=false`, and `publish=false` to build and validate without registry login or pushes. Each bundled Orca channel must resolve its libraries, run `--help`, slice a generated cube headlessly with packaged templates, and pass the G-code guard before full offline runtime acceptance. Logs and image identity are retained for 30 days. A failed or absent selected slicer fails the smoke check. Only an explicit `publish=true` dispatch can push tags after these checks; candidate success alone publishes nothing. For deployments, prefer the exact tested immutable `ghcr.io/catduckgnaf/print-buddy@sha256:<digest>` recorded in the workflow run summary over a mutable tag. This workflow does not build ARM64 images.

## Build dimensions

The same Dockerfile supports two application channels, each running either the
standalone Discord bot or Moonraker listener. There is no combined supervisor.

| Build argument | Values | Meaning |
| --- | --- | --- |
| `APP_CHANNEL` | `stable`, `development` (default) | Application provenance label, not a Git checkout |
| `WITH_ORCA` | `false` (default), `true` | Include Orca using the selected distribution, or omit it |
| `ORCA_SOURCE` | `prebuilt` (default), `source` | Official stable binary, or compile both stable and alpha |
| `ORCA_BUILD_JOBS` | `auto` (default), `1-64` | Bounded compile parallelism; see OrcaSlicer source build |
| `WITH_BAMBU` | `false` (default), `true` | Include a source-built Bambu Studio, the default slicer for Bambu Lab printers |

All build arguments, with defaults: [SETTINGS.md](SETTINGS.md#build-arguments).

Build from the intended source checkout. Setting APP_CHANNEL does not switch the
application source. The proposed branch policy is main for stable candidates and
development for development candidates; this PR does not create branches or
publish tags. Development validation precedes promotion of the exact tested
source revision and image digest to stable. Rollback selects the previous tested
digest and preserves data. Neither branch labels nor green Python CI prove an
image works. Do not promote an untested source rebuild as an identical artifact.

Orca stable v2.4.2 is pinned to 8500fcdccaa10b5099ac20d252af3a7c560046f1;
alpha v2.5.0-alpha is pinned to 3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2.
The default `ORCA_SOURCE=prebuilt` downloads the official
`OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage` from the v2.4.2 GitHub release
inside the Docker build stage only. SHA256 is pinned to
`d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd`;
a mismatch stops the build before extraction. `--appimage-extract` needs no FUSE.
The entire extracted tree (AppRun, resources, private libraries and upstream environment
helper) is installed in `/opt/orca-stable`; no AppImage is installed in the runtime.
Debian supplies WebKitGTK 4.1, GTK3, OpenGL/GLU and the remaining system runtime libraries.
This prebuilt is amd64 only and ships stable only. Alpha requires `ORCA_SOURCE=source`;
requesting alpha on a prebuilt image fails closed when its executable is absent.
Do not download or run the AppImage on a Hermes host; image builds run in GitHub Actions.
`/orca-stable-build-info` records distribution, version, source revision and asset checksum.
The runtime selector `PRINT_BUDDY_ORCA_CHANNEL` defaults to `stable` and accepts `alpha`; invalid values stop container startup.
A no-Orca image can handle non-slicing commands; slicing requires the absent
/usr/local/bin/orca-slicer and must fail without an approved slice artifact. No remote
slicing fallback is provided. Exact user-facing failure behavior still needs
image verification. Alpha and ARM64 source builds are unverified; no multiarch
publication is claimed.

## Bambu Studio source build

Bambu stays separate from the default prebuilt candidate: the publisher defaults
`with_bambu=false`. No pinned prebuilt Bambu distribution is implemented here.
Enabling it still compiles from source and may take substantially longer.

With `WITH_BAMBU=true` the `bambu-build` stage compiles Bambu Studio 2.8.2 (public release 61) (pinned to
`926a7192574bcb9b3a732e1ec59a46d79cb45466`) the same way as Orca: its own CMake dependency recipe,
an FHS install to `/usr/bin/bambu-studio`, no AppImage, no patches, and a cache mount keyed by
architecture, revision and `BAMBU_BUILD_PROFILE`. It shares `ORCA_BUILD_JOBS` for parallelism.
Bambu Studio is the default slicer for every Bambu Lab printer (`printer.slicer: orca` opts out)
and Orca's one-shot fallback for other vendors. Without it, Bambu Lab slicing fails closed. The
image records `/bambu-source-revision` and `/bambu-build-info`. This build is unverified: no
image with it has been built yet, and ARM64 is untested. Bambu Studio is AGPL-3.0, like Orca.

## OrcaSlicer source build

With `WITH_ORCA=true ORCA_SOURCE=source` both pinned OrcaSlicer channels are built from source into separate prefixes; `WITH_ORCA=false` omits both. At runtime, `PRINT_BUDDY_ORCA_CHANNEL=stable` (the default) or `alpha` selects the executable. Any other value exits with a clear error. Both channel builds use Orca's own CMake dependency recipe. Orca source is never patched: each build refuses a checkout whose HEAD is not the pinned commit or whose tracked files differ from it.

Parallelism: `ORCA_BUILD_JOBS=auto` (default) runs one compile job per
`ORCA_BUILD_MEM_PER_JOB_MIB` (default 2560 MiB) of memory, capped at the usable CPUs minus one and
never below 1. Usable CPUs honour a cgroup v2 `cpu.max` quota, and memory honours a cgroup
`memory.max` limit before falling back to `MemAvailable`. For example, 4 CPUs with 6 GiB gives 2 jobs.
Override it with `--build-arg ORCA_BUILD_JOBS=N` (1-64); anything else stops the build before it
compiles. The same value is exported as `CMAKE_BUILD_PARALLEL_LEVEL`, so every dependency's own
build uses it while the dependency graph builds one dependency at a time, as Orca recommends. The
application then builds with `--parallel N`. Orca's recipe hard-codes its own parallelism for three
small C dependencies (GMP and MPFR use `make -j`, OpenSSL `make -j$(nproc)`). They are not patched,
and because only one dependency builds at a time, they run alone. A 4-CPU build's first dependency
stage therefore may briefly use all four CPUs. Earlier builds used `--parallel 1` only at the top
level, which still let every dependency use all host CPUs.

Cache: with BuildKit (`docker buildx build`, the default builder of current Docker), each channel has
an independent cache mount keyed by channel, architecture, its pinned revision and `ORCA_BUILD_PROFILE`.
The mount holds the pinned checkout, downloaded dependency sources, finished dependencies with their
completion stamps, Ninja objects and a ccache store (`ORCA_CCACHE_MAXSIZE`, default 5G). A fingerprint
of the OS release, GCC and CMake versions, compiler wrappers and option profile is kept with it; any
change empties the build trees and keeps the downloads and ccache, which checks every object itself.
Rename `ORCA_BUILD_PROFILE` when the CMake options in the Dockerfile change.

What survives an interrupted build: the cache mount does, whether the `RUN` fails or the build is
cancelled. A re-run reuses the checkout, skips finished dependencies and recompiles only unfinished
objects, mostly from ccache. The image layer itself is only committed when the whole step succeeds, so
an interrupted build on a builder that ignores or does not keep this cache mount, or with
`--no-cache`, starts over (the behaviour above was measured with Docker 29 BuildKit). After a hard kill (SIGKILL, out-of-memory) a truncated object can
make a later link fail. Clear the build trees by changing `ORCA_BUILD_PROFILE` for one build, or
remove the BuildKit cache. ccache keeps the rebuild short either way. Hosted runners start with an
empty cache.

Example build commands, to run only after the relevant container approval:

```sh
docker build --build-arg APP_CHANNEL=development --build-arg WITH_ORCA=false -t print-buddy:development-no-orca .
docker build --build-arg APP_CHANNEL=stable --build-arg WITH_ORCA=true --build-arg ORCA_SOURCE=source -t print-buddy:stable-orca .
docker run -e PRINT_BUDDY_ORCA_CHANNEL=alpha print-buddy:stable-orca
```

OpenSCAD (`openscad`) is included in the runtime image for `cad_split.py --execute`. KiCad is not bundled; it remains deferred per [KICAD-EVALUATION.md](KICAD-EVALUATION.md). Spoolman runs as its own container, included in the default Compose stack (see [Included Spoolman](#included-spoolman)).

## First-run configuration

1. Copy .env.example to .env outside any published artifact. Set the Discord token,
   chat ID, allowed numeric user IDs and required service URLs. Bot mode is
   standalone. LLM configuration remains optional. Never bake secrets into images.
2. Set PRINT_BUDDY_IMAGE in .env to an approved local tag or immutable tested image
   digest. There is intentionally no invented published image default.
3. Set PRINT_BUDDY_DATA to an absolute persistent directory. Create its hermes,
   archive, records, cache and spoolman subdirectories writable by container
   UID/GID 1000 (the spoolman subdirectory holds the included Spoolman's data).
   Do not run as root to hide ownership errors. First-run state is created there.
4. Use PRINT_BUDDY__SECTION__KEY scalar overrides from the settings schema. YAML
   and TOML Docker examples have equivalent effective configuration. For arrays,
   mount an explicit replacement config file and set PRINT_BUDDY_CONFIG to it.
5. Before any authorized startup, inspect `docker compose config` locally because
   it resolves secrets; do not paste that output into an issue. Run the bot's
   `python3 -m print_buddy.bot check` in an approved offline container with dummy
   credentials before considering an authorized live deployment.

No source checkout is mounted onto /app. Plugins, including print-feedback, ship
inside the image; editing host source cannot mask broken packaging.

## Services and health

The Compose file defines bot and listener using the same selected image, plus
the included Spoolman service. It publishes no ports.

## Included Spoolman

Spoolman is included in the standard deployment ([#214](https://github.com/catduckgnaf/print-buddy/issues/214)); it is not an
opt-in extra and there is no separate Spoolman Compose file to add. A plain
`docker compose up -d` starts all three services:

| Service | Image | Notes |
| --- | --- | --- |
| `spoolman` | `ghcr.io/donkie/spoolman:0.27.0` (pinned) | Data in `PRINT_BUDDY_DATA/spoolman`, mapped to `/home/app/.local/share/spoolman`; 512 MiB memory limit; no host port published |
| `bot`, `listener` | the selected Print Buddy image | Both wait for Spoolman's healthcheck (`GET /api/v1/health`) via `depends_on: service_healthy`, and are wired to it automatically |

Print Buddy is configured to use the included Spoolman without the user
discovering or entering its internal URL: Compose sets
`PRINT_BUDDY__SERVICES__SPOOLMAN_URL` to `http://spoolman:8000` on bot and
listener whenever that variable is empty or unset in `.env`. Spoolman data
persists across container recreation in that directory; recreate with
`docker compose up -d` (never `docker compose down -v`).
Starting the included Spoolman changes no spool or printer state by itself:
it is a filament-record database. Print Buddy only reads or writes spool
records through its normal, user-initiated flows.

Supported version and update policy: the supported Spoolman is the pinned
`0.27.0` image above, the same release the CI Spoolman job installs. The pin
never floats on `latest`, Print Buddy never auto-updates Spoolman, and users
should not change the tag on their own. A version bump lands as a reviewed
change to the pin in `docker-compose.yml` and the Unraid Spoolman template
together, after the acceptance harness passes with the new image. Before any
such update, back up `PRINT_BUDDY_DATA/spoolman`; to roll back, restore the
previous pin and that backup. No automatic database downgrade is provided.

Network exposure: the Compose stack publishes no Spoolman port, so the
Spoolman UI and API are reachable only from inside the Compose network.
That is deliberate: Spoolman has no login of its own worth exposing. To use
its web UI, reach it from the host without publishing it (for example an SSH
tunnel or a one-off local override you create and review yourself); never
forward a Spoolman port from a router or expose it publicly.

Using an existing external Spoolman instead: set
`PRINT_BUDDY__SERVICES__SPOOLMAN_URL` in `.env` to that instance (for
example `http://spoolman.example:8000`) and Print Buddy uses it. Nothing is
migrated, reset, overwritten or silently redirected: the external instance's
data and configuration are untouched, the included container still starts
(its own data directory is simply unused while the override is set), and
removing the override returns Print Buddy to the included Spoolman with its
data as it was left. Changing a URL never moves a database; to actually move
between instances, export/import using Spoolman's own supported procedure
and keep the old data directory until the move is verified.

Bot health reports its handler count and checks its standalone Discord connection, freshness,
container identity and Linux process start identity. Listener health checks its
own event-loop heartbeat and identity, not the bot's file. Printer connectivity
is reported separately: an offline printer does not make a live reconnecting
listener unhealthy. A stale heartbeat, replaced process or other container cannot
satisfy health. Listener heartbeat is cancelled when its loop exits.

The entrypoint uses tini and exec; a display wrapper is started only when Orca
exists and DISPLAY is unset. Its cleanup and signal behavior needs image proof.
Do not scale multiple instances of the same service sharing one state directory.
Distinct bot/listener files prevent cross-service health, not shared-state races
between replicas of one service.

## Unraid DockerMan parity (manual candidate setup)

No DockerMan template is published by this draft, and nothing here is a
published Unraid Community Applications (CA) listing: submitting these
templates to CA is a separate external step that has not happened (#180
tracks the CA route). What this repo provides for Unraid today is three
template proposals in `docker/unraid/`: `print-buddy-bot.xml`,
`print-buddy-listener.xml` and `print-buddy-spoolman.xml` (the included
Spoolman). Tests keep them in step with Compose, and the acceptance harness
runs the bot/listener templates' docker arguments. The bot/listener
Repository is a `REPLACE_WITH_TESTED_IMAGE` placeholder; the Spoolman
template's Repository is the pinned upstream `ghcr.io/donkie/spoolman:0.27.0`.
After separate deployment approval, copy the templates to
`/boot/config/plugins/dockerMan/templates-user/`, set the bot/listener
Repository to the tested image, or create the three entries by hand:
Print Buddy Bot, Print Buddy Listener and spoolman. Override the bot/listener
commands respectively with `python3 -m print_buddy.bot` and
`python3 -m print_buddy.hermes.moonraker_event_listener`.
Map the same four persistent paths to /data/hermes, /data/archive, /data/records
and /data/cache, and the Spoolman data path to
/mnt/user/appdata/print-buddy/spoolman. Preserve UID/GID 1000 ownership. Set PRINT_BUDDY_CONFIG to
/app/config/docker.yaml and PRINT_BUDDY__BOT__MODE to standalone. Copy the same
required scalar settings and secrets into each Print Buddy entry, without exposing host
ports. Apply Compose's health commands respectively:
`python3 -m print_buddy.bot health` and `python3 -m print_buddy.healthcheck`.
Use no-new-privileges, drop capabilities, 2 CPU/2 GiB and a 256 PID limit as the
starting runtime envelope for bot/listener, and 512 MiB for Spoolman. Slicer memory requirements remain unverified; do not
confuse these example service limits with the earlier 4 CPU/6 GiB build approval.

Unraid limitations, specific to the included Spoolman:

- DockerMan has no `depends_on`: nothing waits for Spoolman's healthcheck
  before Print Buddy starts. Print Buddy tolerates Spoolman being briefly
  unavailable at startup, but start (or restart) spoolman first and let its
  healthcheck pass before relying on spool features.
- Containers on Unraid's default bridge network cannot reach each other by
  container name. Put all three containers on the same custom Docker network
  and keep the Spoolman container named `spoolman`, so the default
  `http://spoolman:8000` in the bot/listener templates resolves. If you cannot
  do that, publish the Spoolman template's port (host 7912 to container 8000)
  and set the bot/listener Spoolman URL to `http://<unraid-host>:7912`
  instead. That port is then reachable on the LAN: never forward it from the
  router or expose Spoolman publicly.
- The Spoolman template publishes that 7912 port by default so its web UI is
  usable from the LAN, unlike the Compose stack, which publishes nothing.
  Delete the port mapping in DockerMan if you do not want the UI reachable
  and Print Buddy shares the custom network.
- Persistence is the single appdata path above; back it up with the other
  Print Buddy appdata paths. Recreating the container from the template
  keeps it; deleting the container and its appdata does not.

DockerMan installation and persistence have not been exercised on Unraid.

## Validation and attribution

`tests/docker/image_acceptance.sh IMAGE [included]` is the offline runtime
acceptance for one already-built image. It never builds, pulls or pushes. It runs under
a unique Compose project on an internal network with no route out, uses dummy
secrets, and removes only its own containers. It checks:

- the payload and handlers, without a source mount
- Orca's executable and shared-library closure, or its absence
- real slicing plus G-code guards, or fail-closed refusal
- read-only root behaviour
- per-service bot and listener readiness
- refusal of foreign and stopped heartbeats
- SIGTERM, recreation persistence, and a same-image tag switch (recreation only, not an
  upgrade)
- included Spoolman persistence

The hosted equivalent, `.github/workflows/docker-image-validation.yml`, only runs when a
maintainer dispatches it, and never publishes anything.

See DOCKER-117-PROGRESS.md and DOCKER-117-ACCEPTANCE.md for exact evidence and outstanding gates. Source tests
are not a source-built Orca image, runtime fixture, release, or live-printer test.

Standalone foundations originated in zaheria985/print-buddy commit
fba5727184dd8f0070e59c8f1fc088751142a003 and merged through #132. Contributor
Docker #139 commit 3bb0984250c20eb336d11ba1da06633950b45182 (MIT) informs the
Spoolman service (originally an optional override, included in the base stack
by #214), build-context filtering and listener heartbeat.
The current health implementation additionally binds container/process identity;
the source-build option and pinned official prebuilt preserve that attribution.
Original contributor commits and license notices remain intact.

## Settings and external service boundaries

The complete runtime scalar inventory and defaults live in config/home.yaml and
[SETTINGS.md](SETTINGS.md), which a test keeps complete. Every scalar accepts PRINT_BUDDY__SECTION__KEY;
use integer spelling for schema integer defaults (for example MAX_MERGED_HOURS=12,
not 12.0). Arrays and nested mappings require a mounted YAML/TOML file. Optional
keys include services.octoprint_url and printer.nozzle_type. Unknown settings fail
at startup instead of silently changing behavior. .env.example starts with the
required values and lists every other scalar commented out. Compose reads .env but a direct DockerMan entry
requires the same variables entered manually. Runtime secrets are separate:
DISCORD_BOT_TOKEN, OCTOPRINT_API_KEY and the configured LLM key variable.

Select brand/model with printer.model, not a separate unsupported printer.brand:
flashforge.ad5x, klipper.generic, sovol.sv06 or octoprint.marlin. Selection alone
does not erase AD5X values inherited from home.yaml. For a single-extruder model,
explicitly set printer.ifs_slots=1 and the actual bed, height, firmware and Orca
template directory. See OCTOPRINT-MARLIN.md and the selected printer's defaults.
Example partial override (merge into a copy of docker.yaml, do not discard its
container paths and source-installed Orca command):

```yaml
printer:
  model: octoprint.marlin
  firmware: Marlin
  ifs_slots: 1
  bed_mm: [220, 220]
  max_print_height_mm: 220
orca:
  templates: print_buddy/templates/orca/octoprint_marlin
services:
  octoprint_url: http://octoprint.example:5000
```

Equivalent scalar variables: PRINT_BUDDY__PRINTER__MODEL=octoprint.marlin,
PRINT_BUDDY__PRINTER__IFS_SLOTS=1,
PRINT_BUDDY__SERVICES__OCTOPRINT_URL=http://octoprint.example:5000;
OCTOPRINT_API_KEY supplies its secret. YAML and TOML use the same section/key names.
This is configuration, not physical certification of the selected printer.

Moonraker uses services.moonraker_url (HTTP) and moonraker_ws_url (WebSocket).
Empty WebSocket and camera URLs derive from Moonraker when set; override
camera_snapshot_url explicitly for a different scheme, port or route. Fluidd is
an external browser UI, not a runtime service API: there is no fluidd_url setting.
Klipper is reached through Moonraker, not a direct klipper_url setting. OctoPrint
uses its own adapter; the separately configured Moonraker listener is not an
OctoPrint event monitor. Do not start the listener for an OctoPrint-only setup.
No printer services are bundled. Outbound reachability to the chosen endpoints
and Discord is required for live operation; no inbound port is required by the
base example. Do not expose Moonraker, OctoPrint or Spoolman publicly as a shortcut.
Actual network changes and live startup require their own review/approval.

APP_CHANNEL and ORCA_SOURCE are independent build selectors, not YAML runtime
settings. The current default stable Orca pin is 2.4.2, not 2.5.0 stable. The alpha
pin is 2.5.0-alpha. On a future stable 2.5.0 release, update the stable source ref
and version documentation together, verify the new build/runtime and promote the
exact tested artifact. No automatic transition or published channel exists yet.

## Candidate upgrade, persistence and rollback procedure

These are proposed operator steps for a separately approved deployment, not an
assertion that container recreation has passed here.

1. Record the currently tested immutable image digest, effective config path and
   the four persistent host paths. Keep secrets outside the image. Stop both
   services before a consistent data migration. Never use compose down -v.
2. Preserve /data/hermes (state, prompts, hardware and job records), /data/archive,
   /data/records and /data/cache. Their legacy hermes directory name is not a
   dependency on a Hermes installation. User-managed recovery copies must include
   config and secrets with restricted permissions. This PR creates no backup job.
3. Change PRINT_BUDDY_IMAGE only to a separately tested digest. Reuse the same
   writable host directories and selected config mount. Start only the applicable
   approved services; check their distinct health commands. Health is not slicing
   or physical-print approval. A no-Orca image cannot create a verified slice.
4. Roll back by stopping the candidate, restoring the recorded digest and matching
   config, and reusing compatible data. No automatic schema downgrade is provided.
   If state schema changes incompatibly, restore the matching operator recovery
   data before startup; do not run an older binary over unknown newer state.

Spoolman is included in the same Compose file, so the upgrade and rollback
steps above cover it too: its database lives in PRINT_BUDDY_DATA/spoolman and
survives recreation. Back that directory up with the other four before an
upgrade. To use an external Spoolman instead, set its URL in .env (see
[Included Spoolman](#included-spoolman)); never delete the included data
directory to switch, and changing a URL does not move a database.
Included-Spoolman recreation remains an image/runtime acceptance gate.

Troubleshooting: check selected YAML/TOML path and UID 1000 permissions first;
use bot check for missing required inputs. Bot health fails until Discord is
connected; dummy credentials intentionally cannot demonstrate healthy login.
Listener health reports an offline printer separately. Missing Orca is a refusal,
not permission to send unsliced geometry. Docker restart unless-stopped reacts to
process exit, not to an unhealthy healthcheck alone. No autoheal is supplied.
Manual DockerMan parity also requires restart unless-stopped, shared memory 256m
and rotating json-file logs (max-size 10m, max-file 3); apply the same config mount
and the included-Spoolman URL (or your external Spoolman URL, if you set one).
Do not bind-mount the source tree over /app.
