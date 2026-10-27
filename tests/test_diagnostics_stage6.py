"""#390 Stage 6: the Discord action handlers' generic failure posts meet
the operator bar — what failed, the operator detail, the state/remedy
note, and the stable greppable PB_* marker, redacted."""
import importlib.util
import re
from pathlib import Path

PLUGIN_PATH = Path(__file__).parents[1] / "plugins/print-feedback/__init__.py"
SPEC = importlib.util.spec_from_file_location("print_feedback_stage6", PLUGIN_PATH)
assert SPEC is not None and SPEC.loader is not None
plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin)


def test_failure_post_carries_label_detail_note_and_marker():
    post = plugin._failure_post(
        "Stop", RuntimeError("printer did not answer"), "Check the printer screen.",
        subsystem="printer")
    assert post.startswith("Stop failed: printer did not answer. Check the printer screen.")
    assert "Reference: PB_PRINTER_UNKNOWN" in post


def test_failure_post_marker_reflects_the_classified_category():
    post = plugin._failure_post(
        "Next plate", ConnectionError("connection reset"), "Check the printer screen before retrying.",
        subsystem="printer")
    assert "Reference: PB_PRINTER_TRANSIENT" in post
    post = plugin._failure_post(
        "Color selection", RuntimeError("bad profile"), "No slicing, upload or print started.",
        subsystem="intake")
    assert "Reference: PB_INTAKE_UNKNOWN" in post


def test_failure_post_is_redacted():
    post = plugin._failure_post(
        "Stop", RuntimeError("auth failed token=supersecretvalue"), "Check the printer screen.",
        subsystem="printer")
    assert "supersecretvalue" not in post
    assert "***" in post


def test_every_generic_handler_post_uses_the_helper():
    source = PLUGIN_PATH.read_text()
    # The eight audited generic posts (color selection, next plate x2,
    # stop, resume, print again, restart, alert buttons) all route
    # through _failure_post; no bare f-string failure post remains.
    assert len(re.findall(r"_failure_post\(", source)) >= 9  # helper + 8 call sites
    # The only "failed: {exc}" f-strings left are the helper's own and the
    # curated DesignError post (a deliberate, operator-phrased error type,
    # in the same class as the NextPlateError refusals — audited, unchanged).
    assert len(re.findall(r"failed: \{exc\}", source)) == 2
