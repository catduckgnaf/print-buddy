"""Contract tests for #246 stage 1: go2rtc container plumbing.

Everything offline: the pinned prebuilt script is parsed (and only its
refusal paths are executed), the supervisor/healthcheck gates run against
fake children, and the deployment files are checked as rendered artefacts.
No Docker build, camera, GPU or network access is needed.
"""
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from print_buddy import go2rtc, settings  # noqa: E402

DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE_TEXT = (ROOT / "docker-compose.yml").read_text()
COMPOSE = yaml.safe_load(COMPOSE_TEXT)
UNRAID_TEXT = (ROOT / "docker/unraid/print-buddy.xml").read_text()
PREBUILT = ROOT / "docker" / "go2rtc-prebuilt.sh"

AMD64_SHA = "20b46c6910734cb05ecefb234066f36868ff19b42ba1418a7a32e13a3e035712"
ARM64_SHA = "af416f22b21a24ab83b8d78642190b4932ae695b4e386853f11d1b0319781763"


class Go2rtcPrebuiltTests(unittest.TestCase):
    """go2rtc is a pinned official prebuilt, verified before installation."""

    def test_pin_table_parses_to_the_official_assets_and_digests(self):
        helper = PREBUILT.read_text()
        self.assertIn("version=1.9.15", helper)
        self.assertIn(f"sha256_amd64={AMD64_SHA}", helper)
        self.assertIn(f"sha256_arm64={ARM64_SHA}", helper)
        self.assertIn("asset_amd64=go2rtc_linux_amd64", helper)
        self.assertIn("asset_arm64=go2rtc_linux_arm64", helper)
        self.assertIn("https://github.com/AlexxIT/go2rtc/releases/download/v${version}/${asset}", helper)
        self.assertIn("set -eu", helper)
        # The digest is verified before the binary is installed anywhere.
        self.assertLess(helper.index("sha256sum --check --strict"),
                        helper.index("install -m 0755"))

    def test_refuses_other_architectures_before_any_download(self):
        for bad in ("arm", "arm/v7", "386", "ppc64le", ""):
            with self.subTest(arch=bad):
                result = subprocess.run(["sh", str(PREBUILT), bad],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 2)
                self.assertIn("amd64 and arm64 only", result.stderr)


class RuntimeImageGo2rtcTests(unittest.TestCase):
    """The published image bundles go2rtc + VAAPI; a WITH_GO2RTC=false build excludes both."""

    def test_go2rtc_stage_and_runtime_copy(self):
        self.assertIn("AS go2rtc-prebuilt", DOCKERFILE)
        self.assertIn("COPY --from=go2rtc-prebuilt /out/ /", DOCKERFILE)
        self.assertIn("sh /usr/local/bin/go2rtc-prebuilt \"$TARGETARCH\"", DOCKERFILE)

    def test_vaapi_stack_is_inside_the_with_go2rtc_conditional(self):
        runtime = DOCKERFILE.split("FROM debian:13-slim AS runtime", 1)[1]
        for package in ("intel-media-va-driver", "mesa-va-drivers", "libva-drm2", "vainfo"):
            with self.subTest(package=package):
                self.assertIn(package, runtime)
        vaapi_block = runtime.split('if [ "$WITH_GO2RTC" = true ]', 1)[1]
        self.assertIn("intel-media-va-driver", vaapi_block)
        # No CUDA toolkit or vendor driver stack is baked in.
        self.assertNotIn("cuda-toolkit", runtime)
        self.assertNotIn("nvidia-", runtime)

    def test_workflows_build_the_published_image_with_go2rtc(self):
        """#353: one published image; every publisher leg builds it with go2rtc."""
        for name in ("docker-publish.yml", "nightly.yml"):
            with self.subTest(workflow=name):
                workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
                jobs = workflow["jobs"]
                build = next(j for j in jobs.values() if "matrix" in j.get("strategy", {}))
                entries = build["strategy"]["matrix"]["include"]
                self.assertEqual({entry["arch"] for entry in entries}, {"amd64", "arm64"})
                self.assertEqual(build["env"]["WITH_GO2RTC"], "true")
                self.assertEqual(build["env"]["WITH_GO2RTC"], build["env"]["WITH_ORCA"])
        validation = (ROOT / ".github/workflows/docker-image-validation.yml").read_text()
        self.assertIn('WITH_GO2RTC: "true"', validation)
        self.assertIn('--build-arg "WITH_GO2RTC=$WITH_GO2RTC"', validation)


