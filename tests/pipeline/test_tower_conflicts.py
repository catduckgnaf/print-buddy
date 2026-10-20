"""Regression tests for Orca -101 "G-code conflicts detected" on mapped multicolor slices."""
import inspect
import json
import re
import zipfile

from print_buddy.core import color_geometry
from print_buddy.core import orca_adapter
from . import test_color_geometry as tcg
from print_buddy.core.color_geometry import export_color_geometry, prime_tower_candidates


@tcg.needs_coupon
def test_overlapping_parts_of_one_build_item_export_as_one_object(tmp_path):
    # Separate Orca objects whose footprints touch fail Orca's path-conflict check.
    src = tcg.ROOT / 'three/three_core_geometry.3mf'
    st = json.loads(tcg.STATE.read_text())
    mapping, report = export_color_geometry(src, tmp_path / 'out.3mf', tcg.decisions(src, st))
    with zipfile.ZipFile(tmp_path / 'out.3mf') as z:
        items = re.findall(r'<(?:\w+:)?item ', z.read('3D/3dmodel.model').decode())
    assert len(report['parts']) == 3
    assert len(items) == 1


def test_tower_candidates_clear_parts_and_are_spread():
    postit = [[[112.5, 196.5], [113.0, 144.5], [0, 84]], [[24.0, 100.4], [19.5, 105.0], [0, 1.4]],
              [[23.5, 99.9], [115.8, 201.3], [0, 1.5]], [[112.3, 188.7], [18.7, 104.2], [0, 1.4]]]
    towers = prime_tower_candidates(postit)
    assert towers[0] == color_geometry.prime_tower_xy(postit)
    assert len(towers) >= 2
    tw, m = color_geometry.TOWER_MM, color_geometry.TOWER_MARGIN_MM
    for x, y in towers:
        assert color_geometry.TOWER_EDGE_MM <= x <= 220 - tw - color_geometry.TOWER_EDGE_MM
        for (x0, x1), (y0, y1), _ in postit:
            assert not (x < x1 + m and x + tw > x0 - m and y < y1 + m and y + tw > y0 - m)
    for i, a in enumerate(towers):
        for b in towers[i + 1:]:
            assert abs(a[0] - b[0]) >= 20 or abs(a[1] - b[1]) >= 20


def test_mapped_slice_never_auto_arranges_and_retries_tower_on_conflict():
    body = inspect.getsource(orca_adapter.slice_model)
    arrange = re.search(r"\['--arrange', '0', '--orient', '0'\] if \((.*?)\) else", body).group(1)
    assert 'mapped_profile' in arrange  # #77 renamed the multi-tool flag
    assert "_orca_conflict(folder)" in body and "prime_tower_candidates_mm" in body
    assert '--no-check' not in body


def test_conflict_detector_reads_result_json(tmp_path):
    assert not orca_adapter._orca_conflict(tmp_path)
    (tmp_path / 'result.json').write_text(json.dumps({'error_string': ' G-code conflicts detected after slicing.'}))
    assert orca_adapter._orca_conflict(tmp_path)
    (tmp_path / 'result.json').write_text(json.dumps({'error_string': 'Success.'}))
    assert not orca_adapter._orca_conflict(tmp_path)


def test_orca_failure_details_include_conflicting_object_names(tmp_path):
    (tmp_path / 'result.json').write_text(json.dumps({
        'return_code': -101,
        'error_string': 'G-code conflicts detected after slicing.',
    }))
    (tmp_path / '00000.log').write_text(
        'debug: gcode path conflicts found between WipeTower and 通用-圆柱体.\n'
    )

    details = orca_adapter._orca_failure_details(tmp_path)

    assert 'return_code -101' in details
    assert 'conflicting objects: WipeTower and 通用-圆柱体' in details
