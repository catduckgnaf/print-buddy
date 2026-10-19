"""scripts/install-hermes.sh against temporary directories. Never touches the real ~/.hermes."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "install-hermes.sh"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "profile"
        self.units = self.tmp / "units"
        self.overlay = self.tmp / "overlay"
        self.fakebin = self.tmp / "bin"
        self.fakebin.mkdir()
        self.log = self.tmp / "systemctl.log"
        systemctl = self.fakebin / "systemctl"
        systemctl.write_text(f'#!/bin/sh\necho "$@" >> "{self.log}"\n')
        systemctl.chmod(systemctl.stat().st_mode | stat.S_IEXEC)

    def run_installer(self, *args, overlay=True):
        env = dict(os.environ,
                   HERMES_HOME=str(self.home), SYSTEMD_USER_DIR=str(self.units),
                   PRINT_BUDDY_OVERLAY=str(self.overlay if overlay else self.tmp / "no-overlay"),
                   PYTHON="/opt/venv/bin/python", HOME=str(self.tmp / "fakehome"),
                   PATH=f"{self.fakebin}:{os.environ['PATH']}",
                   DISCORD_CHANNEL_ID="12345", TIMEZONE="Europe/Paris")
        result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, cwd=self.tmp)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def tree(self):
        return sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*")
                      if self.fakebin not in p.parents and p != self.fakebin and p != self.log)

    def test_dry_run_changes_nothing(self):
        before = self.tree()
        out = self.run_installer("--dry-run")
        self.assertIn("would:", out)
        self.assertEqual(before, self.tree())
        self.assertFalse(self.home.exists())
        self.assertFalse(self.log.exists())

    def test_fresh_install_links_renders_and_installs_units(self):
        self.run_installer()
        skill = self.home / "skills/smart-home/klipper-3d-printing"
        self.assertEqual(ROOT / "hermes/skills/klipper-3d-printing", Path(os.readlink(skill)))
        self.assertTrue((skill / "SKILL.md").is_file())
        plugin = self.home / "plugins/print-feedback"
        self.assertEqual(ROOT / "plugins/print-feedback", Path(os.readlink(plugin)))
        self.assertTrue((plugin / "plugin.yaml").is_file())
        config = (self.home / "config.yaml").read_text()
        self.assertIn("'12345'", config)
        self.assertIn("timezone: Europe/Paris", config)
        self.assertIn(str(self.home), config)
        for name in ("AGENTS.md", "SOUL.md", "MEMORY.md", "profile.yaml", "status_phrases.yaml"):
            self.assertTrue((self.home / name).is_file(), name)
        unit = (self.units / "hermes-print-buddy-listener.service").read_text()
        self.assertIn(f"WorkingDirectory={ROOT}", unit)
        self.assertIn("ExecStart=/opt/venv/bin/python -m print_buddy.hermes.moonraker_event_listener", unit)
        self.assertIn(f"HERMES_HOME={self.home}", unit)
        self.assertNotIn("{{", unit)
        self.assertTrue((self.units / "hermes-print-buddy-listener.service.d/10-restart-with-gateway.conf").is_file())
        self.assertEqual("--user daemon-reload", self.log.read_text().strip())

    def test_second_run_is_idempotent(self):
        self.run_installer()
        self.log.unlink()
        snapshot = self.tree()
        out = self.run_installer()
        self.assertEqual(snapshot, self.tree())
        self.assertFalse(any(".bak-" in path for path in self.tree()))
        self.assertNotIn("backup", out)
        self.assertFalse(self.log.exists(), "no daemon-reload when nothing changed")

    def test_edited_profile_files_are_never_overwritten(self):
        self.run_installer()
        for name in ("AGENTS.md", "SOUL.md", "config.yaml"):
            (self.home / name).write_text(f"my edited {name}\n")
        out = self.run_installer()
        for name in ("AGENTS.md", "SOUL.md", "config.yaml"):
            self.assertEqual(f"my edited {name}\n", (self.home / name).read_text())
            self.assertIn(f"skipped {self.home / name}", out)

    def test_overlay_is_layered_over_profile_and_units(self):
        self.run_installer()
        (self.overlay / "systemd/hermes-print-buddy-listener.service.d").mkdir(parents=True)
        (self.overlay / "SOUL.md").write_text("my private soul\n")
        (self.overlay / "README.md").write_text("not installed\n")
        (self.overlay / ".env").write_text("TOKEN=x\n")
        (self.overlay / "systemd/hermes-print-buddy-listener.service.d/90-local.conf").write_text("[Service]\nEnvironment=X=1\n")
        self.run_installer()
        self.assertEqual("my private soul\n", (self.home / "SOUL.md").read_text())
        self.assertEqual("TOKEN=x\n", (self.home / ".env").read_text())
        self.assertFalse((self.home / "README.md").exists())
        self.assertTrue(list(self.home.glob("SOUL.md.bak-*")), "generic SOUL.md is backed up, not lost")
        self.assertIn("Environment=X=1", (self.units / "hermes-print-buddy-listener.service.d/90-local.conf").read_text())
        before = self.tree()
        self.run_installer()
        self.assertEqual(before, self.tree(), "overlay reapplied without new backups")

    def test_existing_real_directories_are_backed_up_not_deleted(self):
        skill = self.home / "skills/smart-home/klipper-3d-printing"
        skill.mkdir(parents=True)
        (skill / "old.txt").write_text("old copy\n")
        plugin = self.home / "plugins/print-feedback"
        plugin.mkdir(parents=True)
        (plugin / "__init__.py").write_text("# old\n")
        self.run_installer()
        self.assertTrue(skill.is_symlink())
        self.assertTrue(plugin.is_symlink())
        [backup] = list(skill.parent.glob("klipper-3d-printing.bak-*"))
        self.assertEqual("old copy\n", (backup / "old.txt").read_text())
        [backup] = list(plugin.parent.glob("print-feedback.bak-*"))
        self.assertEqual("# old\n", (backup / "__init__.py").read_text())

    def test_stale_symlink_is_repointed(self):
        skill = self.home / "skills/smart-home/klipper-3d-printing"
        skill.parent.mkdir(parents=True)
        skill.symlink_to(self.tmp)
        self.run_installer()
        self.assertEqual(ROOT / "hermes/skills/klipper-3d-printing", Path(os.readlink(skill)))


if __name__ == "__main__":
    unittest.main()
