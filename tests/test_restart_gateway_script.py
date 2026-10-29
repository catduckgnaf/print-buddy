"""bin/restart_gateway_after_print.sh must not hard-code the Hermes profile name.

Since #577 the profile name is the operator's choice; the intake folder is
<paths.hermes_home>/state/model-link-intakes, the path the Python side uses
(settings.state_dir), so the script resolves it the same way.
"""
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "bin" / "restart_gateway_after_print.sh"


def test_intake_dir_comes_from_paths_hermes_home_not_a_fixed_profile():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "profiles/3dprinting" not in text
    assert "print_handy.settings get paths.hermes_home" in text
    assert "/state/model-link-intakes" in text
    assert "PRINT_HANDY_INTAKE_DIR" in text  # explicit override still wins
