"""Web UI stage 3 (#286): the picker configuration page.

GET /config renders the stage 1 catalog as a form; saving is
preview (diff, writes nothing) -> confirm (the stage 1 validated write).
Everything runs offline against a temp settings file named by
PRINT_HANDY_CONFIG, with the server on an ephemeral loopback port.
"""
import http.client
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

from print_handy import settings
from print_handy.webui import config as config_api
from print_handy.webui import server

TOKEN = "test-webui-token-12345"
OTHER_SECRET = "test-discord-token-67890"
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}

FAKE_SNAPSHOT = {
    "version": "0.test", "host": "testhost", "ok": True,
    "printer": {"model": "flashforge.ad5x", "name": "Flashforge AD5X",
                "vendor": "flashforge", "connection": "moonraker"},
    "bot": {"platform": "discord", "mode": "standalone", "ok": True,
            "reason": "connected", "heartbeat": {"connected": True}},
    "listener": {"required": True, "ok": True, "reason": "alive"},
    "spoolman": {"bundled": True, "url": "http://127.0.0.1:8000", "ok": True,
                 "detail": "HTTP 200"},
    "services": {"spoolman_url": "http://127.0.0.1:8000"},
    "doctor": [{"label": "settings", "status": "ok", "detail": "fine"}],
}


def hidden_inputs(body):
    return re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', body)


def row_segment(body, field_id):
    """The rendered row for one field, for error-placement assertions."""
    return body.split(f'id="row-{field_id}"', 1)[1].split("</div>", 1)[0]


