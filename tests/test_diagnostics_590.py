"""#590: readable chat errors with the real cause, and PH_ markers.

Pins: (1) a missing/expired site token is classified out of UNKNOWN
and its chat post names the site, the credential and the docs section,
with no resend advice and no raw exception text; (2) retry wording is
only offered for transient failures; (3) every user-facing marker is
PH_*; (4) the setup wizard reads PRINT_HANDY_WIZARD_<KEY> presets and
no longer reads PB_<KEY>.
"""
import urllib.error

import pytest

from print_handy import diagnostics
from print_handy.diagnostics import Category

MAKERWORLD_TOKEN_ERROR = RuntimeError(
    "MakerWorld links need an account token in /data/.config/bambu/token; "
    "see docs/PROJECT-REFERENCE.md (MakerWorld account token)")

SITE_TOKEN_ERRORS = [
    (MAKERWORLD_TOKEN_ERROR, "MakerWorld", "MakerWorld account token"),
    (RuntimeError("MakerWorld token empty"), "MakerWorld", "MakerWorld account token"),
    (RuntimeError("Thingiverse links need a free Thingiverse App Token in "
                  "/home/x/.config/thingiverse/token; create an app/token at "
                  "https://www.thingiverse.com/developers"),
     "Thingiverse", "Thingiverse App Token"),
    (RuntimeError("Thingiverse refused the request (401/403), which usually means "
                  "the App Token is missing, invalid or expired"),
     "Thingiverse", "Thingiverse App Token"),
    (RuntimeError("MyMiniFactory links need an API key in /home/x/.config/myminifactory/token; "
                  "create an API key in your MyMiniFactory account"),
     "MyMiniFactory", "MyMiniFactory sign-in"),
    (RuntimeError("MyMiniFactory refused the request (401/403), which usually means "
                  "the API key is missing, invalid or expired"),
     "MyMiniFactory", "MyMiniFactory sign-in"),
    (RuntimeError("Cults3D needs an API key first. Create one at "
                  "https://cults3d.com/en/api/keys and save it as the only content "
                  "of /home/x/.config/cults3d/token in the form nickname:key"),
     "Cults3D", "Cults3D API key"),
    (RuntimeError("Cults3D refused the request (401), which usually means the "
                  "nickname or API key in ~/.config/cults3d/token is wrong"),
     "Cults3D", "Cults3D API key"),
    # #464: the login-token sites' curated messages.
    (RuntimeError("Creality Cloud refused the login token (the site answered \"Invalid "
                  "Token\"), which usually means the token in ~/.config/crealitycloud/token "
                  "is missing, invalid or expired"),
     "Creality Cloud", "Creality Cloud login"),
    (RuntimeError("Thangs downloads need a login token in /home/x/.config/thangs/token (or "
                  "the THANGS_TOKEN environment variable)"),
     "Thangs", "Thangs login token"),
    (RuntimeError("The Nexprint login token in /home/x/.config/nexprint/token has expired."),
     "Nexprint", "Nexprint login token"),
]


def test_makeronline_gap_is_a_known_site_gap():
    from print_handy.core import model_job
    known = diagnostics.known_cause(RuntimeError(model_job.MAKERONLINE_DOWNLOAD_GAP))
    assert known is not None and known.category is Category.CONFIGURATION
    assert "MakerOnline" in known.cause and "browser" in known.remedy


# ---------------------------------------------------------------- markers

def test_markers_use_ph_prefix():
    assert diagnostics.marker("spoolman", Category.TRANSIENT) == "PH_SPOOLMAN_TRANSIENT"
    assert diagnostics.marker("intake", Category.CONFIGURATION) == "PH_INTAKE_CONFIGURATION"
    assert diagnostics.marker("Discord Startup", Category.CONFIGURATION) == \
        "PH_DISCORD_STARTUP_CONFIGURATION"


def test_fixed_markers_use_ph_prefix():
    from print_handy import debug_mode
    assert debug_mode.MARKER == "PH_DEBUG_CONFIGURATION"


# ------------------------------------------------------- known causes

@pytest.mark.parametrize("exc,site,credential", SITE_TOKEN_ERRORS)
def test_site_token_failures_are_known_configuration_causes(exc, site, credential):
    known = diagnostics.known_cause(exc)
    assert known is not None
    assert known.category is Category.CONFIGURATION
    assert diagnostics.classify(exc) is Category.CONFIGURATION
    assert site in known.cause and credential in known.cause
    assert credential in known.remedy and "PROJECT-REFERENCE" in known.remedy
    assert "send the link again" not in known.remedy.lower()
    assert "send it again" not in known.remedy.lower()


