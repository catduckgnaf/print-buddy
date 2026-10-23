"""The Docker release stays complete, consistent and public-safe.

Settings parity: every user-adjustable setting has a row in docs/SETTINGS.md and, when it is a
scalar, an entry in .env.example; every PRINT_BUDDY__ name in a deployment file is a real setting.
Sanitization: public deployment examples carry no LAN addresses, machine paths, IDs or credentials.
Structure: the Compose stack, Dockerfile, Unraid template and OrcaSlicer pin agree with each other.
"""
import ipaddress
import json
import os
import re
import shlex
import socket
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import yaml

from print_buddy import healthcheck, printers, settings

ROOT = settings.ROOT
DOCS = (ROOT / "docs" / "SETTINGS.md").read_text()
ENV_EXAMPLE = (ROOT / ".env.example").read_text()
DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
SPOOLMAN = yaml.safe_load((ROOT / "docker-compose.spoolman.yml").read_text())
UNRAID = ET.parse(ROOT / "docker" / "unraid" / "print-buddy.xml").getroot()
LOCK = dict(line.split("=", 1) for line in (ROOT / "docker" / "orcaslicer.lock").read_text().splitlines()
            if line and not line.startswith("#"))
# Public files a user copies or reads to deploy. All must be sanitized.
DEPLOYMENT_FILES = [".env.example", "docker-compose.yml", "docker-compose.spoolman.yml", "docker-compose.build.yml",
                    "Dockerfile", "docker/entrypoint.sh", "docker/unraid/print-buddy.xml", "docker/orcaslicer.lock",
                    "config/docker.yaml", "config/docker.toml", "docs/DOCKER.md", "docs/SETTINGS.md"]
SECRETS = {"DISCORD_BOT_TOKEN", "OCTOPRINT_API_KEY", "MOONRAKER_API_KEY", "CLIPROXY_API_KEY", "OPENVIKING_API_KEY"}
CONTAINER_VARS = {"PRINT_BUDDY_CONFIG", "PRINT_BUDDY_IMAGE", "PRINT_BUDDY_TAG", "PRINT_BUDDY_DATA", "PUID", "PGID",
                  "TZ", "PRINT_BUDDY_CPUS", "PRINT_BUDDY_MEMORY", "PRINT_BUDDY_HEALTH_MAX_AGE_S", "COMPOSE_FILE",
                  "SPOOLMAN_TAG", "SPOOLMAN_PORT", "ORCA_CHANNEL"}
DATA_TARGETS = {"/data/hermes", "/data/archive", "/data/records", "/data/cache"}


def inventory():
    """{(section, key): example value} for every user-adjustable setting; open sections use key None."""
    home = settings._read(settings.HOME)
    found = {}
    for model in printers.MODELS.values():
        for section, values in settings._merge(model.defaults(), home).items():
            for key, value in values.items():
                found[(section, None if section in settings.OPEN_SECTIONS else key)] = value
    for (section, key), kind in settings.OPTIONAL_KEYS.items():
        found[(section, key)] = kind()
    return found


def env_name(section, key):
    return f"PRINT_BUDDY__{section.upper()}__{key.upper()}"


def is_scalar(value):
    return not isinstance(value, (list, dict))