class TimelapseCaptureSettingsTests(unittest.TestCase):
    """New [timelapse] settings default to today's behaviour."""

    def test_defaults_are_off_and_unchanged_configs_load(self):
        data = settings.load(environ={})
        self.assertIs(data["timelapse"]["capture_enabled"], False)
        self.assertEqual(data["timelapse"]["capture_source_url"], "")

    def test_env_override_enables_capture(self):
        data = settings.load(environ={"PRINT_BUDDY__TIMELAPSE__CAPTURE_ENABLED": "true"})
        self.assertIs(data["timelapse"]["capture_enabled"], True)


def make_data(**timelapse):
    base = {"capture_enabled": True, "capture_source_url": ""}
    base.update(timelapse)
    return {"timelapse": base,
            "services": {"camera_snapshot_url": "http://printer.example/webcam/?action=snapshot"},
            "paths": {"cache": "/data/cache"}}


class Go2rtcGateAndConfigTests(unittest.TestCase):
    def test_gate_exit_codes(self):
        self.assertEqual(go2rtc.gate(make_data(capture_enabled=False)), 3)
        self.assertEqual(go2rtc.gate(make_data()), 0)
        no_source = make_data()
        no_source["services"]["camera_snapshot_url"] = ""
        self.assertEqual(go2rtc.gate(no_source), 3)

    def test_source_derives_stream_from_moonraker_snapshot(self):
        source = go2rtc.resolve_source(make_data())
        self.assertEqual(source.kind, "mjpeg")
        self.assertEqual(source.stream_url,
                         "http://printer.example/webcam/?action=stream")

    def test_source_override_wins_and_rtsp_stays_rtsp(self):
        source = go2rtc.resolve_source(make_data(capture_source_url="rtsp://cam.example/live"))
        self.assertEqual(source.kind, "rtsp")
        self.assertEqual(go2rtc.source_url(source), "rtsp://cam.example/live")

    def test_snapshot_only_source_still_renders(self):
        data = make_data()
        data["services"]["camera_snapshot_url"] = "http://printer.example/snap.jpg"
        source = go2rtc.resolve_source(data)
        self.assertEqual(source.kind, "snapshot")
        self.assertIn("http://printer.example/snap.jpg", go2rtc.render_config(source))

    def test_rendered_config_binds_loopback_only(self):
        config = go2rtc.render_config(go2rtc.resolve_source(make_data()))
        self.assertIn('listen: "127.0.0.1:1984"', config)
        self.assertIn('listen: "127.0.0.1:8554"', config)
        self.assertNotIn("0.0.0.0", config)

    def test_credentials_never_printed_but_config_file_is_0600(self):
        secret_url = "http://user:hunter2@cam.example/webcam/?action=snapshot&api_key=sekrit"
        data = make_data()
        data["services"]["camera_snapshot_url"] = secret_url
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(go2rtc.gate(data), 0)
        self.assertNotIn("hunter2", out.getvalue())
        self.assertNotIn("sekrit", out.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            path = go2rtc.write_config(Path(directory) / "go2rtc.yaml", data)
            # go2rtc needs the raw URL; the file itself is the secret.
            self.assertIn("hunter2", path.read_text())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_check_probes_the_api(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        try:
            server = ThreadingHTTPServer(("127.0.0.1", 1984), Handler)
        except OSError:
            self.skipTest("port 1984 is in use on this host")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            ok, reason = go2rtc.check()
            self.assertTrue(ok, reason)
        finally:
            server.shutdown()
        ok, _ = go2rtc.check(timeout=1)
        self.assertFalse(ok)


class SupervisorGo2rtcGateTests(unittest.TestCase):
    """supervise.sh starts go2rtc only when the gate says so (fake children)."""

    def environment(self, directory, gate_code):
        fake_python = Path(directory, "python3")
        fake_python.write_text(
            "#!/bin/bash\n"
            "case \"$*\" in\n"
            "  *print_buddy.listener_gate*--roster*) printf 'printer1\\n'; exit 0 ;;\n"
            "  *print_buddy.listener_gate*) exit 3 ;;\n"
            "  *print_buddy.webui_gate*) exit 3 ;;\n"
            "  *print_buddy.go2rtc*--write-config*) printf '%s\\n' \"$GO2RTC_TEST_CONFIG\" ;;\n"
            f"  *print_buddy.go2rtc*) exit {gate_code} ;;\n"
            "  *) echo 'unexpected python3 call: $*' >&2; exit 9 ;;\n"
            "esac\n")
        fake_python.chmod(0o755)
        fake_go2rtc = Path(directory, "go2rtc")
        fake_go2rtc.write_text(
            "#!/bin/bash\n"
            "printf '%s\\n' \"$*\" > \"$GO2RTC_TEST_MARKER\"\n"
            "exec sleep 60\n")
        fake_go2rtc.chmod(0o755)
        return {**os.environ, "PATH": directory + ":" + os.environ["PATH"],
                "PRINT_BUDDY_BUNDLED_SPOOLMAN": "false",
                "PRINT_BUDDY__SERVICES__SPOOLMAN_URL": "http://external.invalid:8000",
                "DISCORD_BOT_TOKEN": "",
                "GO2RTC_BIN": str(fake_go2rtc),
                "GO2RTC_TEST_CONFIG": str(Path(directory, "go2rtc.yaml")),
                "GO2RTC_TEST_MARKER": str(Path(directory, "go2rtc-args"))}

    def run_supervisor(self, gate_code):
        directory = tempfile.mkdtemp()
        env = self.environment(directory, gate_code)
        process = subprocess.Popen(["bash", str(ROOT / "docker/supervise.sh")],
                                   env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        return directory, process

    def test_gate_off_idles_without_go2rtc(self):
        directory, process = self.run_supervisor(3)
        try:
            time.sleep(1.5)
            self.assertIsNone(process.poll())
            self.assertFalse(Path(directory, "go2rtc-args").exists())
            process.send_signal(signal.SIGTERM)
            out, _ = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0)
            self.assertIn("go2rtc not started", out)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_gate_on_starts_go2rtc_with_the_generated_config(self):
        directory, process = self.run_supervisor(0)
        marker = Path(directory, "go2rtc-args")
        try:
            for _ in range(100):
                if marker.exists():
                    break
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            self.assertEqual(marker.read_text().strip(),
                             f"-config {Path(directory, 'go2rtc.yaml')}")
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_gate_unresolved_stops_the_container(self):
        directory, process = self.run_supervisor(2)
        out, err = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 2)
        self.assertIn("go2rtc gate failed", err)
        self.assertFalse(Path(directory, "go2rtc-args").exists())


class DeploymentContractTests(unittest.TestCase):
    """Loopback-only, passthrough opt-in, and healthcheck coverage."""

    def test_no_go2rtc_port_is_published_anywhere(self):
        self.assertNotIn("ports", COMPOSE["services"]["combined"])
        for text in (COMPOSE_TEXT, UNRAID_TEXT):
            self.assertNotIn("1984", text)
            self.assertNotIn("8554", text)

    def test_gpu_passthrough_is_commented_opt_in(self):
        service = COMPOSE["services"]["combined"]
        self.assertNotIn("devices", service)
        self.assertNotIn("group_add", service)
        self.assertIn("#   - /dev/dri:/dev/dri", COMPOSE_TEXT)
        self.assertIn("# devices:", COMPOSE_TEXT)

    def test_unraid_device_is_off_by_default_and_documented(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(UNRAID_TEXT)
        self.assertNotIn("--device", root.findtext("ExtraParams"))
        self.assertIn("/dev/dri", UNRAID_TEXT)  # the opt-in note in the header comment
        variables = {c.get("Target"): c for c in root.findall("Config")
                     if c.get("Type") == "Variable"}
        self.assertEqual(variables["PRINT_BUDDY__TIMELAPSE__CAPTURE_ENABLED"].text, "false")
        self.assertIn("PRINT_BUDDY__TIMELAPSE__CAPTURE_SOURCE_URL", variables)

    def test_compose_carries_capture_with_off_default(self):
        environment = COMPOSE["services"]["combined"]["environment"]
        self.assertEqual(environment["PRINT_BUDDY__TIMELAPSE__CAPTURE_ENABLED"],
                         "${PRINT_BUDDY__TIMELAPSE__CAPTURE_ENABLED:-false}")

    def test_healthcheck_covers_go2rtc_only_through_the_gate(self):
        text = (ROOT / "docker/healthcheck.py").read_text()
        self.assertIn("go2rtc.gate()", text)
        self.assertIn("go2rtc.check()", text)
        self.assertIn("go2rtc.binary_present()", text)

    def test_supervise_skips_go2rtc_without_the_binary(self):
        text = (ROOT / "docker/supervise.sh").read_text()
        self.assertIn('go2rtc_bin="${GO2RTC_BIN:-/usr/local/bin/go2rtc}"', text)
        self.assertIn('if [ -x "$go2rtc_bin" ]', text)
        self.assertIn("python3 -m print_buddy.go2rtc", text)


if __name__ == "__main__":
    unittest.main()
