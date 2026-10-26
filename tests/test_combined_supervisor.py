"""Native lifecycle regressions: fake children only, no service or printer contact."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'docker/supervise.sh'


class CombinedSupervisorTests(unittest.TestCase):
    def environment(self, directory, child):
        fake = Path(directory, 'python3')
        fake.write_text('#!/bin/bash\n' + child)
        fake.chmod(0o755)
        return {**os.environ, 'PATH': directory + ':' + os.environ['PATH'],
                'PRINT_BUDDY_BUNDLED_SPOOLMAN': 'false',
                'PRINT_BUDDY__SERVICES__SPOOLMAN_URL': 'http://external.invalid:8000',
                'DISCORD_BOT_TOKEN': ''}

    def test_explicit_command_is_executed_without_services(self):
        result = subprocess.run(['bash', str(SCRIPT), 'printf', 'offline-probe'],
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'offline-probe')

    def test_even_clean_required_child_exit_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            env = self.environment(directory, 'exit 0\n')
            result = subprocess.run(['bash', str(SCRIPT)], env=env,
                                    capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('bot disabled', result.stdout)

    def test_child_failure_status_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            env = self.environment(directory, 'exit 7\n')
            result = subprocess.run(['bash', str(SCRIPT)], env=env,
                                    capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 7, result.stderr)

    def test_sigterm_exits_and_stops_child(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory, 'child-pid')
            env = self.environment(directory, f'echo $$ > {marker}\nexec sleep 60\n')
            process = subprocess.Popen(['bash', str(SCRIPT)], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                for _ in range(100):
                    if marker.exists():
                        break
                    time.sleep(0.02)
                self.assertTrue(marker.exists())
                pid = int(marker.read_text())
                process.send_signal(signal.SIGTERM)
                process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_disabled_backend_requires_external_url(self):
        with tempfile.TemporaryDirectory() as directory:
            env = self.environment(directory, 'exit 0\n')
            env['PRINT_BUDDY__SERVICES__SPOOLMAN_URL'] = 'http://127.0.0.1:8000'
            result = subprocess.run(['bash', str(SCRIPT)], env=env,
                                    capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 2)
        self.assertIn('External Spoolman URL required', result.stderr)


# A settings-aware fake python3 for the platform gate (#164): the supervisor's
# settings probe (python3 -c ...) answers from PB_FAKE_PLATFORM /
# PB_FAKE_TOKEN_ENV, the bot and listener record their start in PB_FAKE_MARKER,
# and the listener stays up briefly so the bot's start is never racing the
# supervisor's shutdown.
PLATFORM_CHILD = '''if [ "$1" = "-c" ]; then
  printf '%s\\n%s\\n' "${PB_FAKE_PLATFORM:-discord}" "${PB_FAKE_TOKEN_ENV:-DISCORD_BOT_TOKEN}"
  exit "${PB_FAKE_SETTINGS_RC:-0}"
fi
case "$2" in
  print_buddy.bot) echo bot >> "$PB_FAKE_MARKER" ;;
  print_buddy.hermes.moonraker_event_listener) echo listener >> "$PB_FAKE_MARKER"; exec sleep 1 ;;
esac
exit 0
'''


class SupervisorPlatformGateTests(unittest.TestCase):
    """The bot starts iff the CONFIGURED platform's token is set (#164)."""

    def run_supervisor(self, directory, **overrides):
        fake = Path(directory, 'python3')
        fake.write_text('#!/bin/bash\n' + PLATFORM_CHILD)
        fake.chmod(0o755)
        env = {**os.environ, 'PATH': directory + ':' + os.environ['PATH'],
               'PRINT_BUDDY_BUNDLED_SPOOLMAN': 'false',
               'PRINT_BUDDY__SERVICES__SPOOLMAN_URL': 'http://external.invalid:8000',
               'PB_FAKE_MARKER': str(Path(directory, 'marker')),
               'DISCORD_BOT_TOKEN': '', 'TELEGRAM_BOT_TOKEN': '', 'MATRIX_ACCESS_TOKEN': ''}
        env.update(overrides)
        result = subprocess.run(['bash', str(SCRIPT)], env=env,
                                capture_output=True, text=True, timeout=15)
        marker = Path(directory, 'marker')
        started = marker.read_text().split() if marker.exists() else []
        return result, started

    def assert_bot(self, directory, started, **overrides):
        result, started = self.run_supervisor(directory, **overrides)
        self.assertIn('listener', started)
        self.assertIn('bot', started)
        # A required child exiting cleanly still ends the container nonzero.
        self.assertEqual(result.returncode, 1, result.stderr)
        return result

    def assert_idle(self, directory, started, **overrides):
        result, started = self.run_supervisor(directory, **overrides)
        self.assertEqual(started, ['listener'])
        self.assertIn('bot disabled', result.stdout)
        return result

    def test_discord_token_starts_the_bot(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assert_bot(directory, None, DISCORD_BOT_TOKEN='tok')

    def test_discord_empty_token_idles_the_bot(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.assert_idle(directory, None)
            self.assertIn('DISCORD_BOT_TOKEN is empty', result.stdout)

    def test_telegram_token_starts_the_bot(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assert_bot(directory, None, PB_FAKE_PLATFORM='telegram',
                            PB_FAKE_TOKEN_ENV='TELEGRAM_BOT_TOKEN', TELEGRAM_BOT_TOKEN='tok')

    def test_telegram_empty_token_idles_even_with_a_discord_token(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.assert_idle(directory, None, PB_FAKE_PLATFORM='telegram',
                                      PB_FAKE_TOKEN_ENV='TELEGRAM_BOT_TOKEN',
                                      DISCORD_BOT_TOKEN='tok')
            self.assertIn('TELEGRAM_BOT_TOKEN is empty', result.stdout)

    def test_matrix_token_starts_the_bot(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assert_bot(directory, None, PB_FAKE_PLATFORM='matrix',
                            PB_FAKE_TOKEN_ENV='MATRIX_ACCESS_TOKEN', MATRIX_ACCESS_TOKEN='tok')

    def test_matrix_empty_token_idles_the_bot(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.assert_idle(directory, None, PB_FAKE_PLATFORM='matrix',
                                      PB_FAKE_TOKEN_ENV='MATRIX_ACCESS_TOKEN')
            self.assertIn('MATRIX_ACCESS_TOKEN is empty', result.stdout)

    def test_unreadable_settings_fall_back_to_discord(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.assert_bot(directory, None, PB_FAKE_SETTINGS_RC='1',
                                     DISCORD_BOT_TOKEN='tok')
            self.assertIn('falling back to Discord', result.stdout)
        with tempfile.TemporaryDirectory() as directory:
            result = self.assert_idle(directory, None, PB_FAKE_SETTINGS_RC='1')
            self.assertIn('falling back to Discord', result.stdout)

    def test_a_renamed_token_variable_is_honoured(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assert_bot(directory, None, PB_FAKE_TOKEN_ENV='CUSTOM_BOT_TOKEN',
                            CUSTOM_BOT_TOKEN='tok')
        with tempfile.TemporaryDirectory() as directory:
            # The default variable being set does not start the bot when the
            # settings name a different one.
            result = self.assert_idle(directory, None, PB_FAKE_TOKEN_ENV='CUSTOM_BOT_TOKEN',
                                      DISCORD_BOT_TOKEN='tok')
            self.assertIn('CUSTOM_BOT_TOKEN is empty', result.stdout)
