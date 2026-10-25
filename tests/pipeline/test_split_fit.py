"""Unit tests for offline full-size split planning."""
import sys
from pathlib import Path

from print_buddy.core import split_fit  # noqa: E402
from print_buddy.core import plate_merge  # noqa: E402
from .test_plate_merge import _source  # noqa: E402


def test_two_large_objects_pack_into_two_full_size_plates(tmp_path):
    source = tmp_path / 'two-boxes.3mf'
    _source(source, {'1': (150, 150, 10), '2': (150, 150, 10)}, [['1', '2']])
    plan = split_fit.split_plan_100(source, 220)
    assert plan and len(plan['plates']) == 2
    assert sorted(key for plate in plan['plates'] for key in plate) == ['1:1', '2:1']
    assert all(plate_merge.pack({key: (150, 150)}, 220) is not None for group in plan['plates'] for key in group)


def test_individually_oversized_object_has_no_split_plan(tmp_path):
    source = tmp_path / 'wide-box.3mf'
    _source(source, {'1': (300, 10, 10)}, [['1']])
    assert split_fit.split_plan_100(source, 220) is None


def test_yaw_envelope_is_dimension_preserving():
    w, d = split_fit.yaw_envelope(230, 130, 90)
    assert (round(w, 6), round(d, 6)) == (130, 230)
    w, d = split_fit.yaw_envelope(100, 40, 45)
    assert round(w, 1) == round(d, 1) == 99.0


def test_per_part_fit_names_the_stand_from_issue_76_as_blocking(tmp_path):
    # The retained case from #76: a 130 x 230 mm stand on a 220 mm bed fits at
    # no in-plane yaw, so separate plates are not a remedy for it.
    source = tmp_path / 'stand.3mf'
    _source(source, {'1': (130, 230, 30), '2': (195, 200, 119.8)}, [['1', '2']])
    rows = {row['object_id']: row for row in split_fit.per_part_fit(source, 220)}
    stand, base = rows['1'], rows['2']
    assert stand['fits_full_size'] is False
    assert stand['usable_mm'] == [204.0, 204.0]  # 8 mm edge clearance, applied once per axis
    assert 'exceeds the usable' in stand['blocking_reason']
    assert min(stand['best_extent_mm'][:2]) >= 130 and max(stand['best_extent_mm'][:2]) > 204
    assert base['fits_full_size'] is True
    assert split_fit.split_plan_100(source, 220) is None


def test_per_part_fit_finds_a_yaw_the_authored_extent_misses(tmp_path):
    source = tmp_path / 'long-thin.3mf'
    _source(source, {'1': (230, 50, 20)}, [['1']])
    (row,) = split_fit.per_part_fit(source, 220)
    assert row['fits_authored'] is False
    assert row['fits_full_size'] is True
    assert 0 < row['best_yaw_deg'] < 90
    assert max(row['best_extent_mm'][:2]) <= 204


def test_per_part_fit_uses_the_real_height_limit_not_the_bed_size(tmp_path):
    source = tmp_path / 'tall.3mf'
    _source(source, {'1': (50, 50, 250)}, [['1']])
    (row,) = split_fit.per_part_fit(source, bed=220, height=220)
    assert row['fits_full_size'] is False
    assert 'height 250' in row['blocking_reason']
    assert split_fit.split_plan_100(source, bed=220, height=220) is None
    # A shorter printer limit is honored even on a larger bed.
    (row,) = split_fit.per_part_fit(source, bed=300, height=200)
    assert row['fits_full_size'] is False


def test_fit_options_reports_blocking_parts_before_any_scale(tmp_path, monkeypatch):
    from print_buddy.core import orca_adapter as oa
    source = tmp_path / 'stand.3mf'
    _source(source, {'1': (130, 230, 30)}, [['1']])
    monkeypatch.setattr(oa, 'verified_scale_choices', lambda *a, **k: [])
    monkeypatch.setattr(oa, 'rotation_alternatives', lambda *a, **k: [])
    options = oa.fit_options(source, {'bed_mm': [220, 220], 'max_print_height_mm': 220,
                                      'resolved_hop_types': ['Normal Lift']})
    (part,) = options['parts']
    assert part['fits_full_size'] is False
    assert part['blocking_reason']
    assert options['blocking_parts'] == [part['name']]
    assert 'yaw sweep 0-90 degrees' in part['orientations_checked']


def test_split_plan_stays_conservative_for_yaw_only_parts(tmp_path):
    # A split plan is sliced with authored orientations, so a part that only
    # fits yawed is evaluated and reported by per_part_fit but is not offered
    # a split plan the slicing path cannot realize.
    source = tmp_path / 'yaw-only.3mf'
    _source(source, {'1': (230, 50, 20), '2': (150, 150, 10)}, [['1', '2']])
    assert split_fit.split_plan_100(source, 220) is None
