"""scripts/home-update.sh against throwaway git repos: a good update sticks, a bad one rolls back."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipIf(os.environ.get("PRINT_BUDDY_UPDATE_CHECK"), "already inside an update check")
@unittest.skipUnless(shutil.which("git"), "git is not installed")
class HomeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.upstream, self.home = base / "upstream", base / "home"
        files = git(ROOT, "ls-files", "-co", "--exclude-standard").splitlines()
        for name in files:
            if (ROOT / name).is_file():
                (self.upstream / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, self.upstream / name)
        git(self.upstream, "init", "-q", "-b", "main")
        git(self.upstream, "add", "-A")
        git(self.upstream, "commit", "-qm", "base")
        git(base, "clone", "-q", str(self.upstream), str(self.home))
        # `true --help` exits 0: a stand-in Orca so the doctor passes on machines without flatpak.
        # A profile with a hardware record, so the doctor's checks match a working install.
        profile = base / "profile"
        (profile / "state").mkdir(parents=True)
        (profile / "state" / "printer_hardware.json").write_text(
            '{"spool": {}, "temps_c": {}, "nozzle": {"diameter_mm": 0.4}}')
        (self.home / "config" / "local.toml").write_text(
            f'[printer]\nname = "Home AD5X"\n\n[orca]\ncommand = ["true"]\n\n[paths]\nhermes_home = "{profile}"\n')

    def tearDown(self):
        self.tmp.cleanup()

    def commit_upstream(self, path, text):
        (self.upstream / path).write_text(text)
        git(self.upstream, "add", "-A")
        git(self.upstream, "commit", "-qm", f"change {path}")
        return git(self.upstream, "rev-parse", "HEAD")

    def update(self):
        return subprocess.run(["sh", "scripts/home-update.sh"], cwd=self.home, capture_output=True, text=True)

    def test_good_update_sticks_and_keeps_local_settings(self):
        head = self.commit_upstream("NOTES.txt", "harmless\n")
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(self.home, "rev-parse", "HEAD"), head)
        self.assertIn("Home AD5X", (self.home / "config" / "local.toml").read_text())

    def test_breaking_update_rolls_back(self):
        before = git(self.home, "rev-parse", "HEAD")
        self.commit_upstream("tests/test_broken.py",
                             "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail('broken')\n")
        result = self.update()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Rolled back", result.stdout)
        self.assertEqual(git(self.home, "rev-parse", "HEAD"), before)
        self.assertFalse((self.home / "tests" / "test_broken.py").exists())

    def test_local_edits_to_tracked_files_block_the_update(self):
        self.commit_upstream("NOTES.txt", "harmless\n")
        (self.home / "config" / "home.toml").write_text("# hand edited\n")
        result = self.update()
        self.assertEqual(result.returncode, 1)
        self.assertIn("local edits", result.stdout)