class ConfigPageTests(unittest.TestCase):
    def start(self, tmp, extra="", environ=None):
        local = Path(tmp) / "local.yaml"
        local.write_text(f"paths:\n  hermes_home: {tmp}/hermes\n"
                         "webui:\n  enabled: true\n  port: 8765\n" + extra)
        environ = {"PRINT_HANDY_CONFIG": str(local), **(environ or {})}
        data = settings.load(local=local, environ=environ)
        httpd = server.make_server(data, environ=environ, port=0,
                                   snapshot_func=lambda: FAKE_SNAPSHOT)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        return httpd.server_address[1], local, environ

    def request(self, port, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read().decode()
        finally:
            conn.close()

    def get_config(self, port, headers=None):
        code, body = self.request(port, "GET", "/config", headers=headers)
        csrf = dict(hidden_inputs(body)).get("_csrf", "")
        return code, body, csrf

    def browser_form(self, environ, csrf, **overrides):
        """The (name, value) pairs a browser would submit for the current
        effective settings, with per-field overrides applied (None removes
        the field, as an unchecked checkbox or emptied select does)."""
        form = []
        for item in config_api.read_fields(environ=environ):
            if item.env_overridden:
                continue
            value = item.value
            if item.field.kind == "toggle":
                if value:
                    form.append((item.id, "true"))
            elif isinstance(value, (list, tuple)):
                form += [(item.id, str(part)) for part in value]
            elif isinstance(value, float) and value == int(value):
                form.append((item.id, str(int(value))))
            else:
                form.append((item.id, "" if value is None else str(value)))
        for field_id, value in overrides.items():
            form = [(k, v) for k, v in form if k != field_id]
            if value is not None:
                form.append((field_id, value))
        form.append(("_csrf", csrf))
        return form

    def post(self, port, path, pairs, headers=None):
        return self.request(port, "POST", path, body=urlencode(pairs),
                            headers={**FORM_HEADERS, **(headers or {})})

    def save_flow(self, port, environ, csrf, **overrides):
        """Preview + confirm with the preview's own hidden inputs."""
        code, body = self.post(port, "/config/preview",
                               self.browser_form(environ, csrf, **overrides))
        self.assertEqual(code, 200, body)
        return self.post(port, "/config", hidden_inputs(body))

    # -- rendering ---------------------------------------------------------

    def test_config_page_renders_groups_fields_badges_and_pickers(self):
        with tempfile.TemporaryDirectory() as tmp:
            port, _local, _environ = self.start(tmp, "discord:\n  chat_id: '12345'\n")
            code, body, csrf = self.get_config(port)
        self.assertEqual(code, 200)
        self.assertTrue(csrf)
        self.assertIn('action="/config/preview"', body)
        for heading in ("Printer", "Platform and chat", "Services", "Timelapse",
                        "Images and camera watch", "Slicing and delivery",
                        "Logging", "Web UI"):
            self.assertIn(f"<h2>{heading}</h2>", body)
        for name in ("printer.model", "bot.platform", "discord.chat_id",
                     "telegram.chat_id", "matrix.room_id",
                     "services.moonraker_url", "services.spoolman_url",
                     "services.camera_source", "services.camera_snapshot_url",
                     "visual_watch.sensitivity", "timelapse.mode",
                     "timelapse.render_wait_s", "printer.slicer",
                     "delivery.methods", "logging.level", "webui.port"):
            self.assertIn(f'name="{name}"', body, name)
        # Provenance badges: the file value, the home value, a model default.
        self.assertIn("settings file", row_segment(body, "discord.chat_id"))
        self.assertIn("home config", row_segment(body, "printer.model"))
        self.assertIn("model default", row_segment(body, "printer.slicer"))
        # Pickers carry the real choice sets with the effective value selected.
        self.assertIn('<option value="flashforge.ad5x" selected>', body)
        for choice in ("rendered", "container", "off"):
            self.assertIn(f'<option value="{choice}"', body)
        # No Moonraker URL is configured here, so the derived mode is off.
        self.assertIn('<option value="off" selected>', body)
        for choice in ("auto", "moonraker", "bambu", "go2rtc", "none"):
            self.assertIn(f'<option value="{choice}"', body)
        self.assertIn('<option value="auto" selected>', body)
        # The sensitivity number input carries the catalog bounds.
        self.assertIn('min="1" max="5"', row_segment(body, "visual_watch.sensitivity"))

    def test_status_page_links_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            port, _local, _environ = self.start(tmp)
            code, body = self.request(port, "GET", "/")
        self.assertEqual(code, 200)
        self.assertIn('href="/config"', body)

    def test_env_overridden_field_is_disabled_and_never_written(self):
        environ = {"PRINT_HANDY__VISUAL_WATCH__SENSITIVITY": "4"}
        with tempfile.TemporaryDirectory() as tmp:
            port, local, environ = self.start(tmp, environ=environ)
            code, body, csrf = self.get_config(port)
            self.assertEqual(code, 200)
            row = row_segment(body, "visual_watch.sensitivity")
            self.assertIn("disabled", row)
            self.assertIn("Overridden by the environment", row)
            self.assertIn("environment override", row)
            before = local.read_bytes()
            # Even a crafted submission naming the field changes nothing.
            form = self.browser_form(environ, csrf)
            form.append(("visual_watch.sensitivity", "2"))
            code, body = self.post(port, "/config/preview", form)
            self.assertEqual(code, 200)
            self.assertIn("No changes", body)
            self.assertEqual(local.read_bytes(), before)

    # -- save flow -----------------------------------------------------------

    def test_preview_shows_exact_diff_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            port, local, environ = self.start(tmp, "discord:\n  chat_id: '12345'\n")
            _code, _body, csrf = self.get_config(port)
            before = local.read_bytes()
            code, body = self.post(port, "/config/preview", self.browser_form(
                environ, csrf, **{"discord.chat_id": "999",
                                  "visual_watch.sensitivity": "5"}))
            self.assertEqual(code, 200)
            self.assertIn("discord.chat_id", body)
            self.assertIn("12345", body)  # the current value
            self.assertIn("999", body)    # the new value
            self.assertIn("visual_watch.sensitivity", body)
            self.assertEqual(local.read_bytes(), before)
            self.assertFalse(list(Path(tmp).glob("*.bak-*")))

    def test_confirmed_post_round_trips_through_the_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            port, local, environ = self.start(tmp, "discord:\n  chat_id: '12345'\n")
            _code, _body, csrf = self.get_config(port)
            code, body = self.save_flow(port, environ, csrf,
                                        **{"discord.chat_id": "999",
                                           "visual_watch.sensitivity": "5"})
            self.assertEqual(code, 200)
            self.assertIn("discord.chat_id", body)
            self.assertIn("visual_watch.sensitivity", body)
            self.assertIn("Restart required", body)
            data = settings.load(local=local, environ={})
            self.assertEqual(data["discord"]["chat_id"], "999")
            self.assertEqual(data["visual_watch"]["sensitivity"], 5)
            self.assertEqual(len(list(Path(tmp).glob("local.yaml.bak-*"))), 1)

    def test_type_pickers_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            port, local, environ = self.start(tmp)
            _code, _body, csrf = self.get_config(port)
            code, body = self.save_flow(port, environ, csrf,
                                        **{"timelapse.mode": "container",
                                           "services.camera_source": "go2rtc"})
            self.assertEqual(code, 200)
            data = settings.load(local=local, environ={})
            self.assertEqual(data["timelapse"]["mode"], "container")
            self.assertEqual(data["services"]["camera_source"], "go2rtc")

    def test_toggle_off_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            port, local, environ = self.start(tmp)
            _code, _body, csrf = self.get_config(port)
            code, _body = self.save_flow(port, environ, csrf,
                                         **{"visual_watch.enabled": None})
            self.assertEqual(code, 200)
            self.assertIs(settings.load(local=local, environ={})["visual_watch"]["enabled"],
                          False)

    def test_invalid_values_are_rejected_against_the_field(self):
        cases = [
            ({"visual_watch.sensitivity": "9"}, "visual_watch.sensitivity", "at most 5"),
            ({"printer.model": "nope.model"}, "printer.model", None),
            ({"services.moonraker_url": "printer.lan"}, "services.moonraker_url",
             "must be a URL"),
            ({"timelapse.mode": "sometimes"}, "timelapse.mode", None),
        ]
        for overrides, field_id, needle in cases:
            with self.subTest(field=field_id), tempfile.TemporaryDirectory() as tmp:
                port, local, environ = self.start(tmp)
                _code, _body, csrf = self.get_config(port)
                before = local.read_bytes()
                code, body = self.post(port, "/config/preview",
                                       self.browser_form(environ, csrf, **overrides))
                self.assertEqual(code, 400)
                self.assertIn('class="error"', row_segment(body, field_id))
                if needle:
                    self.assertIn(needle, row_segment(body, field_id))
                self.assertEqual(local.read_bytes(), before)
                self.assertFalse(list(Path(tmp).glob("*.bak-*")))

    def test_unknown_form_keys_are_never_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            port, local, environ = self.start(tmp)
            _code, _body, csrf = self.get_config(port)
            form = self.browser_form(environ, csrf, **{"discord.chat_id": "777"})
            form += [("discord.token_env", "PWNED"), ("evil.key", "1"),
                     ("services.camera_source_extra", "bambu")]
            code, body = self.post(port, "/config/preview", form)
            self.assertEqual(code, 200)
            code, body = self.post(port, "/config", hidden_inputs(body))
            self.assertEqual(code, 200)
            text = local.read_text()
            self.assertNotIn("token_env", text)
            self.assertNotIn("PWNED", text)
            self.assertNotIn("evil", text)
            self.assertEqual(settings.load(local=local, environ={})["discord"]["chat_id"],
                             "777")

    # -- auth / CSRF ---------------------------------------------------------

    def test_post_requires_the_form_token_or_the_header(self):
        environ = {"WEBUI_ACCESS_TOKEN": TOKEN}
        with tempfile.TemporaryDirectory() as tmp:
            port, local, environ = self.start(tmp, environ=environ)
            code, _body = self.request(port, "GET", "/config")
            self.assertEqual(code, 401)  # stage 2's header rule still gates GETs
            code, _body, csrf = self.get_config(
                port, headers={server.TOKEN_HEADER: TOKEN})
            self.assertEqual(code, 200)
            form = self.browser_form(environ, csrf, **{"discord.chat_id": "999"})
            bare = [(k, v) for k, v in form if k != "_csrf"]
            # Neither header nor form token: refused, nothing written.
            before = local.read_bytes()
            code, _body = self.post(port, "/config/preview", bare)
            self.assertEqual(code, 403)
            # A wrong form token is refused too.
            code, _body = self.post(port, "/config/preview",
                                    bare + [("_csrf", "wrong-token")])
            self.assertEqual(code, 403)
            self.assertEqual(local.read_bytes(), before)
            # The header alone authorizes a POST.
            code, _body = self.post(port, "/config/preview", bare,
                                    headers={server.TOKEN_HEADER: TOKEN})
            self.assertEqual(code, 200)
            # And so does the embedded form token alone.
            code, _body = self.post(port, "/config/preview", form)
            self.assertEqual(code, 200)

    def test_loopback_without_a_token_still_requires_the_form_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            port, local, environ = self.start(tmp)
            _code, _body, csrf = self.get_config(port)
            form = self.browser_form(environ, csrf, **{"discord.chat_id": "999"})
            bare = [(k, v) for k, v in form if k != "_csrf"]
            code, _body = self.post(port, "/config/preview", bare)
            self.assertEqual(code, 403)
            code, _body = self.post(port, "/config/preview", form)
            self.assertEqual(code, 200)

    def test_save_without_the_preview_confirm_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            port, local, environ = self.start(tmp)
            _code, _body, csrf = self.get_config(port)
            before = local.read_bytes()
            form = self.browser_form(environ, csrf, **{"discord.chat_id": "999"})
            code, _body = self.post(port, "/config", form)
            self.assertEqual(code, 400)
            self.assertEqual(local.read_bytes(), before)

    def test_non_config_posts_stay_405(self):
        with tempfile.TemporaryDirectory() as tmp:
            port, _local, _environ = self.start(tmp)
            for path in ("/", "/api/status", "/healthz"):
                code, _body = self.post(port, path, [("_csrf", "x")])
                self.assertEqual(code, 405, path)

    # -- secrecy ---------------------------------------------------------------

    def test_no_secret_strings_in_any_config_response(self):
        environ = {"WEBUI_ACCESS_TOKEN": TOKEN, "DISCORD_BOT_TOKEN": OTHER_SECRET}
        with tempfile.TemporaryDirectory() as tmp:
            port, _local, environ = self.start(tmp, environ=environ)
            headers = {server.TOKEN_HEADER: TOKEN}
            bodies = [self.request(port, "GET", "/", headers=headers)[1]]
            code, body, csrf = self.get_config(port, headers=headers)
            bodies.append(body)
            code, body = self.post(port, "/config/preview", self.browser_form(
                environ, csrf, **{"discord.chat_id": "999"}))
            bodies.append(body)
            code, body = self.post(port, "/config", hidden_inputs(body))
            bodies.append(body)
            bodies.append(self.request(port, "GET", "/config")[1])  # the 401 body
        for body in bodies:
            self.assertNotIn(TOKEN, body)
            self.assertNotIn(OTHER_SECRET, body)


if __name__ == "__main__":
    unittest.main()
