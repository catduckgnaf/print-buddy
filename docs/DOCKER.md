# Docker

Run Print Buddy + OrcaSlicer CLI + Spoolman as containers. Settings come from environment variables (`PRINT_BUDDY__SECTION__KEY`) or a mounted YAML config. The image defaults to `config/docker.yaml`; `config/docker.toml` remains supported for existing mounts.

Pinned OrcaSlicer v2.4.2 AppImage (matches the generation used by the Flathub CI job). The Compose file runs Spoolman as a separate service.

## Quick start

```bash
cp .env.example .env
# edit .env: set PRINT_BUDDY__SERVICES__MOONRAKER_URL and Discord IDs
mkdir -p data/hermes data/archive data/records data/cache data/spoolman
# Spoolman data dir must be writable by uid 1000
sudo chown 1000:1000 data/spoolman
docker compose up -d
```

Open Spoolman at http://localhost:7912. Print Buddy connects to Moonraker and posts to Discord using the Hermes profile mounted at `data/hermes`. The Compose file publishes Spoolman on host port 7912; it does not publish a Print Buddy port.

## Updating and stopping

Pull the desired source revision, then rebuild and recreate the services with `docker compose up -d --build`. Stop the stack with `docker compose down`; bind-mounted data remains in `./data/`.

## Volumes

- `data/hermes` → `/data/hermes` (profile, state, logs)
- `data/archive` → `/data/archive`
- `data/records` → `/data/records`
- `data/cache` → `/data/cache`
- `data/spoolman` → Spoolman SQLite

## Environment

Every scalar setting can be set with `PRINT_BUDDY__SECTION__KEY`. See `.env.example` and the README settings table.

Lists (`orca.command`, `printer.bed_mm`) cannot come from the environment. They are supplied by `config/docker.yaml`. Mount a YAML replacement and set `PRINT_BUDDY_CONFIG` to its container path:

```yaml
environment:
  PRINT_BUDDY_CONFIG: /app/config/local.yaml
volumes:
  - ./config/local.yaml:/app/config/local.yaml:ro
```

For a legacy TOML mount, keep the existing target path and explicitly select it; this preserves the old file format and `/app/config/docker.toml` mount location:

```yaml
environment:
  PRINT_BUDDY_CONFIG: /app/config/docker.toml
volumes:
  - ./config/docker.toml:/app/config/docker.toml:ro
```

Legacy names (`MOONRAKER_URL`, `SPOOLMAN_URL`, …) still work.

## Hermes

The current Discord bot and listener expect a Hermes profile. Mount one at `/data/hermes` (or set `PRINT_BUDDY__PATHS__HERMES_HOME`). Standalone mode (no Hermes) is tracked in #73 and will simplify this image.

## Unraid

Use the compose file as a template. Map the data paths and set the environment variables in the template. Spoolman can be a separate container or the same stack.
