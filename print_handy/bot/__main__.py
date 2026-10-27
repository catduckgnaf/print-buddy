"""python3 -m print_handy.bot [run | check | health]

run     start the standalone bot on the [bot] platform (the default). Refuses unless [bot] mode is standalone.
check   validate settings, token, channel, users and handlers offline. Exit 1 on a problem.
health  exit 0 only while a running bot reports a fresh heartbeat with no Hermes loaded.
"""
import logging
import sys
from pathlib import Path

from .. import logs, settings


def checks(cfg):
    """[(label, ok, detail)]. Offline: nothing here contacts the chat platform."""
    from ..hermes import _config
    from . import health, llm, platform
    from .runtime import allowed_users
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
        add("llm", True, f"off ({name.capitalize()} is a pure bot: no LLM; unmatched messages get the command list)")
    else:
        add("llm", True, f"{cfg['llm']['model']} at {cfg['llm']['chat_url']}" if llm.configured(cfg)
            else "off (unmatched messages get the command list)")
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