class SettingsParityTests(unittest.TestCase):
    def setUp(self):
        self.inventory = inventory()
        self.rows = dict(re.findall(r"^\| `([a-z_]+\.(?:[a-z_]+|<[a-zA-Z]+>))` \| ([^|]+) \|", DOCS, re.M))

    def test_every_setting_has_a_reference_row_with_its_env_name(self):
        for (section, key), value in self.inventory.items():
            with self.subTest(setting=f"{section}.{key}"):
                if key is None:
                    self.assertTrue(any(name.startswith(f"{section}.<") for name in self.rows), section)
                    continue
                self.assertIn(f"{section}.{key}", self.rows)
                expected = f"`{env_name(section, key)}`" if is_scalar(value) else "file only"
                self.assertEqual(self.rows[f"{section}.{key}"].strip(), expected)

    def test_every_reference_row_is_a_real_setting(self):
        for name in self.rows:
            section, key = name.split(".")
            with self.subTest(row=name):
                self.assertIn((section, None if key.startswith("<") else key), self.inventory)

    def test_env_example_lists_every_scalar_setting(self):
        for (section, key), value in self.inventory.items():
            if key is not None and is_scalar(value):
                with self.subTest(setting=f"{section}.{key}"):
                    self.assertRegex(ENV_EXAMPLE, rf"(?m)^#? ?{env_name(section, key)}=")

    def test_every_documented_env_name_is_accepted_by_the_loader(self):
        names = set()
        for path in DEPLOYMENT_FILES:
            names |= set(re.findall(r"PRINT_BUDDY__[A-Z0-9_]+__[A-Z0-9_]+", (ROOT / path).read_text()))
        names.discard("PRINT_BUDDY__SECTION__KEY")
        names = {n for n in names if not n.endswith("__TYPE")}  # the <type> placeholder row
        self.assertIn("PRINT_BUDDY__SERVICES__MOONRAKER_URL", names)
        home = settings.load(local=False, environ={})
        for name in sorted(names):
            section, key = name[len("PRINT_BUDDY__"):].lower().split("__")
            with self.subTest(env=name):
                self.assertTrue(key in home.get(section, {}) or (section, key) in settings.OPTIONAL_KEYS, name)

    def test_env_example_values_load(self):
        """The uncommented example values are valid settings once the hosts are filled in."""
        environ = {}
        for line in ENV_EXAMPLE.splitlines():
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                environ[name] = value
        self.assertEqual(set(environ) - CONTAINER_VARS - SECRETS,
                         {n for n in environ if n.startswith("PRINT_BUDDY__")})
        data = settings.load(home=settings.HOME, local=ROOT / "config" / "docker.yaml",
                             environ={k: v for k, v in environ.items() if k.startswith("PRINT_BUDDY__")})
        self.assertEqual(data["services"]["moonraker_ws_url"], "ws://printer.example:7125/websocket")

    def test_secrets_and_container_variables_are_documented(self):
        for name in SECRETS | CONTAINER_VARS:
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", DOCS)
        for name in SECRETS:
            with self.subTest(secret=name):
                self.assertRegex(ENV_EXAMPLE, rf"(?m)^# {name}=$")
                self.assertNotIn(name.lower(), (ROOT / "config" / "docker.yaml").read_text().lower())


class SanitizedExamplesTests(unittest.TestCase):
    def test_no_lan_addresses_machine_paths_ids_or_credentials(self):
        for path in DEPLOYMENT_FILES:
            text = (ROOT / path).read_text()
            with self.subTest(file=path):
                for raw in re.findall(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])", text):
                    address = ipaddress.ip_address(raw)
                    self.assertFalse(address.is_private and not address.is_loopback, f"{path}: LAN address {raw}")
                self.assertIsNone(re.search(r"/(home|Users)/(?!app/)[a-z]", text), f"{path}: machine path")
                self.assertIsNone(re.search(r"/mnt/user/(?!appdata/)", text), f"{path}: personal share")
                self.assertIsNone(re.search(r"(?<![0-9a-f])\d{17,20}(?![0-9a-f])", text), f"{path}: Discord ID")
                self.assertIsNone(re.search(r"[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}",
                                            text), f"{path}: credential")
                for host in re.findall(r"https?://([A-Za-z0-9.-]+)", text):
                    self.assertFalse(host.endswith((".lan", ".local", ".home", ".internal")) and host != "host.docker.internal",
                                     f"{path}: private host name {host}")


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.service = COMPOSE["services"]["print-buddy"]

    def test_only_print_buddy_runs_by_default(self):
        self.assertEqual(set(COMPOSE["services"]), {"print-buddy"})
        self.assertNotIn("build", self.service)
        self.assertNotIn("command", self.service)  # the image CMD is the single runtime switch
        for stack in (COMPOSE, SPOOLMAN):
            for name, service in stack["services"].items():
                self.assertNotIn("hermes", name + service.get("image", "") + json.dumps(service.get("command", "")))

    def test_least_privilege_and_restart(self):
        self.assertTrue(self.service["read_only"])
        self.assertEqual(self.service["cap_drop"], ["ALL"])
        self.assertNotIn("cap_add", self.service)
        self.assertIn("no-new-privileges:true", self.service["security_opt"])
        self.assertEqual(self.service["user"], "${PUID:-1000}:${PGID:-1000}")
        self.assertEqual(self.service["restart"], "unless-stopped")
        self.assertNotIn("privileged", self.service)
        limits = self.service["deploy"]["resources"]["limits"]
        self.assertIn("memory", limits)
        self.assertIn("cpus", limits)

    def test_healthcheck_matches_the_image(self):
        image = re.search(r'HEALTHCHECK [^\n]*\\\n\s+CMD (\[.*\])', DOCKERFILE).group(1)
        self.assertEqual(self.service["healthcheck"]["test"], ["CMD", *json.loads(image)])

    def test_volumes_cover_every_data_directory(self):
        targets = {volume.rsplit(":", 1)[1] for volume in self.service["volumes"]}
        self.assertEqual(targets, DATA_TARGETS)
        entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text()
        self.assertIn("for dir in " + " ".join(sorted(DATA_TARGETS, key=["/data/hermes", "/data/archive",
                      "/data/records", "/data/cache"].index)), entrypoint)

    def test_bundled_spoolman_override(self):
        spoolman = SPOOLMAN["services"]["spoolman"]
        self.assertRegex(spoolman["image"], r"^ghcr\.io/donkie/spoolman:\$\{SPOOLMAN_TAG:-\d+\.\d+\.\d+\}$")
        self.assertEqual(spoolman["volumes"], ["${PRINT_BUDDY_DATA:-./data}/spoolman:/home/app/.local/share/spoolman"])
        self.assertIn("healthcheck", spoolman)
        self.assertEqual(spoolman["restart"], "unless-stopped")
        self.assertEqual(spoolman["cap_drop"], ["ALL"])
        override = SPOOLMAN["services"]["print-buddy"]
        self.assertEqual(override["environment"]["PRINT_BUDDY__SERVICES__SPOOLMAN_URL"], "http://spoolman:8000")
        self.assertEqual(override["depends_on"]["spoolman"]["condition"], "service_healthy")

    def test_external_spoolman_is_the_default(self):
        for path in ("config/docker.yaml", "config/docker.toml"):
            with self.subTest(file=path):
                data = settings.load(home=settings.HOME, local=ROOT / path, environ={})
                self.assertEqual(data["services"]["spoolman_url"], "")
        self.assertRegex(ENV_EXAMPLE, r"(?m)^PRINT_BUDDY__SERVICES__SPOOLMAN_URL=http")
        self.assertRegex(ENV_EXAMPLE, r"(?m)^# COMPOSE_FILE=docker-compose.yml:docker-compose.spoolman.yml$")

    def test_spoolman_pin_matches_ci(self):
        tag = re.search(r"SPOOLMAN_TAG:-([\d.]+)", SPOOLMAN["services"]["spoolman"]["image"]).group(1)
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn(f"releases/download/v{tag}/spoolman.zip", workflow)


