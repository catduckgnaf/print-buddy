# Docker

Run Print Buddy + OrcaSlicer CLI + Spoolman as containers. Settings come from environment variables (`PRINT_BUDDY__SECTION__KEY`) or a mounted TOML.

Pinned OrcaSlicer v2.4.2 AppImage (matches the generation used by the Flathub CI job). Spoolman is the official image.

## Quick start

```bash
cp .env.example .env
# edit .env: set PRINT_BUDDY__SERVICES__MOONRAKER_URL and Discord IDs
mkdir -p data/hermes data/archive data/records data/cache data/spoolman
# Spoolman data dir must be writable by uid 1000
sudo chown 1000:1000 data/spoolman
docker compose up -d
```

Open Spoolman at http://localhost:7912. Print Buddy listens on Moonraker and posts to Discord via the mounted Hermes profile at `data/hermes`.

## Volumes

- `data/hermes` → `/data/hermes` (profile, state, logs)
- `data/archive` → `/data/archive`
- `data/records` → `/data/records`
- `data/cache` → `/data/cache`
- `data/spoolman` → Spoolman SQLite

## Environment

Every scalar setting can be set with `PRINT_BUDDY__SECTION__KEY`. See `.env.example` and the README settings table.

Lists (`[orca] command`, `[printer] bed_mm`) cannot come from the environment. They live in `config/docker.toml` (used when `PRINT_BUDDY_CONFIG` is set). Mount a replacement file to change them:

```yaml
volumes:
  - ./my-config.toml:/app/config/docker.toml:ro
```

Legacy names (`MOONRAKER_URL`, `SPOOLMAN_URL`, …) still work.

## Hermes

The current Discord bot and listener expect a Hermes profile. Mount one at `/data/hermes` (or set `PRINT_BUDDY__PATHS__HERMES_HOME`). Standalone mode (no Hermes) is tracked in #73 and will simplify this image.

## Unraid

Use the compose file as a template. Map the data paths and set the environment variables in the template. Spoolman can be a separate container or the same stack.
