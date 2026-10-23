# Settings reference

Every user-adjustable setting, its YAML key, its environment variable and its default in the Docker image (`config/docker.yaml` on top of `config/home.yaml` and the printer model). `tests/test_docker_release.py` fails when a setting is added without a row here, an `.env.example` entry, or when a documented name stops being a real setting.

* **YAML**: put keys in a file and select it with `PRINT_BUDDY_CONFIG` (Docker: mount it, e.g. at `/app/config/local.yaml`). Nested form: `services:` / `  moonraker_url: http://printer.example:7125`.
* **Environment**: `PRINT_BUDDY__SECTION__KEY=value` overrides any file. Booleans accept `true/false`, `1/0`, `yes/no`, `on/off`. Rows marked *file only* are lists or tables and can only come from YAML (or legacy TOML).
* **Precedence**, later wins: printer model defaults (*model*), `config/home.yaml`, the `PRINT_BUDDY_CONFIG` file, environment. Settings are read once at start: restart the container after a change.
* A typo or invalid value stops startup and names the setting. YAML holds no secrets; see [Secrets](#secrets).

General schema, validation limits and TOML migration: [CONFIGURATION-YAML.md](CONFIGURATION-YAML.md).

| YAML key | Environment variable | Docker default | What it does |
|---|---|---|---|
| `printer.name` | `PRINT_BUDDY__PRINTER__NAME` | `Flashforge AD5X` *model* | Printer name shown in job summaries |
| `printer.firmware` | `PRINT_BUDDY__PRINTER__FIRMWARE` | `ZMod Klipper` *model* | Firmware label shown in job summaries |
| `printer.start_macro` | `PRINT_BUDDY__PRINTER__START_MACRO` | `START_PRINT` *model* | Klipper start macro for stock Klipper models |
| `printer.end_macro` | `PRINT_BUDDY__PRINTER__END_MACRO` | `END_PRINT` *model* | Klipper end macro for stock Klipper models |
| `printer.bed_mm` | file only | `[220.0, 220.0]` *model* | Usable print area `[x, y]` in mm |
| `printer.max_print_height_mm` | `PRINT_BUDDY__PRINTER__MAX_PRINT_HEIGHT_MM` | `220.0` *model* | Tallest allowed print |
| `printer.nozzle_diameter_mm` | `PRINT_BUDDY__PRINTER__NOZZLE_DIAMETER_MM` | `0.4` *model* | Installed nozzle; slicing refuses any other |
| `printer.ifs_slots` | `PRINT_BUDDY__PRINTER__IFS_SLOTS` | `4` *model* | Filament slots; 1 for a single extruder |
| `printer.model` | `PRINT_BUDDY__PRINTER__MODEL` | `flashforge.ad5x` | Printer brand and model: `flashforge.ad5x`, `sovol.sv06`, `klipper.generic`, `octoprint.marlin`. Sets every model default marked *model* |
| `printer.nozzle_type` | `PRINT_BUDDY__PRINTER__NOZZLE_TYPE` | unset | Optional nozzle material, limited to the model's supported types |
| `layout.single_copy_edge_mm` | `PRINT_BUDDY__LAYOUT__SINGLE_COPY_EDGE_MM` | `1.0` *model* | Bed-edge clearance for one copy |
| `layout.multi_copy_edge_mm` | `PRINT_BUDDY__LAYOUT__MULTI_COPY_EDGE_MM` | `3.0` *model* | Bed-edge clearance for several copies |
| `layout.merge_edge_margin_mm` | `PRINT_BUDDY__LAYOUT__MERGE_EDGE_MARGIN_MM` | `8.0` *model* | Edge margin when merging plates |
| `layout.merge_spacing_mm` | `PRINT_BUDDY__LAYOUT__MERGE_SPACING_MM` | `10.0` *model* | Gap between merged plates' parts |
| `layout.max_merged_hours` | `PRINT_BUDDY__LAYOUT__MAX_MERGED_HOURS` | `12.0` | Merged plates longer than this stay separate |
| `prime_tower.size_mm` | `PRINT_BUDDY__PRIME_TOWER__SIZE_MM` | `45.0` *model* | Prime tower size |
| `prime_tower.part_clearance_mm` | `PRINT_BUDDY__PRIME_TOWER__PART_CLEARANCE_MM` | `8.0` *model* | Prime tower to part clearance |
| `prime_tower.edge_mm` | `PRINT_BUDDY__PRIME_TOWER__EDGE_MM` | `10.0` *model* | Prime tower to bed edge clearance |
| `prime_tower.merge_slack_mm` | `PRINT_BUDDY__PRIME_TOWER__MERGE_SLACK_MM` | `5.0` *model* | Extra room kept for the tower when merging |
| `orca.templates` | `PRINT_BUDDY__ORCA__TEMPLATES` | the model's folder *model* | Folder with the Orca machine, process and filament JSON |
| `orca.command` | file only | `["/opt/orcaslicer/AppRun"]` | How to start the OrcaSlicer CLI; the image bundles it at `/opt/orcaslicer/AppRun` |
| `bambu.command` | file only | `["true"]` | Fallback Bambu Studio CLI; not bundled in the image (`true` disables it) |
| `paths.hermes_home` | `PRINT_BUDDY__PATHS__HERMES_HOME` | `/data/hermes` | Profile/state folder; holds `state/` (runtime state, heartbeat) and `logs/` |
| `paths.archive` | `PRINT_BUDDY__PATHS__ARCHIVE` | `/data/archive` | Job archive |
| `paths.records_vault` | `PRINT_BUDDY__PATHS__RECORDS_VAULT` | `/data/records` | Obsidian print records |
| `paths.cache` | `PRINT_BUDDY__PATHS__CACHE` | `/data/cache` | Regenerable cache (also the container's `HOME`, `TMPDIR` and work dir) |
| `paths.hermes_bin` | `PRINT_BUDDY__PATHS__HERMES_BIN` | `/usr/local/bin/hermes` | Hermes CLI used for Discord posts until standalone mode (#73); not in the image |
| `paths.ffmpeg` | `PRINT_BUDDY__PATHS__FFMPEG` | `ffmpeg` | ffmpeg binary or name on `PATH` |
| `paths.hermes_agent` | `PRINT_BUDDY__PATHS__HERMES_AGENT` | `/data/hermes/hermes-agent` | Hermes agent checkout (Hermes installs only) |
| `paths.hermes_restart_helper` | `PRINT_BUDDY__PATHS__HERMES_RESTART_HELPER` | `/data/hermes/restart_hermes.py` | Hermes restart helper (Hermes installs only) |
| `services.moonraker_url` | `PRINT_BUDDY__SERVICES__MOONRAKER_URL` | empty | Klipper printers: Moonraker HTTP URL, e.g. `http://printer.example:7125`. Required for the listener |
| `services.moonraker_ws_url` | `PRINT_BUDDY__SERVICES__MOONRAKER_WS_URL` | empty | Moonraker websocket; derived from `moonraker_url` when empty |
| `services.camera_snapshot_url` | `PRINT_BUDDY__SERVICES__CAMERA_SNAPSHOT_URL` | empty | Camera snapshot URL; derived from the Moonraker host when empty |
| `services.spoolman_url` | `PRINT_BUDDY__SERVICES__SPOOLMAN_URL` | empty | Spoolman URL. External by default; the bundled-Spoolman Compose file sets `http://spoolman:8000` |
| `services.openviking_url` | `PRINT_BUDDY__SERVICES__OPENVIKING_URL` | empty | Optional OpenViking memory store |
| `services.vision_chat_url` | `PRINT_BUDDY__SERVICES__VISION_CHAT_URL` | empty | OpenAI-compatible endpoint for camera checks and roasts; empty disables both |
| `services.stock_api_port` | `PRINT_BUDDY__SERVICES__STOCK_API_PORT` | `8898` | Flashforge stock API port for IFS presence |
| `services.octoprint_url` | `PRINT_BUDDY__SERVICES__OCTOPRINT_URL` | empty | OctoPrint printers (`octoprint.marlin`): OctoPrint URL. API key: `OCTOPRINT_API_KEY` secret |
| `discord.chat_id` | `PRINT_BUDDY__DISCORD__CHAT_ID` | empty | Discord channel ID |
| `discord.approval_user_id` | `PRINT_BUDDY__DISCORD__APPROVAL_USER_ID` | empty | Discord user ID allowed to approve |
| `discord.upload_max_bytes` | `PRINT_BUDDY__DISCORD__UPLOAD_MAX_BYTES` | `9500000` | Largest upload before video is shrunk |
| `discord.post_print_quiet_s` | `PRINT_BUDDY__DISCORD__POST_PRINT_QUIET_S` | `7200` | Quiet time before a chat session resets |
| `discord.daily_reset_hour` | `PRINT_BUDDY__DISCORD__DAILY_RESET_HOUR` | `4` | Hour of the daily session reset |
| `discord.timezone` | `PRINT_BUDDY__DISCORD__TIMEZONE` | `America/New_York` | Display and reset time zone (IANA name) |
| `discord.bot_name` | `PRINT_BUDDY__DISCORD__BOT_NAME` | `Print Buddy` | Name the bot uses for itself |
| `discord.question_timeout_s` | `PRINT_BUDDY__DISCORD__QUESTION_TIMEOUT_S` | `1800` | How long a Discord question waits for a button |
| `discord.safety_confirm_timeout_s` | `PRINT_BUDDY__DISCORD__SAFETY_CONFIRM_TIMEOUT_S` | `600` | How long a safety confirmation waits |
| `discord.upload_wait_s` | `PRINT_BUDDY__DISCORD__UPLOAD_WAIT_S` | `3600` | How long an upload-wait freeze stays active |
| `discord.cold_pull_outcome_s` | `PRINT_BUDDY__DISCORD__COLD_PULL_OUTCOME_S` | `1800` | How long a cold-pull outcome prompt stays open |
| `listener.tick_s` | `PRINT_BUDDY__LISTENER__TICK_S` | `600` | Listener housekeeping interval |
| `listener.ifs_presence_poll_s` | `PRINT_BUDDY__LISTENER__IFS_PRESENCE_POLL_S` | `15` | IFS spool presence poll |
| `listener.spool_nag_s` | `PRINT_BUDDY__LISTENER__SPOOL_NAG_S` | `600` | Reminder interval for an unanswered spool question |
| `listener.start_claim_ttl_s` | `PRINT_BUDDY__LISTENER__START_CLAIM_TTL_S` | `1800` | How long a start button stays claimed |
| `vision.model` | `PRINT_BUDDY__VISION__MODEL` | `gemini-latest` | Model for camera checks |
| `vision.roast_model` | `PRINT_BUDDY__VISION__ROAST_MODEL` | `luna-latest` | Model for the print-start roast |
| `visual_watch.sensitivity` | `PRINT_BUDDY__VISUAL_WATCH__SENSITIVITY` | `3` | Stall alert sensitivity, 1 (quiet) to 5 |
| `visual_watch.enabled` | `PRINT_BUDDY__VISUAL_WATCH__ENABLED` | `true` | Camera monitoring switch |
| `timelapse.archive_host` | `PRINT_BUDDY__TIMELAPSE__ARCHIVE_HOST` | empty | SSH host for the timelapse archive; empty disables it |
| `timelapse.archive_dir` | `PRINT_BUDDY__TIMELAPSE__ARCHIVE_DIR` | empty | Archive folder on that host |
| `timelapse.ssh_key` | `PRINT_BUDDY__TIMELAPSE__SSH_KEY` | empty | Path of the SSH key in the container (mount it read-only) |
| `timelapse.render_wait_s` | `PRINT_BUDDY__TIMELAPSE__RENDER_WAIT_S` | `900` | Wait for the printer to render the timelapse |
| `timelapse.render_poll_s` | `PRINT_BUDDY__TIMELAPSE__RENDER_POLL_S` | `10` | Poll interval while waiting |
| `timelapse.max_bytes` | `PRINT_BUDDY__TIMELAPSE__MAX_BYTES` | `209715200` | Largest timelapse kept |
| `timelapse.local_retention_days` | `PRINT_BUDDY__TIMELAPSE__LOCAL_RETENTION_DAYS` | `1` | Local copy retention |
| `timelapse.plan_clip_retention_days` | `PRINT_BUDDY__TIMELAPSE__PLAN_CLIP_RETENTION_DAYS` | `14` | Plan clip retention |
| `maintenance.quick_hours` | `PRINT_BUDDY__MAINTENANCE__QUICK_HOURS` | `25` | Quick maintenance due after these print hours |
| `maintenance.full_hours` | `PRINT_BUDDY__MAINTENANCE__FULL_HOURS` | `75` | Full maintenance due after these print hours |
| `maintenance.full_days` | `PRINT_BUDDY__MAINTENANCE__FULL_DAYS` | `30` | Full maintenance due after these days |
| `nozzle_temp_offsets.<type>` | `PRINT_BUDDY__NOZZLE_TEMP_OFFSETS__<TYPE>` | `0.0` | Temperature offset, −10 to +15 °C, for `brass`, `hardened_steel`, `stainless_steel`, `ruby`, `tungsten_carbide`, `diamond` |
| `material_temps.<MATERIAL>` | file only | see `config/home.yaml` | `{nozzle, bed}` fallback temperatures for PLA, PETG, ABS, ASA, TPU, PA, PC; Spoolman filament values win |
| `cold_pull.<profile>` | file only | `pla_trial: [220, 90]`, `petg: [245, 100]` *model* | Hot and cold cold-pull temperatures; profile names are yours |

## Container and Compose variables

These configure the container, not Print Buddy itself. Set them in `.env`.

| Variable | Default | What it does |
|---|---|---|
| `PRINT_BUDDY_CONFIG` | `/app/config/docker.yaml` | Settings file the container reads (YAML, or legacy `.toml`) |
| `PRINT_BUDDY_IMAGE` | `ghcr.io/catduckgnaf/print-buddy` | Image repository |
| `PRINT_BUDDY_TAG` | `stable` | Image tag: an exact version such as `2.1.0` (recommended), or the moving `stable` / `next` channel |
| `PRINT_BUDDY_DATA` | `./data` | Host folder holding the `hermes`, `archive`, `records`, `cache` (and bundled `spoolman`) volumes |
| `PUID`, `PGID` | `1000`, `1000` | User and group the containers run as; must own the data folders |
| `TZ` | `Etc/UTC` | Container time zone (log timestamps). Message times use `discord.timezone` |
| `PRINT_BUDDY_CPUS`, `PRINT_BUDDY_MEMORY` | `2`, `4g` | Resource limits for the Print Buddy container |
| `PRINT_BUDDY_HEALTH_MAX_AGE_S` | `90` | Heartbeat age after which the health check fails |
| `COMPOSE_FILE` | `docker-compose.yml` | Add `:docker-compose.spoolman.yml` for the bundled Spoolman |
| `SPOOLMAN_TAG`, `SPOOLMAN_PORT` | `0.27.0`, `7912` | Bundled Spoolman image tag and published host port |
| `ORCA_CHANNEL` | `alpha` | Build argument only (`docker-compose.build.yml`): OrcaSlicer channel to bundle, see [DOCKER.md](DOCKER.md#orcaslicer-channel) |

## Secrets

Secrets are read from the environment (Docker: `.env`, which must not be shared or committed), never from YAML. On a Hermes install they may also live in the Hermes profile `.env`.

| Variable | Used for |
|---|---|
| `DISCORD_BOT_TOKEN` | Discord buttons, plate picker and other direct Discord API posts |
| `OCTOPRINT_API_KEY` | `octoprint.marlin` printers: OctoPrint application key |
| `MOONRAKER_API_KEY` | Moonraker API key, only when Moonraker requires one |
| `CLIPROXY_API_KEY` | Key for `services.vision_chat_url` |
| `OPENVIKING_API_KEY` | Key for `services.openviking_url` |

## Legacy environment names

The names below predate `PRINT_BUDDY__SECTION__KEY` and still work; new installs should use the long form. The full map is `LEGACY_ENV` in `print_buddy/settings.py`, e.g. `MOONRAKER_URL` → `services.moonraker_url`, `SPOOLMAN_URL` → `services.spoolman_url`, `PRINT_DISCORD_CHAT_ID` → `discord.chat_id`.