class DockerfileTests(unittest.TestCase):
    def test_single_runtime_entry_point_is_importable(self):
        commands = re.findall(r"(?m)^CMD (\[.*\])$", DOCKERFILE)
        self.assertEqual(len(commands), 1)
        command = json.loads(commands[0])
        self.assertEqual(command[:2], ["python3", "-m"])
        module = ROOT / (command[2].replace(".", "/") + ".py")
        self.assertTrue(module.is_file(), module)
        self.assertIn("healthcheck.beat", module.read_text().replace("healthcheck.HEARTBEAT_S", ""))

    def test_runs_unprivileged_without_hermes(self):
        self.assertRegex(DOCKERFILE, r"(?m)^USER 1000:1000$")
        installs = " ".join(re.findall(r"(?ms)^RUN .*?(?<!\\)$", DOCKERFILE))
        self.assertNotIn("hermes", installs.replace("/data/hermes", ""))
        ignored = (ROOT / ".dockerignore").read_text().split()
        for path in ("hermes", "plugins", "tests", ".env", ".git", "data"):
            self.assertIn(path, ignored)

    def test_orca_channel_default_matches_the_lock(self):
        defaults = set(re.findall(r"(?m)^ARG ORCA_CHANNEL=(\w+)$", DOCKERFILE))
        self.assertEqual(defaults, {LOCK["ORCA_DEFAULT_CHANNEL"]})
        build = yaml.safe_load((ROOT / "docker-compose.build.yml").read_text())
        self.assertEqual(build["services"]["print-buddy"]["build"]["args"]["ORCA_CHANNEL"],
                         "${ORCA_CHANNEL:-%s}" % LOCK["ORCA_DEFAULT_CHANNEL"])
        for path in ("config/docker.yaml", "config/docker.toml"):
            data = settings.load(home=settings.HOME, local=ROOT / path, environ={})
            self.assertEqual(data["orca"]["command"], ["/opt/orcaslicer/AppRun"])


