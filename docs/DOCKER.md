# Docker candidate: issue #117 / PR #134

This is an unreleased candidate, not a supported image or deployment approval.
Do not use production credentials or a live printer to validate this draft.

## Build dimensions

The same Dockerfile supports two application channels, each running either the
standalone Discord bot or Moonraker listener. There is no combined supervisor.

| Build argument | Values | Meaning |
| --- | --- | --- |
| APP_CHANNEL | stable, development (default) | Application provenance label, not a Git checkout |
| WITH_ORCA | false (default), true | Include a source-built slicer or omit it |
| ORCA_CHANNEL | stable (default), alpha | Independently select the pinned slicer revision |

Build from the intended source checkout. Setting APP_CHANNEL does not switch the
application source. The proposed branch policy is main for stable candidates and
development for development candidates; this PR does not create branches or
publish tags. Development validation precedes promotion of the exact tested
source revision and image digest to stable. Rollback selects the previous tested
digest and preserves data. Neither branch labels nor green Python CI prove an
image works. Do not promote an untested source rebuild as an identical artifact.

Orca stable v2.4.2 is pinned to 8500fcdccaa10b5099ac20d252af3a7c560046f1;
alpha v2.5.0-alpha is pinned to 3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2.
The build uses source CMake dependencies and FHS installation, never AppImages.
Changing runtime environment variables cannot install or change a bundled slicer.
A no-Orca image can handle non-slicing commands; slicing requires the absent
/usr/bin/orca-slicer and must fail without an approved slice artifact. No remote
slicing fallback is provided. Exact user-facing failure behavior still needs
image verification. Alpha and ARM64 source builds are unverified; no multiarch
publication is claimed.

Example build commands, to run only after the relevant container approval:

```sh
docker build --build-arg APP_CHANNEL=development --build-arg WITH_ORCA=false -t print-buddy:development-no-orca .
docker build --build-arg APP_CHANNEL=stable --build-arg WITH_ORCA=true --build-arg ORCA_CHANNEL=stable -t print-buddy:stable-orca-stable .
```

## First-run configuration

1. Copy .env.example to .env outside any published artifact. Set the Discord token,
   chat ID, allowed numeric user IDs and required service URLs. Bot mode is
   standalone. LLM configuration remains optional. Never bake secrets into images.
2. Set PRINT_BUDDY_IMAGE in .env to an approved local tag or immutable tested image
   digest. There is intentionally no invented published image default.
3. Set PRINT_BUDDY_DATA to an absolute persistent directory. Create its hermes,
   archive, records and cache subdirectories writable by container UID/GID 1000.
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

The base Compose file defines bot and listener using the same selected image.
It publishes no ports and requires no bundled Spoolman. Supply an existing
Spoolman URL with PRINT_BUDDY__SERVICES__SPOOLMAN_URL if used.

The optional docker-compose.spoolman.yml override adds pinned Spoolman 0.27.0
and persistent data, setting its internal URL on both services. This optional
container is not required, tested here, or approved for creation by this PR.
It publishes no UI port. Adding a host listener requires separate network review.

Bot health checks its standalone Discord connection, handler state, freshness,
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

No DockerMan template is published by this draft. After separate deployment
approval, create two entries from the same tested image: Print Buddy Bot and
Print Buddy Listener. Override the commands respectively with
`python3 -m print_buddy.bot` and
`python3 -m print_buddy.hermes.moonraker_event_listener`.
Map the same four persistent paths to /data/hermes, /data/archive, /data/records
and /data/cache. Preserve UID/GID 1000 ownership. Set PRINT_BUDDY_CONFIG to
/app/config/docker.yaml and PRINT_BUDDY__BOT__MODE to standalone. Copy the same
required scalar settings and secrets into each entry, without exposing host
ports. Apply Compose's health commands respectively:
`python3 -m print_buddy.bot health` and `python3 -m print_buddy.healthcheck`.
Use no-new-privileges, drop capabilities, 2 CPU/2 GiB and a 256 PID limit as the
starting runtime envelope. Slicer memory requirements remain unverified; do not
confuse these example service limits with the earlier 4 CPU/6 GiB build approval.
DockerMan installation and persistence have not been exercised on Unraid.

## Validation and attribution

See DOCKER-117-PROGRESS.md for exact evidence and outstanding gates. Source tests
are not a source-built Orca image, runtime fixture, release, or live-printer test.

Standalone foundations originated in zaheria985/print-buddy commit
fba5727184dd8f0070e59c8f1fc088751142a003 and merged through #132. Contributor
Docker #139 commit 3bb0984250c20eb336d11ba1da06633950b45182 (MIT) informs the
optional Spoolman override, build-context filtering and listener heartbeat.
The current health implementation additionally binds container/process identity;
the source build deliberately replaces the contributor's binary-download route.
Original contributor commits and license notices remain intact.
