"""Issue #117 packaging regressions, runnable without a container engine."""
from pathlib import Path
import re
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
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG APP_CHANNEL=development", dockerfile)
        ignored = (ROOT / ".dockerignore").read_text().splitlines()
        self.assertNotIn("plugins", ignored)
        self.assertIn(".env", ignored)
        self.assertTrue((ROOT / "plugins" / "print-feedback").is_dir())
        extra = yaml.safe_load((ROOT / "docker-compose.spoolman.yml").read_text())
        self.assertIn("spoolman", extra["services"])
        self.assertNotIn("ports", extra["services"]["spoolman"])

    def test_orca_is_optional_and_built_from_source(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG WITH_ORCA=", dockerfile)
        self.assertNotIn("ARG ORCA_CHANNEL=", dockerfile)
        self.assertEqual(dockerfile.count("FROM debian:13-slim AS orca-"), 2)
        self.assertIn("COPY --from=orca-stable /out/ /opt/orca-stable/", dockerfile)
        self.assertIn("COPY --from=orca-alpha /out/ /opt/orca-alpha/", dockerfile)
        entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text()
        self.assertIn("PRINT_BUDDY_ORCA_CHANNEL:-stable", entrypoint)
        self.assertIn("orca-slicer", entrypoint)
        runtime = dockerfile.split("AS runtime", 1)[1]
        self.assertRegex(runtime, r"(?m)^\s+openscad(?:\s|\\)")
        self.assertIn("--no-install-recommends", runtime)
        self.assertNotIn(".AppImage", dockerfile)
        self.assertIn("cmake --build", dockerfile)
        self.assertEqual(dockerfile.count("COPY --from=orca-"), 2)
        self.assertIn("test -x /usr/local/bin/orca-slicer-stable", dockerfile)
        self.assertIn("test -x /usr/local/bin/orca-slicer-alpha", dockerfile)
        self.assertIn("ARG ORCA_STABLE_REF=", dockerfile)
        self.assertIn("ARG ORCA_ALPHA_REF=", dockerfile)
        for channel in ("stable", "alpha"):
            self.assertIn(f"--mount=type=cache,id=print-buddy-orca-${{TARGETARCH}}-{channel}-", dockerfile)

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
        self.assertIn("OpenSCAD is included", docs)
        self.assertIn("KiCad is not bundled; it remains deferred", docs)
        self.assertIn("Spoolman stays a separate container", docs)
        from print_buddy import __version__
        self.assertEqual(__version__, "2.0.9")

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
        self.assertEqual(inputs["with_bambu"]["default"], "true")
        steps = workflow["jobs"]["publish"]["steps"]
        acceptance = next(i for i, step in enumerate(steps) if step.get("id") == "acceptance")
        publish = next(i for i, step in enumerate(steps) if step.get("id") == "publish")
        self.assertLess(acceptance, publish)
        self.assertEqual(steps[publish]["if"], "steps.acceptance.outcome == 'success'")
        self.assertIn("docker push", steps[publish]["run"])
        self.assertIn("image_acceptance.sh", steps[acceptance]["run"])
        for step in steps:
            if "uses" in step:
                self.assertRegex(step["uses"], r"^[^@]+@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
