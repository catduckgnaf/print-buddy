"""docker/healthcheck.py: the bot heartbeat is required only when the configured
platform's token is present (#164) — the same rule docker/supervise.sh applies.
Empty token = bot idle = healthy, for every platform; listener and Spoolman
checks are stubbed, nothing here contacts a service."""
import importlib.util
import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("docker_healthcheck", ROOT / "docker" / "healthcheck.py")
healthcheck = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(healthcheck)

from print_buddy import settings  # noqa: E402

LABELS = {"discord": "Discord", "telegram": "Telegram", "matrix": "Matrix"}
TOKEN_VARS = {"discord": "DISCORD_BOT_TOKEN", "telegram": "TELEGRAM_BOT_TOKEN",
              "matrix": "MATRIX_ACCESS_TOKEN"}


def fake_cfg(platform, token_env=None):
    cfg = {"bot": {"platform": platform},
           "discord": {"token_env": "DISCORD_BOT_TOKEN"},
           "telegram": {"token_env": "TELEGRAM_BOT_TOKEN"},
           "matrix": {"access_token_env": "MATRIX_ACCESS_TOKEN"}}
    if token_env:
        section = "matrix" if platform == "matrix" else platform
        key = "access_token_env" if platform == "matrix" else "token_env"
        cfg[section][key] = token_env
    return cfg


class BotTokenEnvTests(unittest.TestCase):
    def test_each_platform_resolves_its_token_variable(self):
        for platform, expected in TOKEN_VARS.items():
            with self.subTest(platform=platform):
                with mock.patch.object(settings, "current", lambda p=platform: fake_cfg(p)):
                    self.assertEqual(healthcheck.bot_token_env(), (platform, expected))

    def test_a_renamed_token_variable_is_honoured(self):
        with mock.patch.object(settings, "current", lambda: fake_cfg("telegram", "CUSTOM_TG_TOKEN")):
            self.assertEqual(healthcheck.bot_token_env(), ("telegram", "CUSTOM_TG_TOKEN"))

    def test_broken_settings_fall_back_to_discord(self):
        with mock.patch.object(settings, "current", side_effect=RuntimeError("no settings")):
            self.assertEqual(healthcheck.bot_token_env(), ("discord", "DISCORD_BOT_TOKEN"))


class MainTests(unittest.TestCase):
    def run_main(self, platform, environ, bot_rc=0):
        bot_check = mock.Mock(return_value=bot_rc)
        response = mock.Mock(status=200)
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        out = io.StringIO()
        with mock.patch.object(settings, "current", lambda: fake_cfg(platform)), \
                mock.patch.object(healthcheck, "bot_check", bot_check), \
                mock.patch.object(healthcheck, "listener_check", lambda: (True, "stubbed")), \
                mock.patch("urllib.request.urlopen", return_value=response), \
                mock.patch.dict(os.environ, environ, clear=True), \
                redirect_stdout(out):
            rc = healthcheck.main()
        return rc, bot_check, out.getvalue()

    def test_empty_token_is_healthy_and_skips_the_bot_check(self):
        for platform in TOKEN_VARS:
            with self.subTest(platform=platform):
                rc, bot_check, out = self.run_main(platform, {})
                self.assertEqual(rc, 0)
                bot_check.assert_not_called()
                self.assertIn(f"{LABELS[platform]} bot disabled by empty token", out)

    def test_present_token_requires_a_fresh_bot_heartbeat(self):
        for platform, token_var in TOKEN_VARS.items():
            with self.subTest(platform=platform):
                rc, bot_check, _ = self.run_main(platform, {token_var: "tok"})
                self.assertEqual(rc, 0)
                bot_check.assert_called_once_with()
                rc, _, _ = self.run_main(platform, {token_var: "tok"}, bot_rc=1)
                self.assertEqual(rc, 1)

    def test_another_platforms_token_does_not_enable_the_check(self):
        rc, bot_check, out = self.run_main("telegram", {"DISCORD_BOT_TOKEN": "tok"})
        self.assertEqual(rc, 0)
        bot_check.assert_not_called()
        self.assertIn("Telegram bot disabled by empty token", out)


if __name__ == "__main__":
    unittest.main()
