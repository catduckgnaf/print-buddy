"""One command router for both runtimes: the print-feedback plugin's own handlers, in its own order.

The plugin's ``register(ctx)`` is what the Hermes gateway calls. The router calls it too, with itself
as the context, so the standalone bot and Hermes run the same handler list and the plugin stays the
single place a handler is added. Agent-only hooks (tool-call guards, the pre-agent receipt) are kept
but not run, since no agent follows a standalone message.
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
import sys

from .. import settings

logger = logging.getLogger(__name__)

PLUGIN = settings.ROOT / "plugins" / "print-feedback" / "__init__.py"
MODULE_NAME = "print_handy_print_feedback"
# receive_ack promises the agent will follow up ("Checking the requested action..."). Standalone has no agent.
# stray_chat_dispatch is the transitional in-process claim hook (#524 stage 3): BotCore's own
# fallback answers the same text in this process, with the same lanes and texts.
AGENT_ONLY_DISPATCH = {"receive_ack", "stray_chat_dispatch"}


def load_plugin(path=PLUGIN, name=MODULE_NAME):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


class Router:
    """Collects the plugin's hooks through its register() and runs the dispatch hooks in order."""

    def __init__(self, plugin=None):
        self.plugin = plugin if plugin is not None else load_plugin()
        self.hooks: dict[str, list] = {}
        self.platform_handlers: dict[str, list] = {}
        self.plugin.register(self)

    # The plugin context API (the subset Print Handy's plugin uses).
    def register_hook(self, name, func):
        self.hooks.setdefault(name, []).append(func)

    def register_platform_handler(self, platform, func):
        self.platform_handlers.setdefault(platform, []).append(func)

    @property
    def dispatch_hooks(self):
        return [h for h in self.hooks.get("pre_gateway_dispatch", [])
                if getattr(h, "__name__", "") not in AGENT_ONLY_DISPATCH]

    def handler_names(self):
        return [getattr(h, "__name__", repr(h)) for h in self.dispatch_hooks]

    def attach_platform(self, platform, client, adapter):
        """Run the plugin's platform handlers (alert, insertion and plate buttons) against our client."""
        for func in self.platform_handlers.get(platform, []):
            func(client, adapter)

    async def dispatch(self, event, gateway):
        """The first hook that answers wins, as in the gateway. None: no handler took the message."""
        for hook in self.dispatch_hooks:
            try:
                result = hook(event, gateway)
                if inspect.isawaitable(result):
                    result = await result
            except Exception:
                logger.exception("handler %s failed", getattr(hook, "__name__", hook))
                return {"action": "skip", "reason": f"{getattr(hook, '__name__', 'handler')} failed"}
            if result is not None:
                return result
        return None
