"""Runtime modules that live next to the Hermes profile rather than in the offline core.

print_records, print_control, maintenance, print_next and discord_print_summary are found as
print_handy.hermes.<name> when packaged, otherwise as a top level module on the Hermes path.
"""
import importlib


def load(name):
    last = None
    for qualified in (f"print_handy.hermes.{name}", name):
        try:
            return importlib.import_module(qualified)
        except ModuleNotFoundError as exc:
            if exc.name not in (qualified, name):
                raise
            last = exc
    raise ModuleNotFoundError(f"runtime module {name!r} is not installed", name=name) from last


class _Lazy:
    """Module stand in that imports on first use; attribute reads and writes reach the real module."""

    def __init__(self, name):
        object.__setattr__(self, "_name", name)

    def __getattr__(self, attr):
        return getattr(load(self._name), attr)

    def __setattr__(self, attr, value):
        setattr(load(self._name), attr, value)

    def __delattr__(self, attr):
        delattr(load(self._name), attr)


def lazy(name):
    return _Lazy(name)
