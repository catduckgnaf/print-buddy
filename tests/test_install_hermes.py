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

    def run_installer(self, *args, overlay=True, python="/opt/venv/bin/python"):
        env = dict(os.environ,
                   HERMES_HOME=str(self.home), SYSTEMD_USER_DIR=str(self.units),
                   PRINT_BUDDY_OVERLAY=str(self.overlay if overlay else self.tmp / "no-overlay"),
                   PYTHON=python, HOME=str(self.tmp / "fakehome"),
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
        self.assertIn(str(ROOT), config)
        for name in ("AGENTS.md", "SOUL.md", "MEMORY.md", "profile.yaml", "status_phrases.yaml"):
            self.assertTrue((self.home / name).is_file(), name)
        unit = (self.units / "hermes-3dprinting-moonraker-listener.service").read_text()
        self.assertIn(f"WorkingDirectory={ROOT}", unit)
        self.assertIn("ExecStart=/opt/venv/bin/python -m print_buddy.hermes.moonraker_event_listener", unit)
        self.assertIn(f"HERMES_HOME={self.home}", unit)
        self.assertNotIn("{{", unit)
        self.assertTrue((self.units / "hermes-3dprinting-moonraker-listener.service.d/10-restart-with-gateway.conf").is_file())
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
        (self.overlay / "systemd/hermes-3dprinting-moonraker-listener.service.d").mkdir(parents=True)
        (self.overlay / "SOUL.md").write_text("my private soul\n")
        (self.overlay / "README.md").write_text("not installed\n")
        (self.overlay / ".env").write_text("TOKEN=x\n")
        (self.overlay / "systemd/hermes-3dprinting-moonraker-listener.service.d/90-local.conf").write_text("[Service]\nEnvironment=X=1\n")
        self.run_installer()
        self.assertEqual("my private soul\n", (self.home / "SOUL.md").read_text())
        self.assertEqual("TOKEN=x\n", (self.home / ".env").read_text())
        self.assertFalse((self.home / "README.md").exists())
        [backup] = (self.home / ".install-backups").glob("*/SOUL.md")
        self.assertNotEqual("my private soul\n", backup.read_text(), "generic SOUL.md is backed up, not lost")
        self.assertIn("Environment=X=1", (self.units / "hermes-3dprinting-moonraker-listener.service.d/90-local.conf").read_text())
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
        [backup] = (self.home / ".install-backups").glob("*/skills/smart-home/klipper-3d-printing")
        self.assertEqual("old copy\n", (backup / "old.txt").read_text())
        [backup] = (self.home / ".install-backups").glob("*/plugins/print-feedback")
        self.assertEqual("# old\n", (backup / "__init__.py").read_text())
        self.assertFalse(list(self.home.rglob("*.bak-*")), "no backups next to the originals")

    def test_stale_symlink_is_repointed(self):
        skill = self.home / "skills/smart-home/klipper-3d-printing"
        skill.parent.mkdir(parents=True)
        skill.symlink_to(self.tmp)
        self.run_installer()
        self.assertEqual(ROOT / "hermes/skills/klipper-3d-printing", Path(os.readlink(skill)))

    def make_venv(self):
        venv = self.tmp / "venv"
        subprocess.run(["python3", "-m", "venv", "--without-pip", str(venv)], check=True, capture_output=True)
        py = venv / "bin/python"
        purelib = subprocess.run([str(py), "-c", 'import sysconfig; print(sysconfig.get_paths()["purelib"])'],
                                 check=True, capture_output=True, text=True).stdout.strip()
        return py, Path(purelib)

    def test_pth_written_to_venv_site_packages(self):
        py, purelib = self.make_venv()
        dry = self.run_installer("--dry-run", python=str(py))
        self.assertIn("would: write", dry)
        self.assertFalse((purelib / "print_buddy.pth").exists())
        self.run_installer(python=str(py))
        self.assertEqual(f"{ROOT}\n", (purelib / "print_buddy.pth").read_text())
        self.assertIn("ok      " + str(purelib / "print_buddy.pth"), self.run_installer(python=str(py)))

    def test_unusable_python_skips_pth_with_warning(self):
        self.assertIn("skipped print_buddy.pth", self.run_installer())

    def test_legacy_state_files_are_copied_not_moved(self):
        fake_home = self.tmp / "fakehome"
        fake_home.mkdir()
        (fake_home / ".print_bitch_context.json").write_text("ctx\n")
        (fake_home / ".print_bitch_start_claims.json").write_text("claims-old\n")
        (fake_home / ".moonraker_discord_announcements.json").write_text("ann\n")
        state = self.home / "state"
        state.mkdir(parents=True)
        (state / "print_bitch_start_claims.json").write_text("claims-new\n")
        dry = self.run_installer("--dry-run")
        self.assertIn("would: copy", dry)
        self.assertFalse((state / "print_bitch_context.json").exists())
        self.run_installer()
        self.assertEqual("ctx\n", (state / "print_bitch_context.json").read_text())
        self.assertEqual("ann\n", (state / "moonraker_discord_announcements.json").read_text())
        self.assertEqual("claims-new\n", (state / "print_bitch_start_claims.json").read_text())
        self.assertTrue((fake_home / ".print_bitch_context.json").exists())

    def test_old_private_scripts_dir_is_moved_aside(self):
        scripts = self.home / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "moonraker_event_listener.py").write_text("# old\n")
        out = self.run_installer()
        self.assertIn("old private scripts/", out)
        self.assertFalse(scripts.exists())
        [moved] = (self.home / ".install-backups").glob("*/scripts")
        self.assertTrue((moved / "moonraker_event_listener.py").is_file())

    def test_config_template_runs_terminal_from_the_repo(self):
        self.run_installer()
        self.assertIn(f"cwd: {ROOT}", (self.home / "config.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
