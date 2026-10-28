"""python3 -m print_handy.bot [run | check | health]

run     start the standalone bot on the [bot] platform (the default). Refuses unless [bot] mode is standalone.
check   validate settings, token, channel, users and handlers offline. Exit 1 on a problem.
health  exit 0 only while a running bot reports a fresh heartbeat with no Hermes loaded.
"""
import logging
import os
import sys
from pathlib import Path

from .. import __version__, logs, settings

logger = logging.getLogger(__name__)


def checks(cfg):
    """[(label, ok, detail)]. Offline: nothing here contacts the chat platform."""
    from ..hermes import _config
    from . import health, llm, platform
    from .runtime import allowed_users, discord_chat_llm_enabled
    rows = []

    def add(label, ok, detail):
        rows.append((label, ok, detail))

    mode = cfg["bot"]["mode"]
    add("mode", mode == "standalone", mode if mode == "standalone" else
        f"{mode}; set PRINT_HANDY__BOT__MODE=standalone (or [bot] mode) to run without Hermes")
    name = str(cfg["bot"].get("platform") or "discord")
    implemented = platform.platform_module(name) is not None
    add("platform", implemented, name if implemented else
        f"{name}; platform {name!r} is not implemented yet (#164) — discord, telegram and matrix are available")
    if mode == "hermes" and name == "discord":
        # #384: in Hermes mode the gateway owns the Discord connection, and an
        # explicit platforms.discord.enabled: false in the profile config
        # silently removes attachment intake — credentials do not override it
        # and the gateway only logs a warning. Name it here, with the remedy.
        state, profile_config = _config.profile_platform_state(
            "discord", path=Path(cfg["paths"]["hermes_home"]) / "config.yaml")
        remedy = (f"set platforms.discord.enabled: true in {profile_config} and restart the Hermes gateway; "
                  "environment credentials do not override an explicit platform disable")
        if state == "disabled":
            add("hermes discord platform", False,
                f"disabled in {profile_config}: platforms.discord.enabled is false, so the gateway never "
                f"connects Discord and attachment intake is silently absent; {remedy}")
        elif state == "enabled":
            add("hermes discord platform", True, f"enabled in {profile_config}")
        elif state == "unset":
            add("hermes discord platform", True,
                f"no explicit platforms.discord.enabled in {profile_config}; the gateway default applies")
        elif state == "missing":
            add("hermes discord platform", True,
                f"no profile config at {profile_config} (not installed; no platform switch to disable)")
        else:
            add("hermes discord platform", False,
                f"cannot read {profile_config} to verify platforms.discord.enabled; "
                "fix or remove it, then re-run scripts/install-hermes.sh")
    if name == "discord":
        token_env = cfg["discord"]["token_env"]
        add("token", bool(_config.discord_token()), f"${token_env} is set" if _config.discord_token()
            else f"${token_env} is empty; put the Discord bot token in that environment variable")
        chat = str(cfg["discord"]["chat_id"] or "")
        add("print channel", chat.isdigit(), chat or "discord.chat_id is empty")
        # Discord access (#386): an empty allow list is a valid mode (the
        # channel is the boundary), never a failure. The row names the mode
        # so a check run states who can use the bot.
        from .platform import describe_access
        from .runtime import denied_users, listed_users
        add("access", True, describe_access(len(allowed_users(cfg)), len(denied_users(cfg)),
                                            not listed_users(cfg)))
    elif name == "telegram":
        from .telegram import telegram_token
        token_env = cfg["telegram"]["token_env"]
        add("token", bool(telegram_token(cfg)), f"${token_env} is set" if telegram_token(cfg)
            else f"${token_env} is empty; put the Telegram bot token in that environment variable")
        chat = str(cfg["telegram"]["chat_id"] or "")
        add("print channel", bool(chat) and chat.lstrip("-").isdigit() and chat != "-",
            chat or "telegram.chat_id is empty")
        users = allowed_users(cfg, "telegram")
        add("allowed users", bool(users), f"{len(users)} user(s)" if users
            else "none: set telegram.allowed_user_ids (or approval_user_id); everyone is refused")
    elif name == "matrix":
        from .matrix import matrix_token
        token_env = cfg["matrix"]["access_token_env"]
        add("token", bool(matrix_token(cfg)), f"${token_env} is set" if matrix_token(cfg)
            else f"${token_env} is empty; put the Matrix access token in that environment variable")
        homeserver = str(cfg["matrix"]["homeserver_url"] or "")
        add("homeserver", homeserver.startswith(("http://", "https://")),
            homeserver or "matrix.homeserver_url is empty")
        room = str(cfg["matrix"]["room_id"] or "")
        add("print room", room.startswith("!"), room or "matrix.room_id is empty")
        users = allowed_users(cfg, "matrix")
        add("allowed users", bool(users), f"{len(users)} user(s)" if users
            else "none: set matrix.allowed_user_ids (or approval_user_id); everyone is refused")
    # Debug log mode (#478): a visible row while a session is on, so a
    # check run never hides that DEBUG capture is running.
    try:
        from .. import debug_mode
        add("debug mode", True, debug_mode.check_row(cfg) or "off")
    except Exception as exc:
        add("debug mode", True, f"could not check: {exc}")
    label, available, detail = platform.library_status(name)
    add(label, available, detail)
    try:
        from .router import Router
        names = Router().handler_names()
        add("handlers", bool(names), f"{len(names)}: {', '.join(names)}")
    except Exception as exc:
        add("handlers", False, f"plugin failed to load: {exc}")
    loaded = health.hermes_modules_loaded()
    add("no hermes", not loaded, "no Hermes module imported" if not loaded else ", ".join(loaded))
    try:
        state = _config.state_dir()
        state.mkdir(parents=True, exist_ok=True)
        probe = state / ".write-test"
        probe.write_text("")
        probe.unlink()
        add("state dir", True, str(state))
    except OSError as exc:
        add("state dir", False, f"not writable: {exc}")
    if name in ("telegram", "matrix"):
        # Telegram and Matrix are pure bots (#164 stages 2-3, #73): the LLM
        # fallback is never wired for them, whatever [llm] says elsewhere.
        add("llm", True, f"off ({name.capitalize()} is a pure bot: no LLM; unmatched messages get the short not-understood reply)")
    elif name == "discord" and not discord_chat_llm_enabled(cfg):
        # Discord's own no-LLM mode (#466): the operator turned the chat LLM
        # off by name, so the row names the switch — [llm] may still be
        # configured for /print-design, which the design row below reports.
        add("llm", True, "off (discord.chat_llm_enabled is false: no chat LLM; "
                         "unmatched messages get the short not-understood reply)")
    else:
        add("llm", True, f"{cfg['llm']['model']} at {cfg['llm']['chat_url']}" if llm.configured(cfg)
            else "off (unmatched messages get the short not-understood reply)")
    # The roast is separate from the chat fallback above: the print-started
    # post gains a one-line roast (exactly one per print, when printing
    # begins; the completion post never does) on every platform (Telegram
    # and Matrix included) whenever [vision] roast_enabled is on — the
    # default — and an LLM/vision endpoint is available.
    vision = cfg.get("vision") or {}
    vision_url = str((cfg.get("services") or {}).get("vision_chat_url") or "")
    if not vision.get("roast_enabled", True):
        add("roast", True, "off (vision.roast_enabled is false)")
    elif vision_url:
        add("roast", True, f"on ({vision.get('roast_model') or 'luna-latest'} at {vision_url}; "
                           "set vision.roast_enabled=false to turn roasts off)")
    else:
        add("roast", True, "on by default, but no LLM/vision endpoint is available "
                           "(services.vision_chat_url is empty); set it to enable roasts")
    # Auto light-off (#516): the listener turns the printer's light on at
    # print start and off again after the camera verdict has seen an empty
    # plate for vision.auto_light_off_minutes. Off by default (0). Like
    # the watchdog it needs a vision endpoint (PRINT_VISION_URL counts);
    # the light target is the named vision.light_object, or the printer's
    # single light object auto-discovered by the listener — bot check is
    # offline, so an unnamed target is reported as unresolved here rather
    # than discovered. The Bambu/SDCP follow-up made the target
    # family-shaped: Bambu's chamber light is a fixed protocol target,
    # SDCP's is its Cmd 403 light, and the remaining families have no
    # light at all — the row names the configured printer's family,
    # resolved from the model in cfg without contacting the printer.
    light_minutes = vision.get("auto_light_off_minutes", 0)
    light_object = str(vision.get("light_object") or "").strip()
    light_connection = None
    try:
        from .. import printers as _printers
        _light_model = _printers.MODELS.get(str((cfg.get("printer") or {}).get("model") or ""))
        if _light_model is not None:
            light_connection = getattr(getattr(_light_model, "vendor", None), "connection", None)
    except Exception:
        light_connection = None
    if not light_minutes:
        add("auto light", True, "off (vision.auto_light_off_minutes is 0; set it, "
                                "e.g. 30, to turn the printer light off after the "
                                "plate has been seen empty that long)")
    elif light_connection == "elegoo_sdcp":
        add("auto light", True, f"on (SDCP chamber light, Cmd 403; light on at print "
                                f"start; auto-off cannot run yet — no SDCP camera "
                                f"source is verified, so the empty-plate check has no "
                                f"frame to judge and the light stays on; set "
                                f"vision.auto_light_off_minutes=0 to turn auto light off)")
    elif light_connection not in (None, "moonraker", "bambulab_lan"):
        add("auto light", True, f"on, but unavailable for this printer: connection "
                                f"{light_connection!r} has no light control (auto "
                                f"light-off covers Moonraker, Bambu Lab and Elegoo "
                                f"SDCP printers); the setting has no effect here")
    elif not vision_url and not os.environ.get("PRINT_VISION_URL"):
        add("auto light", True, "on, but no vision endpoint is available "
                                "(services.vision_chat_url is empty and PRINT_VISION_URL "
                                "is not set); the empty-plate check needs one")
    elif light_connection == "bambulab_lan":
        add("auto light", True, f"on (Bambu chamber light; light off after the plate has been "
                                f"seen empty for {light_minutes} minutes; a model whose own "
                                f"telemetry reports no chamber light is never switched — "
                                f"the listener logs it unavailable; vision.light_object "
                                f"applies to Moonraker printers only; set "
                                f"vision.auto_light_off_minutes=0 to turn auto light off)")
    elif light_object:
        add("auto light", True, f"on ({light_object}; light off after the plate has been "
                                f"seen empty for {light_minutes} minutes; set "
                                f"vision.auto_light_off_minutes=0 to turn auto light off)")
    else:
        add("auto light", True, "on, but no light target is named (vision.light_object "
                                "is empty); the listener auto-discovers only when the "
                                "printer has exactly one light object — set "
                                "vision.light_object to name the target for sure")
    # AI design (#388): tri-state enable — explicit design.enabled=false is
    # off; explicit true is on; unset is auto (on whenever a design/LLM
    # endpoint resolves — the roast posture). When on it needs OpenSCAD (the
    # design engine) and a model: in Hermes mode the profile's
    # auxiliary.print_design task, in standalone mode the [design] endpoint
    # inheriting [llm]. A forced-on-but-unusable design fails the check, like
    # a missing token, so the misconfiguration is visible before a user
    # hits it mid-conversation; auto with no endpoint is a healthy off.
    import shutil as _shutil
    from ..core import design as _design
    design_cfg = cfg.get("design") or {}
    resolved = _design.resolve_http_config(cfg)
    endpoint_available = resolved is not None or mode == "hermes"
    design_mode = _design.mode_name(cfg, endpoint_available=endpoint_available)
    if design_mode == "off":
        add("design", True, "off (design.enabled is false; /print-design and /design are unavailable)")
    elif design_mode == "auto-off":
        add("design", True, "auto-off (no design/LLM endpoint configured; /print-design answers "
                            "'not set up' until one is — set [design] or [llm] chat_url/model)")
    elif not _shutil.which("openscad"):
        add("design", False, "enabled, but openscad is not on PATH; install OpenSCAD "
                             "(it is in the Docker image) or set design.enabled=false")
    elif mode == "hermes":
        add("design", True, f"{design_mode} (Hermes print_design auxiliary task; pin its model in the "
                            "profile's auxiliary.print_design block)")
    elif resolved:
        add("design", True, f"{design_mode} ({resolved['model']} at {resolved['chat_url']})")
    else:
        add("design", False, "enabled, but no model endpoint: set [design] chat_url and "
                             "model, or the [llm] values they inherit")
    return rows


def check(out=None):
    out = out or sys.stdout
    try:
        cfg = settings.current()
    except settings.SettingsError as exc:
        print(f"FAIL  settings: {exc}", file=out)
        return 1
    failed = False
    for label, ok, detail in checks(cfg):
        failed |= not ok
        print(f"{'ok' if ok else 'FAIL':<5} {label}: {detail}", file=out)
    return 1 if failed else 0


def run():
    logs.configure()
    logger.info("standalone bot starting (Print Handy %s)", __version__)
    if check(sys.stderr):
        print("Not starting: fix the FAIL lines above.", file=sys.stderr)
        return 2
    cfg = settings.current()
    name = str(cfg["bot"].get("platform") or "discord")
    if name == "discord":
        from .client import run_bot
        return run_bot(cfg)
    if name == "telegram":
        from .telegram import run_bot
        return run_bot(cfg)
    if name == "matrix":
        from .matrix import run_bot
        return run_bot(cfg)
    print(f"Platform {name!r} is not implemented yet (#164).", file=sys.stderr)  # unreachable while checks report it, kept as a guard
    return 2


def main(argv):
    command = argv[0] if argv else "run"
    if command == "run":
        return run()
    if command == "check":
        return check()
    if command == "health":
        from . import health
        return health.check()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
