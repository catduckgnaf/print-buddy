"""Every core module imports as part of the package. Catches flat sibling imports."""
import importlib
from pathlib import Path

CORE = Path(__file__).resolve().parents[2] / "print_buddy" / "core"
THIRD_PARTY = {"numpy", "PIL", "trimesh"}


def test_every_core_module_imports():
    """Import all core modules, collecting only known optional dependency absences."""
    missing = []
    for path in sorted(CORE.glob("*.py")):
        try:
            importlib.import_module(f"print_buddy.core.{path.stem}")
        except ModuleNotFoundError as exc:
            if exc.name not in THIRD_PARTY:
                raise
            missing.append(f"{path.stem}: {exc.name}")
    assert not missing, "core modules unavailable because optional dependencies are missing: " + ", ".join(missing)
