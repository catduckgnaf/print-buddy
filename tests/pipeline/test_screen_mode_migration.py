"""Native screen to screenless (Helix) migration regressions from 2026-10-30.

Each case is a failure Andrew hit after switching an AD5X from the native screen
to screenless ZMod with Helix: the slicer kept the native-era mesh name, and the
calibration mismatch reached chat as an unknown, retryable slicing failure.
"""
import pytest

from print_handy import diagnostics
from print_handy.core import orca_adapter, printer_state, slice_failure

NATIVE_ERA = {'calibration_baseline': {'native_mesh': 'MESH_DATA', 'native_zProbeOffset': 0.025}}


@pytest.mark.parametrize('authority, expected', [
    ({'mode': 'screenless', 'operator_confirmed': True}, 'auto'),
    ({'mode': 'native', 'operator_confirmed': True}, 'MESH_DATA'),
    (None, 'MESH_DATA'),
])
def test_slicer_mesh_follows_the_calibration_mode(authority, expected):
    state = dict(NATIVE_ERA, **({'calibration_authority': authority} if authority else {}))
    assert orca_adapter.start_mesh_profile(state) == expected


def test_invalid_native_mesh_is_still_rejected():
    with pytest.raises(RuntimeError, match='invalid calibration baseline mesh'):
        orca_adapter.start_mesh_profile({'calibration_baseline': {'native_mesh': 'X; M112'}})


def _check_failure(problems):
    return RuntimeError('the printer check did not pass:\n  ' + '\n  '.join(problems))


def test_screenless_with_native_era_authority_is_explained_and_not_retryable():
    problems = printer_state.offset_authority_problems(
        dict(NATIVE_ERA, calibration_authority={'mode': 'native', 'operator_confirmed': True}),
        {'display_off': 1, 'load_zoffset': 1, 'gcode_offsets': {'z': 0.025}}, {})
    assert problems  # the safety check itself stays strict
    exc = _check_failure(problems)
    known = diagnostics.known_cause(exc)
    assert known is not None and 'screenless' in known.cause and '/calibration' in known.remedy
    info = slice_failure.explain(exc)
    assert info.retryable is False
    assert 'could not identify the cause' not in info.plain


def test_native_screen_with_screenless_authority_is_explained_and_not_retryable():
    problems = printer_state.offset_authority_problems(
        dict(NATIVE_ERA, calibration_authority={'mode': 'screenless', 'operator_confirmed': True}),
        {'display_off': 0}, {'leftExtruderOffset': {'zProbeOffset': 0.025}})
    exc = _check_failure(problems)
    info = slice_failure.explain(exc)
    assert info.retryable is False and 'native screen' in info.plain
