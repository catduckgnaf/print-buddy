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
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn('"print_buddy.bot"', dockerfile)
        self.assertIn("PRINT_BUDDY__BOT__MODE=standalone", dockerfile)

    def test_docker_examples_use_source_installed_slicer(self):
        for suffix in ("yaml", "toml"):
            with self.subTest(format=suffix):
                config = (ROOT / "config" / f"docker.{suffix}").read_text()
                self.assertIn("/usr/local/bin/orca-slicer", config)
                self.assertNotIn("/opt/orcaslicer/AppRun", config)

    def test_separate_services_and_external_spoolman_default(self):
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        services = compose["services"]
        self.assertIn("bot", services)
        self.assertIn("listener", services)
        self.assertNotIn("spoolman", services)
        for name, module in (("bot", "print_buddy.bot"),
                             ("listener", "print_buddy.hermes.moonraker_event_listener")):
            with self.subTest(service=name):
                service = services[name]
                self.assertEqual(service["command"], ["python3", "-m", module])
                self.assertIn("healthcheck", service)
                self.assertFalse(service.get("depends_on"))
                self.assertFalse(any("/app" in v for v in service["volumes"]))

    def test_configuration_parity_channels_and_packaged_plugins(self):
        import tomllib
        from print_buddy import settings

        configs = [settings.load(local=ROOT / "config" / f"docker.{suffix}", environ={})
                   for suffix in ("yaml", "toml")]
        self.assertEqual(configs[0], configs[1])
        self.assertEqual(configs[0]["services"]["spoolman_url"], "")
        self.assertEqual(configs[0]["orca"]["command"], ["/usr/local/bin/orca-slicer"])
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG APP_CHANNEL=development", dockerfile)
        ignored = (ROOT / ".dockerignore").read_text().splitlines()
        self.assertNotIn("plugins", ignored)
        self.assertIn(".env", ignored)
        self.assertTrue((ROOT / "plugins" / "print-feedback").is_dir())
        extra = yaml.safe_load((ROOT / "docker-compose.spoolman.yml").read_text())
        self.assertIn("spoolman", extra["services"])
        self.assertNotIn("ports", extra["services"]["spoolman"])

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

    def test_orca_is_optional_with_prebuilt_default_and_source_option(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG WITH_ORCA=", dockerfile)
        self.assertNotIn("ARG ORCA_CHANNEL=", dockerfile)
        self.assertEqual(dockerfile.count("FROM orca-base AS orca-"), 3)
        self.assertIn('COPY --from=orca-stable /out/ /', dockerfile)
        self.assertIn('COPY --from=orca-alpha /out/ /', dockerfile)
        entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text()
        self.assertIn("PRINT_BUDDY_ORCA_CHANNEL:-stable", entrypoint)
        self.assertIn("export PB_ORCA_CMD=\"$selected\"", entrypoint)
        self.assertIn("must be 'stable' or 'alpha'", entrypoint)
        runtime = dockerfile.split("AS runtime", 1)[1]
        self.assertIn("openscad", runtime)
        self.assertIn("--no-install-recommends", runtime)
        self.assertIn("ARG ORCA_SOURCE=prebuilt", dockerfile)
        self.assertIn('case "$ORCA_SOURCE" in prebuilt|source)', dockerfile)
        self.assertIn('COPY --from=orca-prebuilt /out/ /', dockerfile)
        self.assertEqual(dockerfile.count('[ "$ORCA_SOURCE" = source ]'), 3)
        prebuilt = (ROOT / "docker" / "orca-prebuilt.sh").read_text()
        self.assertIn("OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage", prebuilt)
        self.assertIn("d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd", prebuilt)
        self.assertIn("sha256sum --check --strict -", prebuilt)
        self.assertLess(prebuilt.index("sha256sum --check"), prebuilt.index("--appimage-extract"))
        self.assertIn("set -eu", prebuilt)
        self.assertIn("--appimage-extract", prebuilt)
        self.assertNotIn("--appimage-extract-and-run", prebuilt)
        self.assertIn("mv squashfs-root /out/opt/orca-stable", prebuilt)
        self.assertIn("exec /opt/orca-stable/AppRun", prebuilt)
        self.assertIn("libopengl0 libglu1-mesa", runtime)
        helper = (ROOT / "docker" / "orca-build.sh").read_text()
        self.assertIn("cmake --build deps/build", helper)
        self.assertIn('cmake --install build', helper)
        self.assertIn("orca-slicer-$channel", helper)
        self.assertIn("ARG ORCA_STABLE_REF=", dockerfile)
        self.assertIn("ARG ORCA_ALPHA_REF=", dockerfile)
        for channel, ref in (("stable", "${ORCA_STABLE_REF}"), ("alpha", "${ORCA_ALPHA_REF}")):
            self.assertRegex(dockerfile, rf"--mount=type=cache,id=print-buddy-orca-\$\{{TARGETARCH\}}-{channel}-\$\{{{ref[2:-1]}\}}-")

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
        self.assertIn("KiCad is not bundled; it remains deferred", docs)
        self.assertIn("Spoolman stays a separate container", docs)

    def test_validation_workflow_builds_both_orca_channels(self):
        workflow = (ROOT / ".github" / "workflows" / "docker-image-validation.yml").read_text()
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertNotIn("      orca_channel:", workflow)
        self.assertNotIn("inputs.orca_channel", workflow)
        self.assertNotIn("ORCA_CHANNEL:", workflow)
        self.assertIn("ORCA_STABLE_REF", workflow)
        self.assertIn("ORCA_ALPHA_REF", workflow)
        self.assertIn("orca-stable", dockerfile)
        self.assertIn("orca-alpha", dockerfile)

    def test_publish_workflow_has_no_orca_revision_selector(self):
        publish_text = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text()
        self.assertNotIn("orca_channel", publish_text)

    def test_ghcr_publisher_is_manual_gated_and_uses_pinned_actions(self):
        workflow = yaml.load((ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(),
                             Loader=yaml.BaseLoader)
        self.assertEqual(list(workflow["on"]), ["workflow_dispatch"])
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["version"]["required"], "true")
        self.assertEqual(inputs["with_orca"]["default"], "true")
        self.assertEqual(inputs["with_bambu"]["default"], "false")
        self.assertEqual(inputs["orca_source"]["default"], "prebuilt")
        self.assertEqual(inputs["orca_source"]["options"], ["prebuilt", "source"])
        # Candidate validation must not authenticate or push without explicit opt-in.
        self.assertEqual(inputs["publish"]["type"], "boolean")
        self.assertEqual(inputs["publish"]["default"], "false")
        steps = workflow["jobs"]["publish"]["steps"]
        acceptance = next(i for i, step in enumerate(steps) if step.get("id") == "acceptance")
        publish = next(i for i, step in enumerate(steps) if step.get("id") == "publish")
        self.assertLess(acceptance, publish)
        publish_gate = "inputs.publish && steps.acceptance.outcome == 'success'"
        self.assertEqual(steps[publish]["if"], publish_gate)
        login = next(step for step in steps
                     if step.get("uses", "").startswith("docker/login-action@"))
        self.assertEqual(login["if"], publish_gate)
        self.assertIn("docker push", steps[publish]["run"])
        self.assertIn("image_acceptance.sh", steps[acceptance]["run"])
        smoke = next(step for step in steps if step.get("name") == "Headless slice with each bundled Orca channel")
        self.assertIn("channels=stable", smoke["run"])
        self.assertIn('if [ "$ORCA_SOURCE" = source ]; then channels="stable alpha"', smoke["run"])
        self.assertIn("--network none", smoke["run"])
        for step in steps:
            if "uses" in step:
                self.assertRegex(step["uses"], r"^[^@]+@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
