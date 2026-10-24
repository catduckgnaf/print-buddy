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