def test_robot_check_is_a_transient_known_cause():
    exc = RuntimeError(
        "Thingiverse answered with a Cloudflare robot check (challenge). Open "
        "thingiverse.com in a browser and pass any check there")
    known = diagnostics.known_cause(exc)
    assert known is not None and known.category is Category.TRANSIENT
    assert "robot check" in known.cause and "bypass" in known.remedy


def test_site_download_gaps_are_known_causes_with_a_browser_remedy():
    from print_handy.core import model_job
    for gap in (model_job.MYMINIFACTORY_DOWNLOAD_GAP, model_job.CULTS_DOWNLOAD_GAP):
        known = diagnostics.known_cause(RuntimeError(gap))
        assert known is not None and known.category is Category.CONFIGURATION
        assert "browser" in known.remedy and "upload or drop" in known.remedy


def test_unrecognised_failures_stay_unknown_and_unnamed():
    assert diagnostics.known_cause(RuntimeError("mystery")) is None
    assert diagnostics.classify(RuntimeError("mystery")) is Category.UNKNOWN
    assert diagnostics.classify(RuntimeError("bad profile")) is Category.UNKNOWN


def test_http_error_codes_classify():
    def http(code):
        return urllib.error.HTTPError("https://x", code, "msg", {}, None)
    assert diagnostics.classify(http(401)) is Category.CONFIGURATION
    assert diagnostics.classify(http(403)) is Category.CONFIGURATION
    assert diagnostics.classify(http(429)) is Category.TRANSIENT
    assert diagnostics.classify(http(503)) is Category.TRANSIENT


def test_spoolman_unavailable_is_transient_not_unknown():
    from print_handy.core import spoolman_client
    exc = spoolman_client.SpoolmanUnavailable("connection refused")
    assert diagnostics.classify(exc) is Category.TRANSIENT
    not_configured = spoolman_client.SpoolmanUnavailable(
        "Spoolman is not configured (services.spoolman_url)")
    assert diagnostics.classify(not_configured) is Category.CONFIGURATION


# ---------------------------------------------------------------- posts

def test_known_post_names_the_cause_without_raw_text_or_resend_advice():
    post = diagnostics.known_post(
        "Preparing that model stopped before it was ready.",
        not_happened="Nothing was sliced, uploaded or started.",
        subsystem="intake", exc=MAKERWORLD_TOKEN_ERROR)
    assert post is not None
    assert "MakerWorld" in post and "account token" in post
    assert "MakerWorld account token" in post and "PROJECT-REFERENCE" in post
    assert post.rstrip().endswith("Reference: PH_INTAKE_CONFIGURATION")
    assert "UNKNOWN" not in post
    assert "send the link" not in post.lower() and "again" not in post.lower()
    # The raw exception text (its container path) never reaches chat (#467 pin).
    assert "/data/.config" not in post and "RuntimeError" not in post


def test_known_post_returns_none_for_unrecognised_failures():
    assert diagnostics.known_post("Nope.", subsystem="intake",
                                  exc=RuntimeError("mystery")) is None


def test_next_step_for_only_suggests_retry_when_transient():
    assert diagnostics.next_step_for(
        ConnectionError("reset"), transient="RETRY", other="OTHER") == "RETRY"
    assert diagnostics.next_step_for(
        RuntimeError("mystery"), transient="RETRY", other="OTHER") == "OTHER"
    assert diagnostics.next_step_for(
        MAKERWORLD_TOKEN_ERROR, transient="RETRY", other="OTHER") != "RETRY"


# ------------------------------------------------------------- wizard env

def test_wizard_presets_use_print_handy_wizard_prefix():
    from print_handy import setup_wizard
    wizard = setup_wizard.Wizard(environ={"PRINT_HANDY_WIZARD_DISCORD_CHAT_ID": "42",
                                          "PB_DISCORD_CHAT_ID": "99"})
    assert wizard._preset("discord_chat_id") == "42"
    only_old = setup_wizard.Wizard(environ={"PB_DISCORD_CHAT_ID": "99"})
    assert only_old._preset("discord_chat_id") is None
