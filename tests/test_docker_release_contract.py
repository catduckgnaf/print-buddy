"""Issue #117 packaging regressions, runnable without a container engine."""
from pathlib import Path
import os
import shlex
import re
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DockerReleaseContract(unittest.TestCase):
    def test_standalone_is_default_runtime(self):
        """One supervised container: tini, then the supervisor that starts every required process."""
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("PRINT_BUDDY__BOT__MODE=standalone", dockerfile)
        self.assertIn('ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/app/docker/entrypoint.sh", '
                      '"/usr/local/bin/print-buddy-supervise"]', dockerfile)
        self.assertIn('CMD ["python3", "/usr/local/bin/print-buddy-healthcheck"]', dockerfile)
        # The probe is installed outside /app; a script invocation puts the script's
        # own directory on sys.path, so it must add /app itself before importing
        # print_buddy (regression: the combined container could never report healthy).
        probe = (ROOT / "docker" / "healthcheck.py").read_text()
        self.assertLess(probe.index('sys.path.insert(0, "/app")'),
                        probe.index("from print_buddy.bot.health import"))
        supervisor = (ROOT / "docker" / "supervise.sh").read_text()
        # #299: the supervisor starts the printer listener through the
        # listener registry launcher, not a hard-coded domain module.
        for process in ("python3 -m print_buddy.bot", "python3 -m print_buddy.listeners",
                        "python3 -m print_buddy.webui_gate", "python3 -m print_buddy.webui",
                        "uvicorn spoolman.main:app"):
            with self.subTest(process=process):
                self.assertIn(process, supervisor)

    def test_runtime_installs_tools_required_by_shipped_shell_wrappers(self):
        """#236: moonrakerctl uploads with curl and parses with jq; missing tools broke native prints.

        The shipped shell wrappers declare their non-base external tools here. Every
        declared tool must actually be used by its wrapper (so the declaration cannot
        go stale) and must be installed by the runtime stage (so a wrapper gaining a
        new tool dependency without a Dockerfile update fails this test). Tools the
        wrappers use from the Debian base system (bash, coreutils, mawk as awk, tar,
        gzip and util-linux as flock) and python3/xvfb-run, which the runtime stage
        installs for other reasons, are not repeated here.
        """
        wrappers = {
            "bin/moonrakerctl": {"curl", "jq"},
            # Sourced by moonrakerctl for mesh-run.
            "bin/mesh-routine.sh": {"jq"},
            "bin/restart_gateway_after_print.sh": {"curl"},
        }
        dockerfile = (ROOT / "Dockerfile").read_text()
        runtime = dockerfile.split("AS runtime", 1)[1]
        install = re.search(r"apt-get install -y --no-install-recommends\s+(.*?)\s*&& rm -rf",
                            runtime, re.S)
        self.assertIsNotNone(install)
        packages = set(install.group(1).replace("\\", " ").split())
        for wrapper, tools in wrappers.items():
            text = (ROOT / wrapper).read_text()
            for tool in sorted(tools):
                with self.subTest(wrapper=wrapper, tool=tool):
                    self.assertRegex(text, rf"\b{tool}\b")
                    self.assertIn(tool, packages)

    def test_docker_examples_use_source_installed_slicer(self):
        for suffix in ("yaml", "toml"):
            with self.subTest(format=suffix):
                config = (ROOT / "config" / f"docker.{suffix}").read_text()
                self.assertIn("/usr/local/bin/orca-slicer", config)
                self.assertNotIn("/opt/orcaslicer/AppRun", config)

    def test_single_container_with_included_spoolman_api(self):
        """#214: one Compose service runs Print Buddy plus the bundled Spoolman API on loopback."""
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        services = compose["services"]
        # One container runs Print Buddy; the only other service is the
        # optional profile-gated cloudflared sidecar (#311), which runs no
        # Print Buddy code and shares the combined network namespace.
        self.assertEqual(list(services), ["combined", "cloudflared"])
        self.assertEqual(services["cloudflared"]["profiles"], ["live-stream"])
        service = services["combined"]
        self.assertNotIn("command", service)
        self.assertNotIn("ports", service)
        self.assertNotIn("depends_on", service)
        self.assertTrue(service["init"])
        self.assertEqual(service["healthcheck"]["test"], ["CMD", "python3", "/usr/local/bin/print-buddy-healthcheck"])
        self.assertFalse(any(v.split(":")[-1].startswith("/app") for v in service["volumes"]))
        self.assertTrue(any(v.endswith(":/data/spoolman") for v in service["volumes"]))
        env = service["environment"]
        # Bundled API by default; a non-empty external URL in .env wins and nothing is migrated.
        self.assertEqual(env["PRINT_BUDDY__SERVICES__SPOOLMAN_URL"],
                         "${PRINT_BUDDY__SERVICES__SPOOLMAN_URL:-http://127.0.0.1:8000}")
        self.assertEqual(env["SPOOLMAN_HOST"], "${SPOOLMAN_HOST:-127.0.0.1}")
        self.assertEqual(env["SPOOLMAN_DIR_DATA"], "/data/spoolman")
        # Spoolman's backend only: pinned revision, locked deps, no Node build or web UI assets.
        dockerfile = (ROOT / "Dockerfile").read_text()
        stage = dockerfile.split("AS spoolman-build", 1)[1].split("AS runtime", 1)[0]
        self.assertRegex(stage, r"ARG SPOOLMAN_REF=[0-9a-f]{40}\n")
        self.assertIn("uv sync --locked --no-dev", stage)
        self.assertIn("rm -rf .git client client_v2 && mkdir -p client_v2/build", stage)
        self.assertNotRegex(stage, r"\b(npm|node|vite)\b")
        self.assertIn("COPY --from=spoolman-build /opt/spoolman /opt/spoolman", dockerfile)

    def test_configuration_parity_channels_and_packaged_plugins(self):
        import tomllib
        from print_buddy import settings

        configs = [settings.load(local=ROOT / "config" / f"docker.{suffix}", environ={})
                   for suffix in ("yaml", "toml")]
        self.assertEqual(configs[0], configs[1])
        self.assertEqual(configs[0]["services"]["spoolman_url"], "http://127.0.0.1:8000")
        self.assertEqual(configs[0]["orca"]["command"], ["/usr/local/bin/orca-slicer"])
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG APP_CHANNEL=development", dockerfile)
        ignored = (ROOT / ".dockerignore").read_text().splitlines()
        self.assertNotIn("plugins", ignored)
        self.assertIn(".env", ignored)
        self.assertTrue((ROOT / "plugins" / "print-feedback").is_dir())
        # The old opt-in override file is gone: Spoolman lives in the base file (#214).
        self.assertFalse((ROOT / "docker-compose.spoolman.yml").exists())

    def test_entrypoint_selects_stable_by_default_and_alpha_on_request(self):
        script = ROOT / "docker" / "entrypoint.sh"
        with tempfile.TemporaryDirectory(dir=ROOT / ".") as data:
            Path(data, "hermes/state").mkdir(parents=True)
            Path(data, "archive").mkdir()
            Path(data, "records").mkdir()
            Path(data, "cache").mkdir()
            command = ["sh", "-c", "printf \"%s\\n\" \"$PB_ORCA_CMD\""]
            env = {"PATH": os.environ["PATH"], "HOME": data, "PRINT_BUDDY_ORCA_CHANNEL": "alpha"}
            alpha = subprocess.run(["bash", str(script), *command], cwd=data, env=env,
                                   text=True, capture_output=True, check=True)
            self.assertEqual(alpha.stdout.strip(), "/usr/local/bin/orca-slicer-alpha")
            env.pop("PRINT_BUDDY_ORCA_CHANNEL")
            stable = subprocess.run(["bash", str(script), *command], cwd=data, env=env,
                                    text=True, capture_output=True, check=True)
            self.assertEqual(stable.stdout.strip(), "/usr/local/bin/orca-slicer-stable")
            env["PRINT_BUDDY_ORCA_CHANNEL"] = "other"
            invalid = subprocess.run(["bash", str(script), *command], cwd=data, env=env,
                                     text=True, capture_output=True)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("must be 'stable' or 'alpha'", invalid.stderr)

    def test_orca_is_optional_and_prebuilt_only(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG WITH_ORCA=", dockerfile)
        self.assertNotIn("ARG ORCA_CHANNEL=", dockerfile)
        self.assertNotIn("ORCA_SOURCE", dockerfile)
        self.assertNotIn("AS orca-stable", dockerfile)
        self.assertNotIn("AS orca-alpha", dockerfile)
        self.assertFalse((ROOT / "docker" / "orca-build.sh").exists())
        self.assertIn('COPY --from=orca-prebuilt /out/ /', dockerfile)
        entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text()
        self.assertIn("PRINT_BUDDY_ORCA_CHANNEL:-stable", entrypoint)
        self.assertIn("export PB_ORCA_CMD=\"$selected\"", entrypoint)
        self.assertIn("must be 'stable' or 'alpha'", entrypoint)
        runtime = dockerfile.split("AS runtime", 1)[1]
        self.assertIn("openscad", runtime)
        self.assertIn("--no-install-recommends", runtime)
        prebuilt = (ROOT / "docker" / "orca-prebuilt.sh").read_text()
        for pin in ("OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.5.0-alpha.AppImage",
                    "386a5ef38991a4fc32ae2e35ee4261bea43d983683ac675a2c2e2395ab2bc7bb",
                    "3880f2c58ec392ed2bd5938ab31c9c7c496c0eb2",
                    "OrcaSlicer_Linux_AppImage_Ubuntu2404_aarch64_V2.5.0-alpha.AppImage",
                    "b64c705537a80ca0f4a5d0b51fa21d1f789191141f54b7f3599d2f2b9bfad0be"):
            with self.subTest(pin=pin):
                self.assertIn(pin, prebuilt)
        self.assertIn("sha256sum --check --strict -", prebuilt)
        self.assertLess(prebuilt.index("sha256sum --check"), prebuilt.index("--appimage-extract"))
        self.assertIn("set -eu", prebuilt)
        self.assertIn("--appimage-extract", prebuilt)
        self.assertNotIn("--appimage-extract-and-run", prebuilt)
        self.assertIn('mv "squashfs-root" "/out/opt/orca-$channel"', prebuilt)
        self.assertIn("exec /opt/orca-%s/AppRun", prebuilt)
        self.assertIn("libopengl0 libglu1-mesa", runtime)

    def test_bambu_studio_is_optional_pinned_and_built_from_source(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        stage = dockerfile.split("AS bambu-build", 1)[1].split("AS runtime", 1)[0]
        self.assertIn("ARG WITH_BAMBU=false", stage)
        self.assertRegex(stage, r"ARG BAMBU_REF=[0-9a-f]{40}\n")
        self.assertIn("https://github.com/bambulab/BambuStudio.git", stage)
        self.assertIn('test "$(git rev-parse HEAD)" = "$ref"', stage)
        self.assertIn("-DSLIC3R_FHS=ON", stage)
        self.assertNotIn(".AppImage", stage)
        self.assertIn("COPY --from=bambu-build /out/ /", dockerfile)
        for suffix in ("yaml", "toml"):
            self.assertIn("/usr/bin/bambu-studio", (ROOT / "config" / f"docker.{suffix}").read_text())

    def test_documentation_and_app_version_match_the_docker_contract(self):
        docs = (ROOT / "docs" / "DOCKER.md").read_text()
        self.assertIn("PRINT_BUDDY_ORCA_CHANNEL", docs)
        self.assertIn("OpenSCAD (`openscad`) is included", docs)
        self.assertNotIn("KiCad", docs)
        self.assertIn("No Node, npm or web UI assets are built or copied", docs)
        self.assertIn("Default bind is `127.0.0.1:8000` inside the container", docs)

    def test_validation_workflow_records_prebuilt_orca_pins(self):
        workflow = (ROOT / ".github" / "workflows" / "docker-image-validation.yml").read_text()
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertNotIn("      orca_channel:", workflow)
        self.assertNotIn("inputs.orca_channel", workflow)
        self.assertNotIn("ORCA_CHANNEL:", workflow)
        self.assertNotIn("ORCA_STABLE_REF", workflow)
        self.assertNotIn("ORCA_ALPHA_REF", workflow)
        self.assertNotIn("ORCA_SOURCE", workflow)
        self.assertIn("docker/orca-prebuilt.sh", workflow)
        self.assertIn("for channel in stable alpha", workflow)
        self.assertIn("AS orca-prebuilt", dockerfile)
        # The pin counts match the per-arch pin structure: revisions are per
        # channel (2); SHA256 digests and asset names are per arch (4 each).
        self.assertIn("grep -cE 'sha256_(amd64|arm64)=[0-9a-f]{64}' docker/orca-prebuilt.sh", workflow)
        self.assertIn("grep -cE 'asset_(amd64|arm64)=' docker/orca-prebuilt.sh", workflow)

    def test_validation_workflow_offers_both_arches_on_native_runners(self):
        workflow = yaml.load((ROOT / ".github" / "workflows" / "docker-image-validation.yml").read_text(),
                             Loader=yaml.BaseLoader)
        self.assertEqual(list(workflow["on"]), ["workflow_dispatch"])
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["architecture"]["options"], ["amd64", "arm64"])
        self.assertEqual(inputs["architecture"]["default"], "amd64")
        # One image is published (#353): there is no variant input any more.
        self.assertNotIn("variant", inputs)
        job = workflow["jobs"]["validate"]
        # arm64 validates on the native ARM runner, amd64 on the x86 runner.
        self.assertIn("ubuntu-24.04-arm", job["runs-on"])
        self.assertIn("ubuntu-24.04", job["runs-on"])
        self.assertIn("inputs.architecture", job["runs-on"])
        env = job["env"]
        self.assertIn("linux/arm64", env["PLATFORM"])
        self.assertIn("linux/amd64", env["PLATFORM"])
        # The published image's toggles are fixed: Orca and go2rtc in, Bambu out.
        self.assertEqual(env["WITH_ORCA"], "true")
        self.assertEqual(env["WITH_GO2RTC"], "true")
        self.assertEqual(env["WITH_BAMBU"], "false")
        build = next(step for step in job["steps"] if step.get("name") == "Build (no push)")
        self.assertIn('--platform "$PLATFORM"', build["run"])
        self.assertIn("image_acceptance.sh", job["steps"][-2]["run"])
        smoke = next(step for step in job["steps"]
                     if step.get("name") == "Headless slice with each bundled Orca channel")
        # The published image always bundles Orca, so the smoke is unconditional.
        self.assertNotIn("if", smoke)
        for step in job["steps"]:
            if "uses" in step:
                self.assertRegex(step["uses"], r"^[^@]+@[0-9a-f]{40}$")

    def test_publish_workflow_has_no_orca_revision_selector(self):
        publish_text = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text()
        self.assertNotIn("orca_channel", publish_text)

    def test_ghcr_publisher_is_manual_gated_and_uses_pinned_actions(self):
        workflow = yaml.load((ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(),
                             Loader=yaml.BaseLoader)
        self.assertEqual(list(workflow["on"]), ["workflow_dispatch"])
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["version"]["required"], "true")
        self.assertNotIn("orca_source", inputs)
        # The published image's toggles are fixed in the workflow (Orca and
        # go2rtc in, WITH_BAMBU=false), not dispatch inputs.
        self.assertNotIn("with_orca", inputs)
        self.assertNotIn("with_bambu", inputs)
        # Candidate validation must not authenticate or push without explicit opt-in.
        self.assertEqual(inputs["publish"]["type"], "boolean")
        self.assertEqual(inputs["publish"]["default"], "false")
        steps = workflow["jobs"]["build"]["steps"]
        acceptance = next(i for i, step in enumerate(steps) if step.get("id") == "acceptance")
        publish = next(i for i, step in enumerate(steps) if step.get("id") == "publish")
        self.assertLess(acceptance, publish)
        publish_gate = "inputs.publish && steps.acceptance.outcome == 'success'"
        self.assertEqual(steps[publish]["if"], publish_gate)
        login = next(step for step in steps
                     if step.get("uses", "").startswith("docker/login-action@"))
        self.assertEqual(login["if"], publish_gate)
        # Build legs push by digest only; no tag is ever pushed from a leg.
        self.assertIn("push-by-digest=true", steps[publish]["run"])
        self.assertNotIn("docker push", steps[publish]["run"])
        self.assertNotIn("docker tag", steps[publish]["run"])
        self.assertIn("image_acceptance.sh", steps[acceptance]["run"])
        smoke = next(step for step in steps if step.get("name") == "Headless slice with each bundled Orca channel")
        # The published image always bundles Orca, so the smoke is unconditional.
        self.assertNotIn("if", smoke)
        self.assertIn('channels="stable alpha"', smoke["run"])
        self.assertNotIn("ORCA_SOURCE", smoke["run"])
        self.assertIn("--network none", smoke["run"])
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"^[^@]+@[0-9a-f]{40}$")

    def test_publish_matrix_is_native_both_arches_full_image_only(self):
        """#192/#353: linux/amd64 + linux/arm64, one full image, native runners, no QEMU, no arm/v7."""
        workflow = yaml.load((ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(),
                             Loader=yaml.BaseLoader)
        text = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text()
        job = workflow["jobs"]["build"]
        self.assertEqual(job["runs-on"], "${{ matrix.runner }}")
        self.assertEqual(job["timeout-minutes"], "350")  # BaseLoader: scalars are strings
        legs = {leg["arch"]: leg for leg in job["strategy"]["matrix"]["include"]}
        self.assertEqual(set(legs), {"amd64", "arm64"})
        runners = {"amd64": "ubuntu-24.04", "arm64": "ubuntu-24.04-arm"}
        for arch, leg in legs.items():
            with self.subTest(arch=arch):
                self.assertEqual(leg["runner"], runners[arch])
                self.assertEqual(leg["platform"], f"linux/{arch}")
                self.assertNotIn("variant", leg)
        # The image toggles are fixed at job level: Orca and go2rtc in, Bambu out.
        self.assertEqual(job["env"]["WITH_ORCA"], "true")
        self.assertEqual(job["env"]["WITH_GO2RTC"], "true")
        self.assertEqual(job["env"]["WITH_BAMBU"], "false")
        self.assertNotIn("arm/v7", text)
        self.assertNotIn("setup-qemu", text.lower())
        self.assertNotIn("-light", text)
        build = next(step for step in job["steps"] if step.get("name") == "Build image once (no push)")
        self.assertIn('--platform "$PLATFORM"', build["run"])
        self.assertIn('--load -t "$LOCAL_IMAGE"', build["run"])

    def test_publish_manifest_job_combines_accepted_digests_into_the_two_tags(self):
        workflow = yaml.load((ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(),
                             Loader=yaml.BaseLoader)
        manifest = workflow["jobs"]["manifest"]
        # Publication only, gated on every build leg (each leg is itself
        # acceptance-gated before its digest push).
        self.assertEqual(manifest["needs"], "build")
        self.assertEqual(manifest["if"], "inputs.publish")
        create = next(step for step in manifest["steps"]
                      if step.get("name") == "Create and push the multi-arch manifests")
        run = create["run"]
        self.assertIn("docker buildx imagetools create", run)
        for tag in ('"$IMAGE:$PUBLISH_VERSION"', '"$IMAGE:latest"'):
            with self.subTest(tag=tag):
                self.assertIn(f"-t {tag}", run)
        for digest_var in ("full_amd64", "full_arm64"):
            with self.subTest(digest=digest_var):
                self.assertIn(f'"$IMAGE@${digest_var}"', run)
        self.assertNotIn("-light", run)
        # Manifest digests land in the step summary and the evidence.
        self.assertIn("GITHUB_STEP_SUMMARY", run)
        self.assertIn("evidence/manifests.txt", run)
        download = manifest["steps"][0]
        self.assertTrue(download["uses"].startswith("actions/download-artifact@"))
        self.assertEqual(download["with"]["pattern"], "digest-*")

    def test_no_light_variant_and_no_orca_build_still_fails_closed(self):
        """#353: no workflow publishes or validates a -light image any more.

        A locally built WITH_ORCA=false image (a build option, not a shipped
        variant) keeps the existing no-Orca behaviour: non-slicing commands
        run, slicing fails closed (tests/docker/image_probe.py proves no
        G-code is written).
        """
        for name in ("docker-publish.yml", "nightly.yml", "docker-image-validation.yml"):
            with self.subTest(workflow=name):
                text = (ROOT / ".github" / "workflows" / name).read_text()
                self.assertNotIn("-light", text)
                self.assertNotIn("variant", text)
        docs = (ROOT / "docs" / "DOCKER.md").read_text()
        self.assertIn("WITH_ORCA=false", docs)
        self.assertIn("WITH_BAMBU=false", docs)
        probe = (ROOT / "tests" / "docker" / "image_probe.py").read_text()
        self.assertIn("FileNotFoundError", probe)
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("openscad", dockerfile.split("AS runtime", 1)[1])


if __name__ == "__main__":
    unittest.main()
