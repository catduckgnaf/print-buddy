"""Web UI stage 2 (#286): the read-only status snapshot and stdlib server.

Everything runs offline: settings come from temp YAML files, the bot and
listener heartbeats are fabricated records (or real heartbeat files under
a temp state dir), the Spoolman probe is injected, and the server binds
an ephemeral loopback port.
"""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from print_buddy import __version__, healthcheck, settings
from print_buddy.webui import server, status

TOKEN = "test-webui-token-12345"
OTHER_SECRET = "test-discord-token-67890"


def load_settings(tmp, extra="", environ=None):
    local = Path(tmp) / "local.yaml"
    local.write_text(f"paths:\n  hermes_home: {tmp}/hermes\n{extra}")
    return settings.load(local=local, environ={} if environ is None else environ)


def fresh_heartbeat(**overrides):
    record = {"heartbeat_at": time.time(), "pid": os.getpid(), "mode": "standalone",
              "connected": True, "user": "printbuddy#0001", "handlers": 12,
              "hermes_modules": []}
    record.update(overrides)
    return record


def ok_probe(url):
    return True, "HTTP 200"


def down_probe(url):
    return False, "URLError: connection refused"


OK_CHECKS = [{"label": "settings", "status": "ok", "detail": "fine"}]


class SnapshotTests(unittest.TestCase):
    def test_snapshot_contents_with_fresh_heartbeats(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = load_settings(tmp, "services:\n  spoolman_url: http://spoolman.local:7912\n")
            healthcheck.beat(data=data)  # a real, fresh listener heartbeat
            snap = status.snapshot(data, environ={}, heartbeat=fresh_heartbeat(),
                                   probe=ok_probe, checks=OK_CHECKS)
        self.assertEqual(snap["version"], __version__)
        self.assertEqual(snap["printer"]["model"], "flashforge.ad5x")
        self.assertEqual(snap["printer"]["connection"], "moonraker")
        self.assertEqual(snap["printer"]["vendor"], "flashforge")
        self.assertEqual(snap["bot"]["platform"], "discord")
        self.assertEqual(snap["bot"]["mode"], "hermes")
        self.assertTrue(snap["bot"]["ok"])
        self.assertEqual(snap["bot"]["heartbeat"]["user"], "printbuddy#0001")
        self.assertTrue(snap["listener"]["required"])
        self.assertTrue(snap["listener"]["ok"])
        # A non-loopback configured URL with no bundled flag is external.
        self.assertFalse(snap["spoolman"]["bundled"])
        self.assertEqual(snap["spoolman"]["url"], "http://spoolman.local:7912")
        self.assertTrue(snap["spoolman"]["ok"])
        self.assertEqual(snap["services"], {"spoolman_url": "http://spoolman.local:7912"})
        self.assertTrue(snap["ok"])

    def test_listener_section_aggregates_a_multi_printer_roster(self):
        # #336: one status row per printer; a printer without a listener
        # domain adds no requirement.
        with tempfile.TemporaryDirectory() as tmp:
            data = load_settings(tmp, extra=(
                "printers:\n"
                "  - id: moon-two\n    model: klipper.generic\n"
                "  - id: stock-two\n    model: flashforge_stock.ad5x\n"))
            healthcheck.beat(data=data, printer_id="moon-two")
            section = status.snapshot(data, environ={}, heartbeat=fresh_heartbeat(),
                                      probe=ok_probe, checks=OK_CHECKS)["listener"]
        self.assertTrue(section["required"])
        self.assertTrue(section["ok"])
        self.assertEqual(set(section["printers"]), {"moon-two", "stock-two"})
        self.assertTrue(section["printers"]["moon-two"]["ok"])
        self.assertFalse(section["printers"]["stock-two"]["required"])

    def test_listener_section_names_the_unhealthy_printer(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = load_settings(tmp, extra=(
                "printers:\n"
                "  - id: moon-two\n    model: klipper.generic\n"
                "  - id: bambu-two\n    model: bambulab.a1\n"))
            healthcheck.beat(data=data, printer_id="moon-two")
            section = status.snapshot(data, environ={}, heartbeat=fresh_heartbeat(),
                                      probe=ok_probe, checks=OK_CHECKS)["listener"]
        self.assertTrue(section["required"])
        self.assertFalse(section["ok"])
        self.assertIn("bambu-two", section["reason"])

    def test_stale_bot_heartbeat_and_missing_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = load_settings(tmp)
            stale = status.snapshot(data, environ={}, heartbeat=fresh_heartbeat(
                heartbeat_at=time.time() - 10000), probe=down_probe, checks=OK_CHECKS)
            missing = status.snapshot(data, environ={}, heartbeat=None,
                                      probe=down_probe, checks=OK_CHECKS)
        self.assertFalse(stale["bot"]["ok"])
        self.assertIn("old", stale["bot"]["reason"])
        self.assertFalse(missing["bot"]["ok"])
        self.assertIn("no heartbeat", missing["bot"]["reason"])
        self.assertFalse(stale["ok"])

    def test_heartbeat_default_reads_disk_but_explicit_none_means_missing(self):
        # Regression: None must not fall back to reading whatever heartbeat
        # file another process left in the shared state dir (in the full
        # suite the bot tests write a real one, which made CI read it).
        with tempfile.TemporaryDirectory() as tmp:
            data = load_settings(tmp)
            with mock.patch.object(status.bot_health, "read",
                                   return_value=fresh_heartbeat()):
                from_disk = status.snapshot(data, environ={}, probe=ok_probe,
                                            checks=OK_CHECKS)
                explicit = status.snapshot(data, environ={}, heartbeat=None,
                                           probe=ok_probe, checks=OK_CHECKS)
        self.assertTrue(from_disk["bot"]["ok"])
        self.assertFalse(explicit["bot"]["ok"])
        self.assertIn("no heartbeat", explicit["bot"]["reason"])

    def test_spoolman_down_is_data_and_bundled_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = load_settings(tmp, "services:\n  spoolman_url: http://127.0.0.1:8000\n")
            down = status.snapshot(data, environ={}, heartbeat=fresh_heartbeat(),
                                   probe=down_probe, checks=OK_CHECKS)
            bundled = status.snapshot(data, environ={"PRINT_BUDDY_BUNDLED_SPOOLMAN": "true"},
                                      heartbeat=fresh_heartbeat(), probe=ok_probe,
                                      checks=OK_CHECKS)
        self.assertFalse(down["spoolman"]["ok"])
        self.assertIn("refused", down["spoolman"]["detail"])
        # Loopback URL + no explicit flag reads as the bundled container API,
        # and an explicit bundled flag probes the loopback port.
        self.assertTrue(down["spoolman"]["bundled"])
        self.assertTrue(bundled["spoolman"]["bundled"])
        self.assertEqual(bundled["spoolman"]["url"], "http://127.0.0.1:8000")
        self.assertTrue(bundled["spoolman"]["ok"])

    def test_doctor_failure_is_rendered_as_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = load_settings(tmp)
            rows = status.doctor_checks(data)
            snap = status.snapshot(data, environ={}, heartbeat=fresh_heartbeat(),
                                   probe=ok_probe)  # real doctor rows
        labels = {row["label"] for row in rows}
        self.assertTrue({"settings", "printer model", "core", "bot mode"} <= labels)
        # The temp install has no printer hardware record: a fail row, not a raise.
        hardware = next(row for row in rows if row["label"] == "hardware record")
        self.assertEqual(hardware["status"], "fail")
        self.assertFalse(snap["ok"])  # a doctor fail turns the overall flag off

    def test_no_secret_values_in_snapshot(self):
        environ = {"WEBUI_ACCESS_TOKEN": TOKEN, "DISCORD_BOT_TOKEN": OTHER_SECRET,
                   "MOONRAKER_API_KEY": "test-moonraker-key"}
        with tempfile.TemporaryDirectory() as tmp:
            data = load_settings(tmp)
            snap = status.snapshot(data, environ=environ, heartbeat=fresh_heartbeat(),
                                   probe=ok_probe, checks=OK_CHECKS)
        blob = json.dumps(snap)
        for secret in (TOKEN, OTHER_SECRET, "test-moonraker-key"):
            self.assertNotIn(secret, blob)


class ServerStartTests(unittest.TestCase):
    def test_disabled_and_portless_configs_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            disabled = load_settings(tmp)
            portless = load_settings(tmp, "webui:\n  enabled: true\n")
        with self.assertRaises(server.WebUIServerError):
            server.check_start(disabled, {})
        with self.assertRaises(server.WebUIServerError):
            server.make_server(disabled, environ={})
        with self.assertRaises(server.WebUIServerError):
            server.check_start(portless, {})
        self.assertEqual(server.serve(disabled, environ={}), 2)

    def test_non_loopback_without_token_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = load_settings(tmp, "webui:\n  enabled: true\n  host: 0.0.0.0\n  port: 8765\n")
        with self.assertRaises(server.WebUIServerError) as caught:
            server.check_start(data, {})
        self.assertIn("WEBUI_ACCESS_TOKEN", str(caught.exception))
        with self.assertRaises(server.WebUIServerError):
            server.make_server(data, environ={})
        # The same bind with a token set is allowed.
        host, port, token = server.check_start(data, {"WEBUI_ACCESS_TOKEN": TOKEN})
        self.assertEqual((host, port, token), ("0.0.0.0", 8765, TOKEN))

    def test_loopback_detection(self):
        for host in ("127.0.0.1", "127.5.0.9", "::1", "localhost"):
            self.assertTrue(server.is_loopback(host), host)
        for host in ("0.0.0.0", "192.168.1.10", "printer.local", ""):
            self.assertFalse(server.is_loopback(host), host)


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


class ServerRouteTests(unittest.TestCase):
    def start(self, tmp, extra="", environ=None):
        data = load_settings(tmp, "webui:\n  enabled: true\n  port: 8765\n" + extra,
                             environ=environ)
        httpd = server.make_server(data, environ={} if environ is None else environ,
                                   port=0, snapshot_func=lambda: FAKE_SNAPSHOT)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        return httpd.server_address[1]

    def request(self, port, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read().decode()
        finally:
            conn.close()

    def test_routes_and_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = self.start(tmp)
            code, body = self.request(port, "GET", "/")
            self.assertEqual(code, 200)
            self.assertIn("Print Buddy status", body)
            self.assertIn("Flashforge AD5X", body)
            code, body = self.request(port, "GET", "/api/status")
            self.assertEqual(code, 200)
            payload = json.loads(body)
            self.assertEqual(payload["printer"]["model"], "flashforge.ad5x")
            self.assertEqual(payload["spoolman"]["url"], "http://127.0.0.1:8000")
            self.assertEqual(payload["doctor"][0]["status"], "ok")
            code, _ = self.request(port, "GET", "/nope")
            self.assertEqual(code, 404)

    def test_healthz_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = self.start(tmp)
            with mock.patch.object(server.bot_health, "read", return_value=fresh_heartbeat()):
                code, body = self.request(port, "GET", "/healthz")
            self.assertEqual(code, 200)
            self.assertTrue(json.loads(body)["ok"])
            stale = fresh_heartbeat(heartbeat_at=time.time() - 10000)
            with mock.patch.object(server.bot_health, "read", return_value=stale):
                code, body = self.request(port, "GET", "/healthz")
            self.assertEqual(code, 503)
            self.assertFalse(json.loads(body)["ok"])

    def test_non_get_methods_are_405(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = self.start(tmp)
            for method in ("POST", "PUT", "DELETE", "PATCH"):
                code, _ = self.request(port, method, "/api/status")
                self.assertEqual(code, 405, method)

    def test_token_required_and_accepted_on_loopback_when_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = self.start(tmp, environ={"WEBUI_ACCESS_TOKEN": TOKEN})
            code, _ = self.request(port, "GET", "/api/status")
            self.assertEqual(code, 401)
            code, _ = self.request(port, "GET", "/api/status",
                                   headers={server.TOKEN_HEADER: "wrong"})
            self.assertEqual(code, 401)
            code, body = self.request(port, "GET", "/api/status",
                                      headers={server.TOKEN_HEADER: TOKEN})
            self.assertEqual(code, 200)
            self.assertNotIn(TOKEN, body)

    def test_no_secret_strings_in_any_response(self):
        environ = {"WEBUI_ACCESS_TOKEN": TOKEN, "DISCORD_BOT_TOKEN": OTHER_SECRET}
        with tempfile.TemporaryDirectory() as tmp:
            port = self.start(tmp, environ=environ)
            headers = {server.TOKEN_HEADER: TOKEN}
            bodies = [self.request(port, "GET", path, headers=headers)[1]
                      for path in ("/", "/api/status", "/healthz", "/nope")]
            bodies.append(self.request(port, "POST", "/api/status", headers=headers)[1])
            bodies.append(self.request(port, "GET", "/api/status")[1])  # the 401 body
        for body in bodies:
            self.assertNotIn(TOKEN, body)
            self.assertNotIn(OTHER_SECRET, body)


if __name__ == "__main__":
    unittest.main()
