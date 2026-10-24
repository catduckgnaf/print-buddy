"""Offline orientation regressions; slicer verification boundary is stubbed explicitly."""
from pathlib import Path
from unittest.mock import patch

from print_buddy.core import orca_adapter as oa


def test_quarter_turn_on_rectangular_bed_is_not_discarded():
    # An authored 210 x 100 footprint cannot fit the 120 mm X dimension,
    # but yaw 90 fits at 100% without changing the bed-contact face.
    points = [(x, y, z) for x in (0., 210.) for y in (0., 100.) for z in (0., 10.)]
    tris = [(points[0], points[1], points[2])]
    state = {'bed_mm': [120, 220], 'max_print_height_mm': 20,
             'resolved_hop_types': ['Normal Lift']}
    with patch.object(oa, 'source_triangles', return_value=tris), \
         patch.object(oa, '_unique_points', return_value=points), \
         patch.object(oa, '_surface_stats', return_value=(1000, 0)), \
         patch.object(oa, 'orca_plate_capacity', return_value=1) as capacity:
        rows = oa.rotation_alternatives(Path('rectangular.stl'), state, authored_max=0.55)
    assert rows, 'A feasible 90-degree bed turn must reach slicer verification'
    assert rows[0]['axis'] == '+Z'
    assert rows[0]['full_size']
    assert not rows[0]['supports']
    assert capacity.called


def test_explicit_brim_is_included_in_rotation_verification():
    # A user-requested brim must constrain rotated options, not just resize options.
    state = {'bed_mm': [220, 220], 'max_print_height_mm': 220,
             'resolved_hop_types': ['Normal Lift'], 'brim_override': 8.0}
    verified_states = []

    def rotations(source, checked_state, authored_max):
        verified_states.append(checked_state)
        return []

    with patch.object(oa, 'verified_scale_choices', return_value=[0.8, 0.65, 0.5]), \
         patch.object(oa, 'rotation_alternatives', side_effect=rotations):
        oa.fit_options(Path('rack.stl'), state)
    assert oa.required_feature_edge(verified_states[0]) == 8.0


def test_full_size_bed_turn_precedes_equally_fitting_face_change():
    points = [(x, y, z) for x in (0., 245.) for y in (0., 44.5) for z in (0., 20.)]
    state = {'bed_mm': [220, 220], 'max_print_height_mm': 220,
             'resolved_hop_types': ['Normal Lift']}
    with patch.object(oa, 'source_triangles', return_value=[(points[0], points[1], points[2])]), \
         patch.object(oa, '_unique_points', return_value=points), \
         patch.object(oa, '_surface_stats', return_value=(4500, 0)), \
         patch.object(oa, 'orca_plate_capacity', return_value=1):
        rows = oa.rotation_alternatives(Path('rack.stl'), state, authored_max=.85)
    assert rows[0]['full_size']
    assert rows[0]['axis'] == '+Z', 'Preserve the authored bed-contact face when full size already fits'