class OrcaLockTests(unittest.TestCase):
    def channel(self, name):
        prefix = f"ORCA_{name.upper()}_"
        return {k[len(prefix):]: v for k, v in LOCK.items() if k.startswith(prefix)}

    def test_alpha_is_the_pinned_default(self):
        self.assertEqual(LOCK["ORCA_DEFAULT_CHANNEL"], "alpha")
        alpha = self.channel("alpha")
        self.assertEqual(alpha["VERSION"], "2.5.0-alpha")
        for arch in ("AMD64", "ARM64"):
            with self.subTest(arch=arch):
                self.assertIn(f"V{alpha['VERSION']}", alpha[f"{arch}_ASSET"])
                self.assertRegex(alpha[f"{arch}_SHA256"], r"^[0-9a-f]{64}$")
        self.assertIn("aarch64", alpha["ARM64_ASSET"])

    def test_stable_is_either_unset_or_fully_pinned_to_2_5(self):
        stable = self.channel("stable")
        self.assertEqual(set(stable), {"VERSION", "AMD64_ASSET", "AMD64_SHA256", "ARM64_ASSET", "ARM64_SHA256"})
        if any(stable.values()):
            self.assertTrue(all(stable.values()), "fill in every ORCA_STABLE_* entry")
            self.assertTrue(stable["VERSION"].startswith("2.5."))
            self.assertRegex(stable["AMD64_SHA256"], r"^[0-9a-f]{64}$")
            self.assertRegex(stable["ARM64_SHA256"], r"^[0-9a-f]{64}$")

    def test_ci_alpha_job_uses_the_same_release(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn(f"releases/download/v{LOCK['ORCA_ALPHA_VERSION']}/", workflow)


class UnraidTemplateTests(unittest.TestCase):
    def configs(self, kind):
        return {c.get("Target"): c for c in UNRAID.findall("Config") if c.get("Type") == kind}

    def test_repository_and_paths_match_compose(self):
        image = COMPOSE["services"]["print-buddy"]["image"]
        default = re.match(r"\$\{PRINT_BUDDY_IMAGE:-([^}]+)\}:\$\{PRINT_BUDDY_TAG:-([^}]+)\}", image).groups()
        self.assertEqual(UNRAID.findtext("Repository"), ":".join(default))
        self.assertEqual(set(self.configs("Path")), DATA_TARGETS)

    def test_variables_are_real_settings_or_secrets(self):
        home = settings.load(local=False, environ={})
        for target in self.configs("Variable"):
            with self.subTest(target=target):
                if target.startswith("PRINT_BUDDY__"):
                    section, key = target[len("PRINT_BUDDY__"):].lower().split("__")
                    self.assertTrue(key in home[section] or (section, key) in settings.OPTIONAL_KEYS)
                else:
                    self.assertIn(target, SECRETS | CONTAINER_VARS)
                if target in SECRETS:
                    self.assertEqual(self.configs("Variable")[target].get("Mask"), "true")

    def test_same_hardening_as_compose(self):
        params = shlex.split(UNRAID.findtext("ExtraParams"))
        for flag in ("--read-only", "--cap-drop", "--security-opt", "--user", "--memory"):
            self.assertIn(flag, params)
        self.assertEqual(params[params.index("--cap-drop") + 1], "ALL")
        self.assertEqual(UNRAID.findtext("Privileged"), "false")


class HealthcheckTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = settings.load(local=False, environ={})
        self.data["paths"]["hermes_home"] = Path(self.tmp.name)
        self.data["orca"]["command"] = ["sh"]

    def test_fresh_heartbeat_is_healthy(self):
        record = healthcheck.beat("test-runtime", self.data, moonraker_connected=False)
        healthy, reason, seen = healthcheck.check(self.data, environ={})
        self.assertTrue(healthy, reason)
        self.assertEqual(seen, record)
        self.assertFalse(seen["moonraker_connected"])  # a printer that is off does not fail health

    def test_missing_stale_or_foreign_heartbeat_is_unhealthy(self):
        self.assertFalse(healthcheck.check(self.data, environ={})[0])
        healthcheck.beat("test-runtime", self.data)
        self.assertFalse(healthcheck.check(self.data, now=time.time() + 91, environ={})[0])
        self.assertTrue(healthcheck.check(self.data, now=time.time() + 91,
                                          environ={"PRINT_BUDDY_HEALTH_MAX_AGE_S": "120"})[0])
        path = healthcheck.heartbeat_path(self.data)
        record = json.loads(path.read_text())
        path.write_text(json.dumps({**record, "host": socket.gethostname() + "-old"}))
        self.assertFalse(healthcheck.check(self.data, environ={})[0])
        path.write_text(json.dumps({**record, "pid": 2 ** 22 + 7}))
        with mock.patch.object(healthcheck.os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(healthcheck.check(self.data, environ={})[0])
        path.write_text("{not json")
        self.assertFalse(healthcheck.check(self.data, environ={})[0])

    def test_missing_slicer_or_bad_settings_is_unhealthy(self):
        healthcheck.beat("test-runtime", self.data)
        self.data["orca"]["command"] = ["/nonexistent/AppRun"]
        healthy, reason, _ = healthcheck.check(self.data, environ={})
        self.assertFalse(healthy)
        self.assertIn("not installed", reason)
        healthy, reason, _ = healthcheck.check(environ={"PRINT_BUDDY__VISUAL_WATCH__SENSITIVITY": "9"})
        self.assertFalse(healthy)
        self.assertIn("settings", reason)

    def test_heartbeat_write_is_atomic(self):
        healthcheck.beat("test-runtime", self.data)
        state = healthcheck.heartbeat_path(self.data).parent
        self.assertEqual([p.name for p in state.iterdir()], [healthcheck.HEARTBEAT])


if __name__ == "__main__":
    unittest.main()
