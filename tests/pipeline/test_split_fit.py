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
