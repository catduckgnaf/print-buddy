"""Shared test helpers for the pipeline tests."""
import pytest

from print_buddy.core import _external


def external(name):
    """Runtime module (print_next, print_records, ...) or skip the calling test module."""
    try:
        return _external.load(name)
    except ModuleNotFoundError:
        pytest.skip(f"runtime module {name} is not installed", allow_module_level=True)
