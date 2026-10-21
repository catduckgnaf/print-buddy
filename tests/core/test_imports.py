"""Every core module imports as part of the package. Catches flat sibling imports."""
import importlib
import trimesh
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2] / "print_buddy" / "core"
THIRD_PARTY = {"numpy", "PIL", "trimesh"}


class ImportTests(unittest.TestCase):
    def test_every_core_module_imports(self):
        for path in sorted(CORE.glob("*.py")):
            with self.subTest(module=path.stem):
                try:
                    importlib.import_module(f"print_buddy.core.{path.stem}")
                except ModuleNotFoundError as exc:
                    if exc.name in THIRD_PARTY:
                        self.skipTest(f"{exc.name} is not installed")
                    raise
