"""Contract tests for the post-release surfaces check workflow (#394).

Publishing a release must open exactly one checklist issue — "Post-release
surfaces check: <tag>" — listing the merged PRs in the release range with
surface hints, so docs, the Pages site, the wiki, README/About and the
release notes get an explicit updated / verified-no-change decision per
release. These tests pin that contract: the workflow fires only on a
published release (or a manual dispatch), holds least-privilege
GITHUB_TOKEN permissions, and can never edit code, docs or settings.
The one deliberate secret is DOCS_SYNC_TOKEN, used only by the optional
docs auto-sync dispatch step, which degrades gracefully without it.
"""

import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "post-release-surfaces.yml"


def load_workflow():
    return yaml.load(WORKFLOW_PATH.read_text(), Loader=yaml.BaseLoader)


def run_block():
    return load_workflow()["jobs"]["surfaces"]["steps"][0]["run"]


class PostReleaseSurfacesWorkflowContract(unittest.TestCase):
    def test_triggers_are_release_published_and_dispatch_only(self):
        workflow = load_workflow()
        self.assertEqual(sorted(workflow["on"]), ["release", "workflow_dispatch"])
        self.assertEqual(workflow["on"]["release"], {"types": ["published"]})
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(sorted(inputs), ["tag"])
        self.assertEqual(inputs["tag"]["type"], "string")
        self.assertEqual(inputs["tag"]["required"], "false")

    def test_permissions_are_least_privilege_github_token_only(self):
        workflow = load_workflow()
        self.assertEqual(
            workflow["permissions"],
            {"contents": "read", "issues": "write", "pull-requests": "read"},
        )
        # No job may widen the top-level grant.
        for job in workflow["jobs"].values():
            self.assertNotIn("permissions", job)
        text = WORKFLOW_PATH.read_text()
        self.assertIn("${{ github.token }}", text)
        # The checklist itself uses only the GITHUB_TOKEN above. The single
        # deliberate exception is DOCS_SYNC_TOKEN, read only by the
        # auto-sync dispatch step; no other secret may appear.
        secrets_used = set(re.findall(r"secrets\.([A-Z_]+)", text))
        self.assertEqual(secrets_used, {"DOCS_SYNC_TOKEN"})

    def test_docs_auto_sync_dispatch_is_optional_and_never_fails(self):
        workflow = load_workflow()
        steps = workflow["jobs"]["surfaces"]["steps"]
        self.assertEqual(len(steps), 2)
        dispatch = steps[1]
        # The dispatch runs after the checklist issue step, so its outcome
        # can be recorded on that issue.
        run = dispatch["run"]
        self.assertEqual(dispatch["env"]["DOCS_SYNC_TOKEN"],
                         "${{ secrets.DOCS_SYNC_TOKEN }}")
        self.assertIn("repos/catduckgnaf/print-buddy-docs/dispatches", run)
        self.assertIn("print-buddy-release", run)
        # Missing secret: the skip and the manual remedy are recorded.
        self.assertIn("DOCS_SYNC_TOKEN", run)
        self.assertIn("docs-auto-sync.yml", run)
        # Graceful degradation: the step always exits 0.
        self.assertTrue(run.rstrip().endswith("exit 0"))

    def test_single_checklist_issue_per_release(self):
        text = WORKFLOW_PATH.read_text()
        self.assertIn('issue_title="Post-release surfaces check: $tag"', text)
        run = run_block()
        # The open-issue lookup must precede creation, so a re-run updates
        # the existing checklist instead of opening a duplicate.
        self.assertLess(run.index("issue list"), run.index("issue create"))
        self.assertIn("issue comment", run)

    def test_pr_list_comes_from_the_tag_compare(self):
        run = run_block()
        self.assertIn('compare/$prev...$tag', run)
        # A removed docs page is the #355 case: it must be called out as a
        # page removal, not just another drift line.
        self.assertIn('select(.status == "removed")', run)
        self.assertIn("PAGE REMOVAL", run)

    def test_every_surface_needs_a_decision(self):
        run = run_block()
        for surface in (
            "print-buddy/docs",
            "Pages site",
            "Wiki",
            "README + repo About",
            "Release notes",
            "Unraid CA templates",
            "Discord-facing surfaces",
        ):
            self.assertIn(surface, run)
        self.assertIn("verified-no-change", run)
        # The relationship to the daily Docs sync check is stated, so the
        # two checks complement rather than duplicate each other.
        self.assertIn("Docs sync check", run)


if __name__ == "__main__":
    unittest.main()
