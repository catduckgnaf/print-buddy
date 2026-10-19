"""scripts/migrate-names.sh against temporary directories. Never touches a real install."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "migrate-names.sh"
UNIT = "hermes-3dprinting-moonraker-listener.service"


class MigrateNamesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "profile"
        self.archive = self.tmp / "archive"
        self.units = self.tmp / "units"
        self.config = self.tmp / "local.toml"
        (self.home / "state").mkdir(parents=True)
        (self.archive / "job1").mkdir(parents=True)
        (self.units / f"{UNIT}.d").mkdir(parents=True)
        (self.home / "state" / "print_bitch_context.json").write_text("ctx\n")
        (self.home / "state" / "print_bitch_start_claims.json").write_text("old\n")
        (self.home / "state" / "print_buddy_start_claims.json").write_text("new\n")
        (self.archive / "job1" / "print_bitch_note.txt").write_text("note\n")
        (self.home / ".env").write_text("PRINT_BITCH_ARCHIVE=/x\nOTHER=1\n")
        (self.home / "config.yaml").write_text("a: 1\n")
        self.config.write_text("# PRINT_BITCH_CONTEXT_PATH mentioned\n")
        (self.units / UNIT).write_text("[Service]\nEnvironment=PRINT_BITCH_CLEANUP_DRY_RUN=1\n")
        (self.units / f"{UNIT}.d" / "x.conf").write_text("[Service]\nEnvironment=PRINT_BITCH_BOUNDS_CACHE=/y\n")

    def run_script(self, *args):
        result = subprocess.run(
            ["bash", str(SCRIPT), "--hermes-home", str(self.home), "--archive", str(self.archive),
             "--systemd-dir", str(self.units), "--config", str(self.config), *args],
            capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def snapshot(self):
        return {str(p.relative_to(self.tmp)): (p.read_text() if p.is_file() else None)
                for p in sorted(self.tmp.rglob("*"))}

    def test_dry_run_changes_nothing(self):
        before = self.snapshot()
        out = self.run_script("--dry-run")
        self.assertEqual(before, self.snapshot())
        self.assertIn("would: rename", out)
        self.assertIn("would: edit", out)

    def test_migrates_names_and_backs_up(self):
        out = self.run_script()
        state = self.home / "state"
        self.assertEqual("ctx\n", (state / "print_buddy_context.json").read_text())
        self.assertFalse((state / "print_bitch_context.json").exists())
        self.assertEqual("new\n", (state / "print_buddy_start_claims.json").read_text())
        self.assertEqual("old\n", (state / "print_bitch_start_claims.json").read_text())
        self.assertIn("exists", out)
        self.assertTrue((self.archive / "job1" / "print_buddy_note.txt").exists())
        self.assertEqual("PRINT_BUDDY_ARCHIVE=/x\nOTHER=1\n", (self.home / ".env").read_text())
        self.assertEqual("PRINT_BITCH_ARCHIVE=/x\nOTHER=1\n", (self.home / ".env.pre-rename").read_text())
        self.assertIn("PRINT_BUDDY_CONTEXT_PATH", self.config.read_text())
        self.assertIn("PRINT_BUDDY_CLEANUP_DRY_RUN", (self.units / UNIT).read_text())
        self.assertIn("PRINT_BUDDY_BOUNDS_CACHE", (self.units / f"{UNIT}.d" / "x.conf").read_text())
        self.assertFalse((self.home / "config.yaml.pre-rename").exists())
        self.assertIn("FIRMWARE_RESTART", out)

    def test_second_run_is_a_no_op(self):
        self.run_script()
        after_first = self.snapshot()
        self.run_script()
        self.assertEqual(after_first, self.snapshot())

    def test_archive_root_itself_is_never_renamed(self):
        root = self.tmp / "print_bitch_archive"
        (root / "job").mkdir(parents=True)
        (root / "job" / "print_bitch_x.txt").write_text("x\n")
        self.archive = root
        self.run_script()
        self.assertTrue(root.is_dir())
        self.assertTrue((root / "job" / "print_buddy_x.txt").exists())

    def test_printer_steps_configure_the_plugin_before_enabling_it(self):
        out = self.run_script("--dry-run")
        self.assertLess(out.index("user.moonraker.conf"), out.index("ENABLE_PLUGIN name=print-buddy"))


if __name__ == "__main__":
    unittest.main()
