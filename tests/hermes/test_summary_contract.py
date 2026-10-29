import json
import sys
from pathlib import Path

from print_handy.core import discord_color_intake
from print_handy.core import model_job
from print_handy.hermes import print_records
from print_handy.hermes import continuation_contract


def test_sanitized_summary_contract_for_discord_and_homeassistant():
    plan = {
        'parts': [
            {'id': 'frame', 'label': 'Frame', 'quantity': 1, 'completed_quantity': 1,
             'status': 'completed', 'run_id': 1, 'plate_id': 1, 'gcode_file': 'frame.gcode'},
            {'id': 'clip', 'label': 'Clip', 'quantity': 2, 'completed_quantity': 0,
             'run_id': 2, 'plate_id': 3, 'plate_estimate_seconds': 1800, 'gcode_file': 'clip.gcode',
             'filament': {'slot': 1, 'color': 'white', 'material': 'PLA'}},
            {'id': 'lid', 'label': 'Lid', 'quantity': 1, 'completed_quantity': 0,
             'run_id': 3, 'plate_id': 4, 'gcode_file': 'private/path/lid-deadbeef.gcode'},
            {'id': 'blue', 'label': 'Blue alternative', 'alternative_group': 'color', 'selected': False},
        ]
    }
    summary = print_records.format_multipart_summary(plan, 'frame.gcode')
    assert summary is not None
    assert 'Current plate/run finished: Run 1, Plate 1' in summary
    assert 'Next required part: Clip' in summary
    assert 'Clip: 2 remaining' in summary
    assert 'Lid: 1 remaining' in summary
    assert 'Start next plate · bed is clear' in summary
    assert 'require a fresh confirmation for this exact artifact' in summary
    assert 'No automatic advance' in summary
    assert 'deadbeef' not in summary

    contract = continuation_contract.build_continuation_contract(plan, 'frame.gcode')
    assert contract['schema'] == 'print_continuation_v1'
    assert contract['next_part'] == {'label': 'Clip', 'quantity': 2, 'run': 2, 'plate': 3}
    assert contract['start_option']['requires_fresh_exact_artifact_confirmation'] is True
    assert contract['start_option']['automatic_advance'] is False
    encoded = json.dumps(contract)
    assert '192.168.' not in encoded
    assert 'token' not in encoded.casefold()
    assert 'deadbeef' not in encoded
    assert '/private/path' not in encoded


def test_continuation_start_gate_is_exact_fresh_and_single_use():
    gate = continuation_contract.ContinuationStartGate()
    artifact = 'plate-2.gcode'
    token = gate.prepare(artifact)
    started = []

    import pytest
    with pytest.raises(ValueError, match='exact prepared artifact'):
        gate.confirm(token, 'other.gcode', True, started.append)
    # A token is consumed even by an invalid confirmation, so it cannot be replayed.
    with pytest.raises(ValueError, match='already used'):
        gate.confirm(token, artifact, True, started.append)
    assert started == []

    fresh = gate.prepare(artifact)
    with pytest.raises(ValueError, match='bed-clear'):
        gate.confirm(fresh, artifact, False, started.append)
    with pytest.raises(ValueError, match='already used'):
        gate.confirm(fresh, artifact, True, started.append)
    assert started == []

    approved = gate.prepare(artifact)
    assert gate.confirm(approved, artifact, True, started.append) is None
    assert started == [artifact]
    with pytest.raises(ValueError, match='already used'):
        gate.confirm(approved, artifact, True, started.append)
    assert started == [artifact]


def test_continuation_start_gate_rejects_paths_and_consumes_uncertain_start():
    import pytest
    gate = continuation_contract.ContinuationStartGate()
    with pytest.raises(ValueError, match='basename'):
        gate.prepare('/private/path/plate.gcode')

    token = gate.prepare('plate.gcode')
    def uncertain(_artifact):
        raise RuntimeError('start outcome uncertain')
    with pytest.raises(RuntimeError, match='uncertain'):
        gate.confirm(token, 'plate.gcode', True, uncertain)
    with pytest.raises(ValueError, match='already used'):
        gate.confirm(token, 'plate.gcode', True, lambda _: pytest.fail('must not replay'))



def test_filament_label_does_not_name_the_material_twice():
    from print_handy.hermes.discord_print_summary import filament_label
    assert filament_label("Coffee PLA+", "PLA+") == "Coffee PLA+"
    assert filament_label("coffee pla+", "PLA+") == "coffee pla+"
    assert filament_label("PLA+", "PLA+") == "PLA+"
    assert filament_label("Coffee", "PLA+") == "Coffee PLA+"
    assert filament_label("Coffee PLA", "PLA+") == "Coffee PLA PLA+"  # a different material is kept
    assert filament_label("Silk PLA", "LA") == "Silk PLA LA"  # whole-word match only
    assert filament_label(None, "PETG", "?") == "? PETG"
    assert filament_label("", "") == ""


def test_alert_slot_line_names_the_material_once():
    from print_handy.hermes.discord_print_summary import format_confirmed_print
    text = format_confirmed_print(kind="paused", model="clip.gcode", slot=2, color="Coffee PLA+", material="PLA+")
    assert "Slot 2: Coffee PLA+" in text and "PLA+ PLA+" not in text
