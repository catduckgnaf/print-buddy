# Settings reference

Every user-adjustable setting, its YAML key, its environment variable and its value in the Docker configuration (`config/docker.yaml` over `config/home.yaml` and the printer model). `tests/test_docker_release.py` derives the inventory from the settings schema and fails when a setting lacks a row here or an `.env.example` line, or when a documented name is not a real setting.

* **YAML**: put keys in a file and select it with `PRINT_BUDDY_CONFIG`. In Docker, mount the file and point `PRINT_BUDDY_CONFIG` at its container path.
* **Environment**: `PRINT_BUDDY__SECTION__KEY=value` overrides any file. Booleans accept `true/false`, `1/0`, `yes/no`, `on/off`. Integer settings need integer spelling (`12`, not `12.0`). Rows marked *file only* are lists or tables and can only come from YAML or legacy TOML; the one list exception is `delivery.methods`, which also accepts a comma- or space-separated environment value (`PRINT_BUDDY__DELIVERY__METHODS=discord,bambu_handoff,printer`, #270).
* **Precedence**, later wins: vendor and printer model defaults (*model*), `config/home.yaml`, the selected config file, environment. Settings are read once at start, so restart the service after a change.
* A typo or invalid value stops startup and names the setting. YAML holds no secrets; see [Secrets](#secrets).

Schema, validation limits and TOML migration: [CONFIGURATION-YAML.md](CONFIGURATION-YAML.md). Standalone bot settings: [STANDALONE.md](STANDALONE.md). Printer vendor profiles: [PRINTER-PROFILES.md](PRINTER-PROFILES.md).

| YAML key | Environment variable | Docker value | What it does |
|---|---|---|---|
| `layout.single_copy_edge_mm` | `PRINT_BUDDY__LAYOUT__SINGLE_COPY_EDGE_MM` | `1.0` *model* | Bed-edge clearance for one copy |
| `layout.multi_copy_edge_mm` | `PRINT_BUDDY__LAYOUT__MULTI_COPY_EDGE_MM` | `3.0` *model* | Bed-edge clearance for several copies |
| `layout.merge_edge_margin_mm` | `PRINT_BUDDY__LAYOUT__MERGE_EDGE_MARGIN_MM` | `8.0` *model* | Edge margin when merging plates |
| `layout.merge_spacing_mm` | `PRINT_BUDDY__LAYOUT__MERGE_SPACING_MM` | `10.0` *model* | Gap between merged plates' parts |
| `layout.max_merged_hours` | `PRINT_BUDDY__LAYOUT__MAX_MERGED_HOURS` | `12` | Merged plates longer than this stay separate |
| `prime_tower.size_mm` | `PRINT_BUDDY__PRIME_TOWER__SIZE_MM` | `45.0` *model* | Prime tower size |
| `prime_tower.part_clearance_mm` | `PRINT_BUDDY__PRIME_TOWER__PART_CLEARANCE_MM` | `8.0` *model* | Prime tower to part clearance |
| `prime_tower.edge_mm` | `PRINT_BUDDY__PRIME_TOWER__EDGE_MM` | `10.0` *model* | Prime tower to bed edge clearance |
| `prime_tower.merge_slack_mm` | `PRINT_BUDDY__PRIME_TOWER__MERGE_SLACK_MM` | `5.0` *model* | Extra room kept for the tower when merging |
| `printer.firmware` | `PRINT_BUDDY__PRINTER__FIRMWARE` | `ZMod Klipper` *model* | Firmware label shown in job summaries |
| `printer.start_macro` | `PRINT_BUDDY__PRINTER__START_MACRO` | `START_PRINT` *model* | Klipper start macro for stock Klipper models |
| `printer.end_macro` | `PRINT_BUDDY__PRINTER__END_MACRO` | `END_PRINT` *model* | Klipper end macro for stock Klipper models |
| `printer.name` | `PRINT_BUDDY__PRINTER__NAME` | `Flashforge AD5X` *model* | Printer name shown in job summaries |
| `printer.bed_mm` | file only | `[220.0, 220.0]` *model* | Usable print area `[x, y]` in mm |
| `printer.max_print_height_mm` | `PRINT_BUDDY__PRINTER__MAX_PRINT_HEIGHT_MM` | `220.0` *model* | Tallest allowed print |
| `printer.nozzle_diameter_mm` | `PRINT_BUDDY__PRINTER__NOZZLE_DIAMETER_MM` | `0.4` *model* | Installed nozzle; slicing refuses any other |
| `printer.ifs_slots` | `PRINT_BUDDY__PRINTER__IFS_SLOTS` | `4` *model* | Filament slots; 1 for a single extruder |
| `printer.tool_count` | `PRINT_BUDDY__PRINTER__TOOL_COUNT` | `1` *model* | Independent toolheads on a tool-changer model (Creator 5 / 5 Pro: 4); slicer tool *i* is toolhead *i*, never an IFS slot |
| `printer.model` | `PRINT_BUDDY__PRINTER__MODEL` | `flashforge.ad5x` | Printer brand and model: `flashforge.ad5x`, `sovol.sv06`, `klipper.generic`, `octoprint.marlin`, `bambulab.a1`, `bambulab.p1s` (Bambu Lab models are offline only). Sets every model default marked *model* |
| `printer.vendor` | `PRINT_BUDDY__PRINTER__VENDOR` | `flashforge` *model* | Vendor part of the model key, set by the model; `vendor` plus a bare printer name is also accepted |
| `printer.slicer` | `PRINT_BUDDY__PRINTER__SLICER` | `orca` *model* | Slicer: `orca` everywhere; Bambu Lab printers default to `bambu_studio` and may pick `orca` |
| `slicer.flash_studio_path` | `PRINT_BUDDY__SLICER__FLASH_STUDIO_PATH` | empty | Optional path to a Flash Studio executable the user already installed. Empty keeps OrcaSlicer. A set but missing or non-executable path is an error, not a fallback. Never downloaded or bundled. |
| `printer.nozzle_type` | `PRINT_BUDDY__PRINTER__NOZZLE_TYPE` | unset | Optional nozzle material, limited to the model's supported types |
| `orca.templates` | `PRINT_BUDDY__ORCA__TEMPLATES` | the model's folder *model* | Folder with the Orca machine, process and filament JSON |
| `orca.command` | file only | `["/usr/local/bin/orca-slicer"]` | How to start the OrcaSlicer CLI; `PRINT_BUDDY_ORCA_CHANNEL` selects stable (default) or alpha; both binaries exist only when `WITH_ORCA=true` |
| `delivery.methods` | `PRINT_BUDDY__DELIVERY__METHODS` | `["printer"]` *model* | Post-slice options offered, from the vendor profile (for example `printer`); comma- or space-separated in the environment, an empty value keeps the file value |
| `bambu.command` | file only | `["/usr/bin/bambu-studio"]` | Bambu Studio CLI: the default slicer for Bambu Lab printers, Orca's one-shot fallback elsewhere; exists only in a `WITH_BAMBU=true` image |
| `bambu.lan_host` | `PRINT_BUDDY__BAMBU__LAN_HOST` | `""` | Bambu Lab printer LAN address for read-only status (#187); must be set together with `lan_serial`; empty disables LAN status |
| `bambu.lan_serial` | `PRINT_BUDDY__BAMBU__LAN_SERIAL` | `""` | The Bambu Lab printer's serial number (stored upper case); used in the MQTT topics, not as a credential |
| `bambu.lan_access_code_env` | `PRINT_BUDDY__BAMBU__LAN_ACCESS_CODE_ENV` | `BAMBU_LAN_PASSWORD` | Name of the environment variable holding the printer's LAN access code; the code itself is never a setting |
| `bambu.start_confirm_s` | `PRINT_BUDDY__BAMBU__START_CONFIRM_S` | `90` | Bambu Lab LAN print start (#271): how long, in whole seconds (1-300), the printer is polled every 10 s to report the submitted file as preparing or running before the start is left as uncertain; keep it well under the bot's 420 s start budget, which also covers the upload |
| `flashforge_stock.host` | `PRINT_BUDDY__FLASHFORGE_STOCK__HOST` | `""` | Stock Flashforge printer LAN address; empty leaves the printer offline. The serial and check code stay in `AD5X_SERIAL` and `AD5X_CHECK_CODE`, never in a setting |
| `prusa.link_host` | `PRINT_BUDDY__PRUSA__LINK_HOST` | `""` | Prusa printer LAN address for PrusaLink; empty leaves the printer offline (slicing, checks and Discord delivery only). Prusa models only |
| `elegoo_sdcp.host` | `PRINT_BUDDY__ELEGOO_SDCP__HOST` | `""` | Centauri printer LAN address for SDCP; empty leaves the printer offline (slicing, checks and Discord delivery only). Elegoo SDCP models only. SDCP has no authentication; there is no key to configure |
| `prusa.api_key_env` | `PRINT_BUDDY__PRUSA__API_KEY_ENV` | `"PRUSA_LINK_API_KEY"` | Name of the environment variable holding the PrusaLink API key. The key itself is never a setting |
| `paths.hermes_home` | `PRINT_BUDDY__PATHS__HERMES_HOME` | `/data/hermes` | State folder (`state/`, `logs/`); the name is historical, Hermes is not required |
| `paths.archive` | `PRINT_BUDDY__PATHS__ARCHIVE` | `/data/archive` | Job archive |
| `paths.records_vault` | `PRINT_BUDDY__PATHS__RECORDS_VAULT` | `/data/records` | Obsidian print records |
| `paths.cache` | `PRINT_BUDDY__PATHS__CACHE` | `/data/cache` | Regenerable cache |
| `paths.hermes_bin` | `PRINT_BUDDY__PATHS__HERMES_BIN` | `/usr/local/bin/hermes` | Hermes CLI; Hermes installs only, not in the image |
| `paths.ffmpeg` | `PRINT_BUDDY__PATHS__FFMPEG` | `ffmpeg` | ffmpeg binary or name on `PATH` |
| `paths.hermes_agent` | `PRINT_BUDDY__PATHS__HERMES_AGENT` | `/data/hermes/hermes-agent` | Hermes agent checkout (Hermes installs only) |
| `paths.hermes_restart_helper` | `PRINT_BUDDY__PATHS__HERMES_RESTART_HELPER` | `/data/hermes/restart_hermes.py` | Hermes restart helper (Hermes installs only) |
| `services.moonraker_url` | `PRINT_BUDDY__SERVICES__MOONRAKER_URL` | empty | Klipper printers: Moonraker HTTP URL, e.g. `http://printer.example:7125`. Required by the listener |
| `services.moonraker_ws_url` | `PRINT_BUDDY__SERVICES__MOONRAKER_WS_URL` | empty | Moonraker websocket; derived from `moonraker_url` when empty |
| `services.camera_source` | `PRINT_BUDDY__SERVICES__CAMERA_SOURCE` | `auto` | Which camera still images come from (#294): `auto` follows the printer vendor's rule, or pin `moonraker`, `bambu`, `go2rtc`, or `none` |
| `services.camera_snapshot_url` | `PRINT_BUDDY__SERVICES__CAMERA_SNAPSHOT_URL` | empty | Camera snapshot URL; derived from the Moonraker host when empty |
| `services.spoolman_url` | `PRINT_BUDDY__SERVICES__SPOOLMAN_URL` | empty | Spoolman URL. The Docker config and Compose default to `http://127.0.0.1:8000`, the bundled Spoolman API in the same container. Set another URL, plus `PRINT_BUDDY_BUNDLED_SPOOLMAN=false`, to use an existing external Spoolman instead |
| `services.openviking_url` | `PRINT_BUDDY__SERVICES__OPENVIKING_URL` | empty | Optional OpenViking memory store |
| `services.vision_chat_url` | `PRINT_BUDDY__SERVICES__VISION_CHAT_URL` | empty | OpenAI-compatible endpoint for camera checks and roasts; empty disables both |
| `services.stock_api_port` | `PRINT_BUDDY__SERVICES__STOCK_API_PORT` | `8898` | Flashforge stock API port for IFS presence |
| `services.octoprint_url` | `PRINT_BUDDY__SERVICES__OCTOPRINT_URL` | empty | OctoPrint printers (`octoprint.marlin`): OctoPrint URL. API key: `OCTOPRINT_API_KEY` secret |
| `discord.chat_id` | `PRINT_BUDDY__DISCORD__CHAT_ID` | empty | Discord channel ID |
| `discord.approval_user_id` | `PRINT_BUDDY__DISCORD__APPROVAL_USER_ID` | empty | Discord user ID allowed to approve |
| `discord.upload_max_bytes` | `PRINT_BUDDY__DISCORD__UPLOAD_MAX_BYTES` | `9500000` | Largest upload per file on Discord: video is shrunk to it, and a sliced file or Bambu package over it is reported with its host path instead of offered for sending (see [PRINTER-PROFILES.md](PRINTER-PROFILES.md)). Keep it under your server's Discord cap (10 MB unboosted). This row governs Discord only — Telegram and Matrix posts are sized to their own `upload_max_bytes` rows below |
| `discord.post_print_quiet_s` | `PRINT_BUDDY__DISCORD__POST_PRINT_QUIET_S` | `7200` | Quiet time before a chat session resets |
| `discord.daily_reset_hour` | `PRINT_BUDDY__DISCORD__DAILY_RESET_HOUR` | `4` | Hour of the daily session reset |
| `discord.timezone` | `PRINT_BUDDY__DISCORD__TIMEZONE` | `America/New_York` | Display and reset time zone (IANA name) |
| `discord.bot_name` | `PRINT_BUDDY__DISCORD__BOT_NAME` | `Print Buddy` | Name the bot uses for itself |
| `discord.question_timeout_s` | `PRINT_BUDDY__DISCORD__QUESTION_TIMEOUT_S` | `1800` | How long a Discord question waits for a button |
| `discord.safety_confirm_timeout_s` | `PRINT_BUDDY__DISCORD__SAFETY_CONFIRM_TIMEOUT_S` | `600` | How long a safety confirmation waits |
| `discord.upload_wait_s` | `PRINT_BUDDY__DISCORD__UPLOAD_WAIT_S` | `3600` | How long an upload-wait freeze stays active |
| `discord.cold_pull_outcome_s` | `PRINT_BUDDY__DISCORD__COLD_PULL_OUTCOME_S` | `1800` | How long a cold-pull outcome prompt stays open |
| `discord.token_env` | `PRINT_BUDDY__DISCORD__TOKEN_ENV` | `DISCORD_BOT_TOKEN` | Name of the environment variable holding the bot token |
| `discord.allowed_user_ids` | `PRINT_BUDDY__DISCORD__ALLOWED_USER_IDS` | empty | Discord user IDs allowed to use the standalone bot, comma or space separated |
| `telegram.token_env` | `PRINT_BUDDY__TELEGRAM__TOKEN_ENV` | `TELEGRAM_BOT_TOKEN` | Name of the environment variable holding the Telegram bot token |
| `telegram.chat_id` | `PRINT_BUDDY__TELEGRAM__CHAT_ID` | empty | Telegram chat (group) ID; group and channel IDs are negative |
| `telegram.allowed_user_ids` | `PRINT_BUDDY__TELEGRAM__ALLOWED_USER_IDS` | empty | Telegram user IDs allowed to use the standalone bot, comma or space separated |
| `telegram.approval_user_id` | `PRINT_BUDDY__TELEGRAM__APPROVAL_USER_ID` | empty | Telegram user ID allowed to approve |
| `telegram.upload_max_bytes` | `PRINT_BUDDY__TELEGRAM__UPLOAD_MAX_BYTES` | `50000000` | Largest file the Telegram bot uploads (the Bot API cloud limit); timelapse video is shrunk to this value, not to Discord's smaller cap |
| `matrix.homeserver_url` | `PRINT_BUDDY__MATRIX__HOMESERVER_URL` | empty | Matrix homeserver base URL, for example `https://matrix.org` or a self-hosted server |
| `matrix.access_token_env` | `PRINT_BUDDY__MATRIX__ACCESS_TOKEN_ENV` | `MATRIX_ACCESS_TOKEN` | Name of the environment variable holding the Matrix access token |
| `matrix.room_id` | `PRINT_BUDDY__MATRIX__ROOM_ID` | empty | Matrix room ID of the print room (starts with `!`); the room must be unencrypted |
| `matrix.allowed_user_ids` | `PRINT_BUDDY__MATRIX__ALLOWED_USER_IDS` | empty | Matrix user IDs allowed to use the standalone bot, full `@user:server` form, comma or space separated |
| `matrix.approval_user_id` | `PRINT_BUDDY__MATRIX__APPROVAL_USER_ID` | empty | Matrix user ID allowed to approve |
| `matrix.bot_user_id` | `PRINT_BUDDY__MATRIX__BOT_USER_ID` | empty | The bot's own Matrix user ID; empty asks the homeserver (whoami) at startup |
| `matrix.upload_max_bytes` | `PRINT_BUDDY__MATRIX__UPLOAD_MAX_BYTES` | `50000000` | Largest file the Matrix bot uploads; lowered to the homeserver's media limit when the server reports a smaller one. Timelapse video is shrunk to that resulting limit; if even the smallest shrink cannot fit it, the completion post says the timelapse was recorded but is too large for the server instead of attaching the video |
| `bot.mode` | `PRINT_BUDDY__BOT__MODE` | `hermes`; `standalone` in the image | `hermes` or `standalone`; the image and Compose set `standalone` |
| `bot.platform` | `PRINT_BUDDY__BOT__PLATFORM` | `discord` | Chat platform for the standalone bot (#164): `discord`, `telegram` or `matrix` |
| `bot.health_port` | `PRINT_BUDDY__BOT__HEALTH_PORT` | `0` | Serve `GET /healthz` on this port; `0` turns the HTTP check off |
| `bot.health_stale_s` | `PRINT_BUDDY__BOT__HEALTH_STALE_S` | `120` | Bot health fails when its heartbeat is older than this |
| `bot.sync_commands` | `PRINT_BUDDY__BOT__SYNC_COMMANDS` | `true` | Register the slash commands with Discord at startup |
| `llm.chat_url` | `PRINT_BUDDY__LLM__CHAT_URL` | empty | Optional OpenAI-compatible chat URL; empty: unmatched text gets the command list |
| `llm.model` | `PRINT_BUDDY__LLM__MODEL` | empty | LLM model name, required when `chat_url` is set |
| `llm.api_key_env` | `PRINT_BUDDY__LLM__API_KEY_ENV` | `LLM_API_KEY` | Name of the environment variable holding the LLM API key |
| `llm.timeout_s` | `PRINT_BUDDY__LLM__TIMEOUT_S` | `20` | LLM request timeout |
| `listener.tick_s` | `PRINT_BUDDY__LISTENER__TICK_S` | `600` | Listener housekeeping interval |
| `listener.ifs_presence_poll_s` | `PRINT_BUDDY__LISTENER__IFS_PRESENCE_POLL_S` | `15` | IFS spool presence poll |
| `listener.spool_nag_s` | `PRINT_BUDDY__LISTENER__SPOOL_NAG_S` | `600` | Reminder interval for an unanswered spool question |
| `listener.start_claim_ttl_s` | `PRINT_BUDDY__LISTENER__START_CLAIM_TTL_S` | `1800` | How long a start button stays claimed |
| `vision.model` | `PRINT_BUDDY__VISION__MODEL` | `gemini-latest` | Model for camera checks |
| `vision.roast_model` | `PRINT_BUDDY__VISION__ROAST_MODEL` | `luna-latest` | Model for the print-start roast |
| `vision.roast_enabled` | `PRINT_BUDDY__VISION__ROAST_ENABLED` | `true` | The one-line roast on print-started and print-complete posts, on every platform (Telegram included). On by default: it runs whenever an LLM/vision endpoint is available (`services.vision_chat_url` plus `CLIPROXY_API_KEY`); `false` turns roasts off without disabling camera checks |
| `visual_watch.sensitivity` | `PRINT_BUDDY__VISUAL_WATCH__SENSITIVITY` | `3` | Camera watchdog sensitivity, 1 (quietest) to 5 (most alerts); also sets the periodic check interval and stall threshold, see the [project reference](PROJECT-REFERENCE.md#camera-stall-sensitivity) |
| `visual_watch.enabled` | `PRINT_BUDDY__VISUAL_WATCH__ENABLED` | `true` | Camera monitoring switch; the watchdog is alert-only and never controls the printer |
| `timelapse.mode` | `PRINT_BUDDY__TIMELAPSE__MODE` | derived | Timelapse mode (#246/#295): `rendered` (the printer renders it, moonraker-timelapse), `container` (in-container capture) or `off`. Empty in a file derives: `rendered` when a Moonraker URL is configured, else `off` |
| `timelapse.encoder` | `PRINT_BUDDY__TIMELAPSE__ENCODER` | `cpu` | ffmpeg encoder for the timelapse sizing shrink (#314): `cpu` (libx264), `vaapi`, `qsv` or `nvenc`. Hardware choices need the GPU passed through to the container (see [DOCKER.md](DOCKER.md)); a hardware encode that fails falls back to `cpu` automatically, so a completion post is never lost to the encoder |
| `timelapse.archive_host` | `PRINT_BUDDY__TIMELAPSE__ARCHIVE_HOST` | empty | SSH host for the timelapse archive; empty disables it |
| `timelapse.archive_dir` | `PRINT_BUDDY__TIMELAPSE__ARCHIVE_DIR` | empty | Archive folder on that host |
| `timelapse.ssh_key` | `PRINT_BUDDY__TIMELAPSE__SSH_KEY` | empty | Path of the SSH key in the container (mount it read-only) |
| `timelapse.render_wait_s` | `PRINT_BUDDY__TIMELAPSE__RENDER_WAIT_S` | `900` | Wait for the printer to render the timelapse |
| `timelapse.render_poll_s` | `PRINT_BUDDY__TIMELAPSE__RENDER_POLL_S` | `10` | Poll interval while waiting |
| `timelapse.max_bytes` | `PRINT_BUDDY__TIMELAPSE__MAX_BYTES` | `209715200` | Largest timelapse kept |
| `timelapse.local_retention_days` | `PRINT_BUDDY__TIMELAPSE__LOCAL_RETENTION_DAYS` | `1` | Local copy retention |
| `timelapse.plan_clip_retention_days` | `PRINT_BUDDY__TIMELAPSE__PLAN_CLIP_RETENTION_DAYS` | `14` | Plan clip retention |
| `timelapse.vertical_short` | `PRINT_BUDDY__TIMELAPSE__VERTICAL_SHORT` | `false` | Also post a 9:16 vertical version of each finished timelapse (#317), alongside the timelapse itself |
| `timelapse.vertical_short_mode` | `PRINT_BUDDY__TIMELAPSE__VERTICAL_SHORT_MODE` | `pad` | `pad` fills the 9:16 frame with a blurred background; `crop` centre-crops |
| `timelapse.vertical_short_overlay` | `PRINT_BUDDY__TIMELAPSE__VERTICAL_SHORT_OVERLAY` | `true` | Burn the print title / printer / filament / time overlay into the vertical short |
| `timelapse.capture_enabled` | `PRINT_BUDDY__TIMELAPSE__CAPTURE_ENABLED` | `false` | In-container timelapse capture (#246): starts the bundled go2rtc (full Docker image only) to normalise the camera source on loopback. Off keeps today's printer-rendered behaviour |
| `timelapse.capture_source_url` | `PRINT_BUDDY__TIMELAPSE__CAPTURE_SOURCE_URL` | empty | Explicit capture camera source (MJPEG/RTSP URL or a go2rtc `ffmpeg:` source). Empty derives it from `services.camera_snapshot_url` / the Moonraker webcam |
| `timelapse.capture_trigger` | `PRINT_BUDDY__TIMELAPSE__CAPTURE_TRIGGER` | `interval` | Stage 2 frame capture trigger (#246): `interval` (a frame every `capture_interval_s`), `layer` (a frame on each Moonraker layer change) or `both` |
| `timelapse.capture_interval_s` | `PRINT_BUDDY__TIMELAPSE__CAPTURE_INTERVAL_S` | `5.0` | Seconds between captured frames for the interval trigger (above 0, at most 3600) |
| `timelapse.capture_max_frames` | `PRINT_BUDDY__TIMELAPSE__CAPTURE_MAX_FRAMES` | `3600` | Per-job cap on captured frames; capture stops at the cap and keeps the frames already taken. `0` disables the cap |
| `timelapse.capture_max_bytes` | `PRINT_BUDDY__TIMELAPSE__CAPTURE_MAX_BYTES` | `536870912` | Per-job cap on captured frame bytes; capture stops at the cap and keeps the frames already taken. `0` disables the cap |
| `timelapse.capture_encoder` | `PRINT_BUDDY__TIMELAPSE__CAPTURE_ENCODER` | `auto` | Encoder preference for the Stage 3 encode (#246): `auto`, `vaapi`, `nvenc`, `qsv` or `cpu`. Capture itself never encodes; the value is recorded now so Stage 3 needs no settings change |
| `webui.enabled` | `PRINT_BUDDY__WEBUI__ENABLED` | `false` | Optional Web UI (#286) switch; off by default, and nothing listens while disabled |
| `webui.host` | `PRINT_BUDDY__WEBUI__HOST` | `127.0.0.1` | Host the Web UI binds to when enabled; a plain IP address or hostname |
| `webui.port` | `PRINT_BUDDY__WEBUI__PORT` | `0` | Port the Web UI binds to when enabled; `0` means no port has been chosen yet |
| `webui.access_token_env` | `PRINT_BUDDY__WEBUI__ACCESS_TOKEN_ENV` | `WEBUI_ACCESS_TOKEN` | Name of the environment variable holding the optional Web UI access token; the token itself is never a setting |
| `live_stream.enabled` | `PRINT_BUDDY__LIVE_STREAM__ENABLED` | `false` | Live camera viewing in Discord (#311) switch; off by default, and `/print-live` only reports that while disabled |
| `live_stream.voice_channel_id` | `PRINT_BUDDY__LIVE_STREAM__VOICE_CHANNEL_ID` | empty | The one Discord voice channel the live Activity is launched in; the bot never names another channel. Keep it a private channel (see DISCORD-BOT-SETUP.md) |
| `live_stream.auto_start_on_print` | `PRINT_BUDDY__LIVE_STREAM__AUTO_START_ON_PRINT` | `false` | Offer the live view automatically when a print starts; the viewing session itself still starts only from Discord |
| `live_stream.max_height` | `PRINT_BUDDY__LIVE_STREAM__MAX_HEIGHT` | `720` | Live feed height cap in pixels (144-2160); width follows the camera's aspect |
| `live_stream.fps` | `PRINT_BUDDY__LIVE_STREAM__FPS` | `15` | Live feed frame-rate cap (1-60) |
| `live_stream.max_bitrate_kbps` | `PRINT_BUDDY__LIVE_STREAM__MAX_BITRATE_KBPS` | `2500` | Live feed bitrate cap in kbit/s (100-20000) |
| `live_stream.encoder` | `PRINT_BUDDY__LIVE_STREAM__ENCODER` | `auto` | Encoder preference for the live feed: `auto`, `vaapi`, `qsv`, `nvenc` or `cpu` (the plan in `print_buddy/live_stream.py`) |
| `live_stream.empty_timeout_s` | `PRINT_BUDDY__LIVE_STREAM__EMPTY_TIMEOUT_S` | `300` | Seconds the voice channel may stay empty of viewers before the live session ends itself |
| `live_stream.activity_origin` | `PRINT_BUDDY__LIVE_STREAM__ACTIVITY_ORIGIN` | empty | Public https origin the Discord Activity page is served from; how it is reached (URL mapping, tunnel) is deployment wiring (#311 stage 4), empty until deployed |
| `logging.level` | `PRINT_BUDDY__LOGGING__LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `logging.format` | `PRINT_BUDDY__LOGGING__FORMAT` | `text` | `text` (one readable line per event) or `json` (one JSON object per line) |
| `logging.file` | `PRINT_BUDDY__LOGGING__FILE` | empty | Also write a rotating log file (5 MiB, 3 backups) at this path, for example under `/data/hermes/logs`; empty logs to stderr only |
| `maintenance.quick_hours` | `PRINT_BUDDY__MAINTENANCE__QUICK_HOURS` | `25` | Quick maintenance due after these print hours |
| `maintenance.full_hours` | `PRINT_BUDDY__MAINTENANCE__FULL_HOURS` | `75` | Full maintenance due after these print hours |
| `maintenance.full_days` | `PRINT_BUDDY__MAINTENANCE__FULL_DAYS` | `30` | Full maintenance due after these days |
| `nozzle_temp_offsets.<type>` | `PRINT_BUDDY__NOZZLE_TEMP_OFFSETS__<TYPE>` | `0.0` | Temperature offset, −10 to +15 °C, for `brass`, `hardened_steel`, `stainless_steel`, `ruby`, `tungsten_carbide`, `diamond` |
| `material_temps.<MATERIAL>` | file only | see `config/home.yaml` | `{nozzle, bed}` fallback temperatures for PLA, PETG, ABS, ASA, TPU, PA, PC; Spoolman filament values win |
| `cold_pull.<profile>` | file only | from the vendor profile *model* | Hot and cold cold-pull temperatures; profile names are yours |

## Printers list

By default Print Buddy runs one printer, described by the `[printer]`, `[services]`, `[bambu]`, `[prusa]`, `[elegoo_sdcp]` and `[flashforge_stock]` settings above. A config file may instead declare a **list of printers** — `printers:` in YAML, `[[printers]]` in TOML — one entry per printer, each carrying its own connection keys (#333; design: [MULTI-PRINTER-DESIGN.md](MULTI-PRINTER-DESIGN.md)). The list itself is file only: it cannot come from the environment.

The **first entry is the default printer**: the legacy single-printer settings are populated from it, so everything that reads `[printer]`, the `[services]` URLs or a vendor section sees the first entry. When a list is declared, the legacy per-printer locations must be absent or empty in the same file and in the environment — setting both is refused at startup, with the offending locations named. A config with no list behaves exactly as before: loading synthesises a one-entry roster from the legacy settings, its `id` the slug of `printer.name` (or `printer` when there is no name).

Each entry is validated against its own model with the same rules as the legacy sections: a Bambu entry may not carry a Moonraker URL, `lan_host` and `lan_serial` come as a pair, a `host` belongs only to Elegoo SDCP and stock Flashforge entries, and so on. Two entries may not share an `id`, and two entries may not claim the same `chat_id` (an entry without one falls back to `discord.chat_id`).

Scalar keys of a *declared* entry can be overridden from the environment with the indexed spelling `PRINT_BUDDY__PRINTERS__<ID>__<KEY>` — the entry's `id` uppercased in the `<ID>` position, the key in the `<KEY>` position. The environment can never create an entry, and `id` and `model` cannot be overridden: they are the entry's identity in the file.

Each printer's runtime state lives in its own folder, `state/printers/<id>/` under the profile's state directory (#334): its hardware record (`printer_hardware.json`), its launch database (`jobs.db` — the print lease and consumed bed-clear approvals), and its maintenance record (`maintenance.json`). Job folders stay in the shared archive; a job's `JOB.json` records the `printer_id` it belongs to. On the first start after upgrading, the default printer adopts the previous root-level state files — a held lease and the hardware record carry over intact, new writes go to the per-printer folder, and the old files are left in place for one release so a rollback still finds them.

**Channel routing (#335).** Each printer is driven from its own channel. An entry's `chat_id` is that printer's channel on whichever platform the bot runs — a Discord channel ID, a Telegram chat ID, or a Matrix room ID — and an entry without one uses the platform's global chat (`discord.chat_id`, `telegram.chat_id` or `matrix.room_id`), which is therefore the default printer's channel unless the default entry sets its own. A message, command or button press in a printer's channel is handled for that printer end to end: intake stamps the job with that printer, status, stop, resume, spool, macro and maintenance commands read and act on that printer, and its prompts are answered only in its own channel. A channel no printer claims gets silence — there is no fallback to the default printer for unmapped channels, because an approval button carries no typed target: the channel *is* the target, and the default printer is named in output wherever a refusal or listing stands in for it. Two entries claiming one channel refuse startup with the channel and both printers named (the settings load already refuses the Discord case; the bot re-checks for the platform it runs). Delivery methods stay global in v1; they are not per-printer.

**Listeners (#336).** Every printer whose connection needs the Moonraker listener gets its own listener instance — one child process per printer under the Docker supervisor, one runner per printer in the native service — started with that printer's per-printer view: its Moonraker URL, its state folder, its spool and its camera. A listener that dies is restarted on its own backoff and never takes the bot or a sibling listener down; the aggregated health covers every listener, and both the bot status reply and the Web UI status page report each one.

**Setting a roster up (#337).** The CLI setup wizard asks "Add another printer?" after the first printer and writes the roster for you, and the in-chat guided setup offers the same at its review step (reply `add`). Both refuse to guess at a config they cannot rewrite faithfully: the wizard only rewrites an existing `config/local.yaml` it can parse and re-emit unchanged-in-meaning, and leaves an un-round-trippable file byte-for-byte untouched with instructions instead. The Web UI does not edit the roster in this version — its field catalog addresses global fields only — but the status page lists the roster read-only (id, model, connection, channel), and `/api/status` carries the same rows under `printers`.

| YAML key | Environment variable | Docker value | What it does |
|---|---|---|---|
| `printers.id` | file only | — | Required. The printer's stable identity: a slug of `a-z`, `0-9`, `-` and `_` starting with a letter or digit, unique in the list. Renaming an `id` makes it a different printer as far as its state is concerned |
| `printers.model` | file only | — | Required. A registry model key, spelled exactly as `printer.model` |
| `printers.name` | `PRINT_BUDDY__PRINTERS__<ID>__NAME` | — | Display name for this printer; defaults to the name the model's own defaults give `printer.name` |
| `printers.chat_id` | `PRINT_BUDDY__PRINTERS__<ID>__CHAT_ID` | — | This printer's channel on the platform the bot runs (Discord channel ID, Telegram chat ID, or Matrix room ID); empty falls back to that platform's global chat. Two entries may not claim the same channel |
| `printers.moonraker_url` | `PRINT_BUDDY__PRINTERS__<ID>__MOONRAKER_URL` | — | This entry's `services.moonraker_url`; must be empty for offline, Bambu LAN, stock Flashforge, PrusaLink and SDCP models |
| `printers.moonraker_ws_url` | `PRINT_BUDDY__PRINTERS__<ID>__MOONRAKER_WS_URL` | — | This entry's `services.moonraker_ws_url`; derived from `moonraker_url` when empty |
| `printers.octoprint_url` | `PRINT_BUDDY__PRINTERS__<ID>__OCTOPRINT_URL` | — | This entry's `services.octoprint_url`, for OctoPrint models |
| `printers.camera_snapshot_url` | `PRINT_BUDDY__PRINTERS__<ID>__CAMERA_SNAPSHOT_URL` | — | This entry's `services.camera_snapshot_url`; derived from `moonraker_url` when empty |
| `printers.lan_host` | `PRINT_BUDDY__PRINTERS__<ID>__LAN_HOST` | — | This entry's `bambu.lan_host` (Bambu Lab models only); set together with `lan_serial` |
| `printers.lan_serial` | `PRINT_BUDDY__PRINTERS__<ID>__LAN_SERIAL` | — | This entry's `bambu.lan_serial` (Bambu Lab models only); set together with `lan_host` |
| `printers.lan_access_code_env` | `PRINT_BUDDY__PRINTERS__<ID>__LAN_ACCESS_CODE_ENV` | — | This entry's `bambu.lan_access_code_env`: the environment variable holding the printer's LAN access code |
| `printers.start_confirm_s` | `PRINT_BUDDY__PRINTERS__<ID>__START_CONFIRM_S` | — | This entry's `bambu.start_confirm_s` |
| `printers.link_host` | `PRINT_BUDDY__PRINTERS__<ID>__LINK_HOST` | — | This entry's `prusa.link_host` (Prusa models only) |
| `printers.api_key_env` | `PRINT_BUDDY__PRINTERS__<ID>__API_KEY_ENV` | — | This entry's `prusa.api_key_env`: the environment variable holding the PrusaLink API key |
| `printers.host` | `PRINT_BUDDY__PRINTERS__<ID>__HOST` | — | This entry's `elegoo_sdcp.host` or `flashforge_stock.host`, chosen by the entry's model; no other model takes a `host` |
| `printers.nozzle_type` | `PRINT_BUDDY__PRINTERS__<ID>__NOZZLE_TYPE` | — | This entry's `printer.nozzle_type` override, limited to the model's supported types |
| `printers.tool_count` | `PRINT_BUDDY__PRINTERS__<ID>__TOOL_COUNT` | — | This entry's `printer.tool_count` override, for multi-tool models |

## Compose variables

These configure the Compose deployment, not Print Buddy itself. Set them in `.env`.

| Variable | Default | What it does |
|---|---|---|
| `PRINT_BUDDY_IMAGE` | none, required | Image the combined container runs: a locally built tag or a tested immutable digest. No published image exists yet |
| `PRINT_BUDDY_DATA` | `./data` | Host folder holding the `hermes`, `archive`, `records` and `cache` volumes |
| `PRINT_BUDDY_SPOOLMAN_DATA` | `./data/spoolman` | Host folder for the bundled Spoolman database, config, logs and backups |
| `PRINT_BUDDY_CONFIG` | `/app/config/docker.yaml` | Settings file Print Buddy reads (YAML, or legacy `.toml`) |
| `TZ` | `UTC` | Container timezone (IANA name), used by the bundled Spoolman; Print Buddy itself uses `discord.timezone` |

## Runtime environment

| Variable | Default | What it does |
|---|---|---|
| `PRINT_BUDDY_ORCA_CHANNEL` | `stable` | Selects the bundled stable or alpha OrcaSlicer at startup; invalid values stop the container |
| `PRINT_BUDDY_BUNDLED_SPOOLMAN` | `true` | `true` runs the bundled Spoolman API; `false` uses `services.spoolman_url` only |
| `SPOOLMAN_HOST` | `127.0.0.1` | Bundled Spoolman bind address; widen it only together with an approved port mapping, see docs/DOCKER.md |

`WITH_ORCA=false` (default) omits both Orca channels; slicing fails closed without either binary.

## Build arguments

Image build inputs (`docker build --build-arg NAME=value`), not runtime settings. `PRINT_BUDDY_ORCA_CHANNEL` is a runtime environment variable (default `stable`, accepts `alpha`) and requires an image built with `WITH_ORCA=true`.

| Argument | Default | What it does |
|---|---|---|
| `APP_CHANNEL` | `development` | Application provenance label, `stable` or `development`; it does not change the source checkout |
| `WITH_ORCA` | `false` | `true` installs the pinned official prebuilt OrcaSlicer release on both channels (stable and alpha both pin v2.5.0-alpha since #356, each SHA256 verified in `docker/orca-prebuilt.sh`); OrcaSlicer is never built from source; `false` omits it and slicing fails closed |
| `WITH_GO2RTC` | `true` | `true` installs the pinned official go2rtc prebuilt (v1.9.15, SHA256 verified in `docker/go2rtc-prebuilt.sh`) and the VAAPI driver stack for in-container timelapse capture (#246); the published images set it; `false` omits both |
| `SPOOLMAN_REF` | `bed3f14ee77a3a571d31b14215d54b0b88a7519c` | Pinned Spoolman v0.27.0 source commit; only its Python API backend is installed, never the web UI |
| `ORCA_BUILD_JOBS` | `auto` | Bambu Studio source build only: parallel compile jobs, `auto` (memory-aware, below the CPU count) or a whole number from 1 to 64 |
| `ORCA_BUILD_MEM_PER_JOB_MIB` | `2560` | Bambu Studio source build only: memory budgeted per job by `auto`, at least 256 |
| `ORCA_CCACHE_MAXSIZE` | `5G` | Bambu Studio source build only: size cap of the compiler cache inside the build cache |
| `WITH_BAMBU` | `false` | `true` builds Bambu Studio from pinned source into `/usr/bin/bambu-studio`; `false` omits it and Bambu Lab slicing fails closed |
| `BAMBU_REF` | `926a7192574bcb9b3a732e1ec59a46d79cb45466` | Pinned Bambu Studio 2.8.2 source commit |
| `BAMBU_BUILD_PROFILE` | `release-static-fhs` | Names the Bambu Studio build options; rename it to reset the build trees |

## Secrets

Secrets come from the environment only (Docker: `.env`, never committed or shared), never from YAML or the image.

| Variable | Used for |
|---|---|
| `DISCORD_BOT_TOKEN` | Standalone bot token. The variable name is `discord.token_env` |
| `TELEGRAM_BOT_TOKEN` | Telegram standalone bot token. The variable name is `telegram.token_env` |
| `MATRIX_ACCESS_TOKEN` | Matrix standalone bot access token. The variable name is `matrix.access_token_env` |
| `WEBUI_ACCESS_TOKEN` | Optional Web UI (#286) access token, required when it binds beyond loopback. The variable name is `webui.access_token_env` |
| `LLM_API_KEY` | Optional key for `llm.chat_url`. The variable name is `llm.api_key_env` |
| `OCTOPRINT_API_KEY` | `octoprint.marlin` printers: OctoPrint application key |
| `BAMBU_LAN_PASSWORD` | Bambu Lab printers: the LAN access code for read-only status. The variable name is `bambu.lan_access_code_env` |
| `MOONRAKER_API_KEY` | Moonraker API key, only when Moonraker requires one |
| `CLIPROXY_API_KEY` | Key for `services.vision_chat_url` |
| `OPENVIKING_API_KEY` | Key for `services.openviking_url` |
| `AD5X_SERIAL` | Stock Flashforge printers: the printer serial number for the stock LAN API. Never a setting; set it together with `flashforge_stock.host` |
| `AD5X_CHECK_CODE` | Stock Flashforge printers: the printer check code for the stock LAN API. Never a setting |

The MakerWorld account token is not an environment variable. It is the file `~/.config/bambu/token` (Docker: `/data/.config/bambu/token`), needed only for MakerWorld links; see [MakerWorld account token](PROJECT-REFERENCE.md#makerworld-account-token).

## Legacy environment names

The names below predate `PRINT_BUDDY__SECTION__KEY` and still work; new installs should use the long form. The full map is `LEGACY_ENV` in `print_buddy/settings.py`, for example `MOONRAKER_URL` → `services.moonraker_url`, `SPOOLMAN_URL` → `services.spoolman_url`, `PRINT_DISCORD_CHAT_ID` → `discord.chat_id`.
