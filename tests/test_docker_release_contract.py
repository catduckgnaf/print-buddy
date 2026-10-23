"""Issue #117 packaging regressions, runnable without a container engine."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DockerReleaseContract(unittest.TestCase):
    def test_standalone_is_default_runtime(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn('"print_buddy.bot"', dockerfile)
        self.assertIn("PRINT_BUDDY__BOT__MODE=standalone", dockerfile)

    def test_docker_examples_use_source_installed_slicer(self):
        for suffix in ("yaml", "toml"):
            with self.subTest(format=suffix):
                config = (ROOT / "config" / f"docker.{suffix}").read_text()
                self.assertIn("/usr/bin/orca-slicer", config)
                self.assertNotIn("/opt/orcaslicer/AppRun", config)

    def test_orca_is_optional_and_built_from_source(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG WITH_ORCA=", dockerfile)
        self.assertIn("ARG ORCA_CHANNEL=", dockerfile)
        self.assertNotIn(".AppImage", dockerfile)
        self.assertIn("cmake --build", dockerfile)


if __name__ == "__main__":
    unittest.main()
