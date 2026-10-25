"""Unit tests for offline full-size split planning."""
import sys
import zipfile
from pathlib import Path

from print_buddy.core import split_fit  # noqa: E402
from print_buddy.core import plate_merge  # noqa: E402
from .test_plate_merge import _source  # noqa: E402


def _mesh_source(path, meshes, plates):
    """A 3MF from explicit vertex lists: meshes {object_id: [(x, y, z), ...]}.

    Same package shape as test_plate_merge._source, but the mesh vertices are
    the caller's, so non-rectangular footprints (whose bounding rectangle is
    larger than the mesh ever occupies) can be tested honestly.
    """
    resources, items, objects = [], [], []
    for oid, points in meshes.items():
        body = ''.join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in points)
        model = (f'<model unit="millimeter"><resources><object id="1"><mesh><vertices>{body}</vertices>'
                 f'<triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources></model>')
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr(f'3D/Objects/object_{oid}.model', model)
        resources.append(f'<object id="{oid}" name="Part {oid}"><components><component p:path="/3D/Objects/object_{oid}.model" objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object>')
        items.append(f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 {20 + 5 * int(oid)} 30 0"/>')
        objects.append(f'<object id="{oid}"><metadata key="name" value="Part {oid}"/><metadata key="extruder" value="1"/><part id="1"><metadata key="name" value="Part {oid}"/><metadata key="extruder" value="1"/></part></object>')
    plate_xml = ''.join(
        f'<plate><metadata key="plater_id" value="{i}"/>' +
        ''.join(f'<model_instance><metadata key="object_id" value="{o}"/></model_instance>' for o in ids) + '</plate>'
        for i, ids in enumerate(plates, 1))
    with zipfile.ZipFile(path, 'a') as archive:
        archive.writestr('3D/3dmodel.model', f'<model xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" unit="millimeter"><resources>{"".join(resources)}</resources><build>{"".join(items)}</build></model>')
        archive.writestr('Metadata/model_settings.config', f'<config>{"".join(objects)}{plate_xml}</config>')
        archive.writestr('Metadata/project_settings.config', '{\n  "filament_colour": [\n    "#FFFFFF"\n  ],\n  "filament_type": [\n    "PLA"\n  ]\n}')
        archive.writestr('3D/_rels/3dmodel.model.rels', '<Relationships>' + ''.join(f'<Relationship Target="/3D/Objects/object_{o}.model" Id="r{o}"/>' for o in meshes) + '</Relationships>')
        for i in range(1, len(plates) + 1):
            archive.writestr(f'Metadata/plate_{i}.png', b'png')


def _rect_points(w, d, h):
    corners = [(0, 0), (w, 0), (w, d), (0, d)]
    return [(x, y, 0) for x, y in corners] + [(x, y, h) for x, y in corners]


def _plus_points(half_length=115, half_arm=20, h=10):
    outline = [(half_arm, half_length), (-half_arm, half_length), (-half_arm, half_arm),
               (-half_length, half_arm), (-half_length, -half_arm), (-half_arm, -half_arm),
               (-half_arm, -half_length), (half_arm, -half_length), (half_arm, -half_arm),
               (half_length, -half_arm), (half_length, half_arm), (half_arm, half_arm)]
    return [(x, y, 0) for x, y in outline] + [(x, y, h) for x, y in outline]


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


def test_split_plan_gives_a_yaw_only_part_its_own_turned_plate(tmp_path):
    # A part that only fits when turned in the bed plane is offered a split
    # plan now: it sits alone on its own plate and the plan records the exact
    # yaw slicing must apply, instead of no plan at all (#76 follow-up to #191).
    source = tmp_path / 'yaw-only.3mf'
    _source(source, {'1': (230, 50, 20), '2': (150, 150, 10)}, [['1', '2']])
    plan = split_fit.split_plan_100(source, 220)
    assert plan is not None
    assert sorted(plan['plates']) == [['1:1'], ['2:1']]
    (row,) = [r for r in split_fit.per_part_fit(source, 220) if r['object_id'] == '1']
    assert plan['yaw_by_object'] == {'1': row['best_yaw_deg']}
    assert 0 < plan['yaw_by_object']['1'] < 90
    # The turned part never shares its plate, and no other part is turned.
    turned_plate = next(plate for plate in plan['plates'] if '1:1' in plate)
    assert turned_plate == ['1:1']


def test_split_plan_without_yaw_records_no_yaw(tmp_path):
    source = tmp_path / 'two-boxes.3mf'
    _source(source, {'1': (150, 150, 10), '2': (150, 150, 10)}, [['1', '2']])
    plan = split_fit.split_plan_100(source, 220)
    assert plan is not None and 'yaw_by_object' not in plan


def test_split_plan_yaw_does_not_cure_the_issue_76_stand(tmp_path):
    # The retained Stand fits at no yaw, so a yaw-aware plan still refuses it.
    source = tmp_path / 'stand.3mf'
    _source(source, {'1': (130, 230, 30), '2': (150, 150, 10)}, [['1', '2']])
    assert split_fit.split_plan_100(source, 220) is None


def test_fit_choice_rows_carry_the_split_yaw():
    from print_buddy.core.prepared_intake import fit_choice_rows
    rows = fit_choice_rows({'scales': [], 'rotations': [],
                            'split_plan': {'plates': [['1:1'], ['2:1']],
                                           'yaw_by_object': {'1': 43.0}}})
    (split,) = [row for row in rows if row['kind'] == 'split']
    assert split['yaw_by_object'] == {'1': 43.0}
    assert split['plates'] == [['1:1'], ['2:1']]


def _split_job(tmp_path, source, plan):
    import json

    from .test_plate_merge import _job
    job_path = _job(tmp_path, source)
    data = json.loads(job_path.read_text())
    data['full_size_split_plan'] = plan
    job_path.write_text(json.dumps(data))
    return job_path


def test_slicing_a_yaw_split_applies_the_recorded_turn_to_its_plate(tmp_path, monkeypatch):
    import json

    from print_buddy.core import model_job, orca_adapter
    from .test_plate_merge import _fake_slice
    source = tmp_path / 'yaw.3mf'
    _source(source, {'1': (230, 50, 20), '2': (150, 150, 10)}, [['1', '2']])
    plan = split_fit.split_plan_100(source, 220)
    assert plan and plan['yaw_by_object']
    job_path = _split_job(tmp_path, source, plan)
    fake = _fake_slice()
    monkeypatch.setattr(orca_adapter, 'slice_model', fake)
    paths = model_job.slice_job(job_path)
    assert len(paths) == 2 and len(fake.calls) == 2
    saved = json.loads(job_path.read_text())
    by_plate = {row['plate_id']: row for row in saved['derived_plates']}
    turned = next(row for row in saved['derived_plates'] if row['part_keys'] == ['1:1'])
    assert turned['yaw_deg'] == plan['yaw_by_object']['1']
    # The derived plate was exported with the turn, not as authored: its
    # reported fit carries the rotation and its placed bounds fit the bed.
    fit = turned['plate_report']['fit']
    assert fit['scale'] == 1.0 and fit['rotation'] is not None
    placed = turned['plate_report']['placed_bounds_mm']
    assert all(0 <= low and high <= 220 for low, high in placed)
    other = next(row for row in saved['derived_plates'] if row['part_keys'] == ['2:1'])
    assert 'yaw_deg' not in other and 'fit' not in other['plate_report']
    assert by_plate[turned['plate_id']] is turned


def test_slicing_refuses_a_turn_recorded_for_a_shared_plate(tmp_path, monkeypatch):
    import pytest

    from print_buddy.core import model_job, orca_adapter
    from .test_plate_merge import _fake_slice
    source = tmp_path / 'shared.3mf'
    _source(source, {'1': (150, 150, 10), '2': (150, 150, 10)}, [['1', '2']])
    plan = {'plates': [['1:1', '2:1']], 'yaw_by_object': {'1': 30.0}}
    job_path = _split_job(tmp_path, source, plan)
    monkeypatch.setattr(orca_adapter, 'slice_model', _fake_slice())
    with pytest.raises(RuntimeError, match='not that part alone'):
        model_job.slice_job(job_path)


def test_per_part_fit_judges_a_plus_part_by_its_mesh_not_its_rectangle(tmp_path):
    # A plus/cross part spans 230 x 230 mm, so its bounding rectangle fits the
    # 204 mm usable bed at no yaw; the actual mesh, turned 45 degrees, occupies
    # about 191 x 191 mm and does fit (#221). Rectangle evaluation blocked it.
    source = tmp_path / 'plus.3mf'
    _mesh_source(source, {'1': _plus_points(), '2': _rect_points(150, 150, 10)}, [['1', '2']])
    rows = {row['object_id']: row for row in split_fit.per_part_fit(source, 220)}
    plus = rows['1']
    assert plus['extent_mm'] == [230.0, 230.0, 10]
    assert plus['fits_authored'] is False
    rect_yaw, rect_env = split_fit.best_yaw(230, 230, 204, 204)
    assert max(rect_env) > 204  # the old rectangle verdict: blocking
    assert plus['fits_full_size'] is True
    assert plus['best_yaw_deg'] == 45.0
    assert max(plus['best_extent_mm'][:2]) <= 204
    # And the split plan can use that verdict, with the turn recorded (#220).
    plan = split_fit.split_plan_100(source, 220)
    assert plan is not None and plan['yaw_by_object'] == {'1': 45.0}
    assert next(plate for plate in plan['plates'] if '1:1' in plate) == ['1:1']


def test_per_part_fit_rectangle_mesh_matches_the_rectangle_sweep(tmp_path):
    # For a truly rectangular mesh the vertex-extrema sweep must agree with
    # the rectangle sweep exactly: rectangular verdicts do not change (#221).
    source = tmp_path / 'rect.3mf'
    _mesh_source(source, {'1': _rect_points(230, 50, 20)}, [['1']])
    (row,) = split_fit.per_part_fit(source, 220)
    yaw, envelope = split_fit.best_yaw(230, 50, 204, 204)
    assert row['best_yaw_deg'] == yaw
    assert row['best_extent_mm'][:2] == [round(envelope[0], 3), round(envelope[1], 3)]
    assert row['fits_full_size'] is True


def test_per_part_fit_exclusion_blocks_when_no_placement_avoids_it(tmp_path):
    # A 200 x 200 mm part fits the 204 mm usable area, but on a bed whose
    # front-left 18 x 28 mm is excluded every legal placement overlaps the
    # exclusion, so it must not count as fitting (#221).
    source = tmp_path / 'nearly-full.3mf'
    _mesh_source(source, {'1': _rect_points(200, 200, 10)}, [['1']])
    (open_row,) = split_fit.per_part_fit(source, 220, exclusions=[])
    assert open_row['fits_full_size'] is True and open_row['placement_mm'] is None
    (row,) = split_fit.per_part_fit(source, 220, exclusions=[(0, 0, 18, 28)])
    assert row['fits_full_size'] is False
    assert row['placement_mm'] is None
    assert 'exclusion' in row['blocking_reason']
    assert row['exclusions_mm'] == [[0.0, 0.0, 18.0, 28.0]]


def test_per_part_fit_exclusion_reports_an_avoiding_placement(tmp_path):
    source = tmp_path / 'small.3mf'
    _mesh_source(source, {'1': _rect_points(100, 50, 10)}, [['1']])
    (row,) = split_fit.per_part_fit(source, 220, exclusions=[(0, 0, 18, 28)])
    assert row['fits_full_size'] is True
    # Placed flush against the exclusion's right edge, on the bed edge.
    assert row['placement_mm'] == [18.0, 8.0]


def test_split_plan_on_an_exclusion_bed_records_avoiding_placements(tmp_path):
    # Stage 2 (#221): the exporter can now realize an avoiding placement, so
    # a plan IS offered on an exclusion bed. Each placed part sits alone (the
    # exporter places a whole plate rigidly) and the plan records the exact
    # placement per_part_fit proved.
    source = tmp_path / 'two-boxes.3mf'
    _mesh_source(source, {'1': _rect_points(150, 150, 10), '2': _rect_points(150, 150, 10)},
                 [['1', '2']])
    rows = {row['object_id']: row for row in split_fit.per_part_fit(source, 220, exclusions=[(0, 0, 18, 28)])}
    assert all(row['fits_full_size'] for row in rows.values())
    plan = split_fit.split_plan_100(source, 220, exclusions=[(0, 0, 18, 28)])
    assert plan is not None
    assert sorted(plan['plates']) == [['1:1'], ['2:1']]
    assert plan['placement_by_object'] == {oid: row['placement_mm'] for oid, row in rows.items()}
    # The recorded placements really avoid the 18 x 28 exclusion.
    for oid, (px, py) in plan['placement_by_object'].items():
        w, d = rows[oid]['best_extent_mm'][:2]
        assert px + w <= 0 or px >= 18 or py + d <= 0 or py >= 28
    # Without exclusions the same source keeps its old plan shape: no placements.
    open_plan = split_fit.split_plan_100(source, 220, exclusions=[])
    assert open_plan is not None and 'placement_by_object' not in open_plan


def test_split_plan_on_an_exclusion_bed_still_blocks_without_a_placement(tmp_path):
    # A part whose footprint fits the usable bed only inside the exclusion
    # has no avoiding placement: it stays blocking (naming the exclusion) and
    # no split plan is offered (#221).
    source = tmp_path / 'blocked.3mf'
    _mesh_source(source, {'1': _rect_points(200, 200, 10), '2': _rect_points(150, 150, 10)},
                 [['1', '2']])
    rows = {row['object_id']: row for row in split_fit.per_part_fit(source, 220, exclusions=[(0, 0, 18, 28)])}
    assert rows['1']['fits_full_size'] is False
    assert 'exclusion' in rows['1']['blocking_reason']
    assert rows['2']['fits_full_size'] is True
    assert split_fit.split_plan_100(source, 220, exclusions=[(0, 0, 18, 28)]) is None


def test_fit_choice_rows_carry_the_split_placement():
    from print_buddy.core.prepared_intake import fit_choice_rows
    rows = fit_choice_rows({'scales': [], 'rotations': [],
                            'split_plan': {'plates': [['1:1'], ['2:1']],
                                           'placement_by_object': {'1': [18.0, 8.0]}}})
    (split,) = [row for row in rows if row['kind'] == 'split']
    assert split['placement_by_object'] == {'1': [18.0, 8.0]}


def test_slicing_an_exclusion_split_lands_the_plate_at_the_recorded_placement(tmp_path, monkeypatch):
    import json

    from print_buddy.core import model_job, orca_adapter
    from .test_plate_merge import _fake_slice
    source = tmp_path / 'placed.3mf'
    _source(source, {'1': (150, 150, 10), '2': (150, 150, 10)}, [['1', '2']])
    plan = split_fit.split_plan_100(source, 220, exclusions=[(0, 0, 18, 28)])
    assert plan and plan['placement_by_object'] == {'1': [18.0, 8.0], '2': [18.0, 8.0]}
    job_path = _split_job(tmp_path, source, plan)
    fake = _fake_slice()
    monkeypatch.setattr(orca_adapter, 'slice_model', fake)
    paths = model_job.slice_job(job_path)
    assert len(paths) == 2 and len(fake.calls) == 2
    saved = json.loads(job_path.read_text())
    for row in saved['derived_plates']:
        assert row['placement_mm'] == [18.0, 8.0]
        placed = row['plate_report']['placed_bounds_mm']
        # The derived plate was exported at the recorded placement, not
        # centered or as authored, and the placed bounds avoid the exclusion.
        assert placed[0][0] == 18.0 and placed[1][0] == 8.0
        assert placed[0][1] == 168.0 and placed[1][1] == 158.0
        assert row['plate_report']['placement_mm'] == [18.0, 8.0]


def test_slicing_refuses_a_placement_recorded_for_a_shared_plate(tmp_path, monkeypatch):
    import pytest

    from print_buddy.core import model_job, orca_adapter
    from .test_plate_merge import _fake_slice
    source = tmp_path / 'shared.3mf'
    _source(source, {'1': (150, 150, 10), '2': (150, 150, 10)}, [['1', '2']])
    plan = {'plates': [['1:1', '2:1']], 'placement_by_object': {'1': [18.0, 8.0]}}
    job_path = _split_job(tmp_path, source, plan)
    monkeypatch.setattr(orca_adapter, 'slice_model', _fake_slice())
    with pytest.raises(RuntimeError, match='not that part alone'):
        model_job.slice_job(job_path)


def test_slicing_refuses_an_out_of_range_or_unknown_placement(tmp_path, monkeypatch):
    import pytest

    from print_buddy.core import model_job, orca_adapter
    from .test_plate_merge import _fake_slice
    source = tmp_path / 'bad-placement.3mf'
    _source(source, {'1': (150, 150, 10), '2': (150, 150, 10)}, [['1', '2']])
    for bad in ({'1': [220.0, 8.0]}, {'1': [-1.0, 8.0]}, {'9': [18.0, 8.0]}):
        plan = {'plates': [['1:1'], ['2:1']], 'placement_by_object': bad}
        job_path = _split_job(tmp_path, source, plan)
        monkeypatch.setattr(orca_adapter, 'slice_model', _fake_slice())
        with pytest.raises(RuntimeError, match='placement'):
            model_job.slice_job(job_path)


# --- #221 stage 3: brim/feature extents in the fit offer -------------------
# A supplied brim policy is resolved through orca_adapter.required_feature_edge
# against the printer state; Normal Lift keeps the travel sweep at zero so the
# budget below is exactly the brim width.
_BRIM_STATE = {'resolved_hop_types': ['Normal Lift']}
_BRIM_10 = {'type': 'outer_only', 'width_mm': 10.0, 'label': 'Outer-only brim, 10 mm'}


def test_feature_edge_budget_is_zero_without_a_policy_and_includes_travel_sweep():
    assert split_fit._feature_edge_mm() == 0.0
    assert split_fit._feature_edge_mm(state=_BRIM_STATE) == 0.0
    assert split_fit._feature_edge_mm(brim_policy=_BRIM_10, state=_BRIM_STATE) == 10.0
    spiral = {'resolved_hop_types': ['Spiral Lift'], 'z_hop': 0.4, 'travel_slope': 3.0}
    budget = split_fit._feature_edge_mm(brim_policy={'type': 'outer_only', 'width_mm': 5.0},
                                        state=spiral)
    assert 6.21 < budget < 6.22  # 5 mm brim + ~1.215 mm resolved travel sweep


def test_per_part_fit_brim_blocks_a_part_that_fits_only_without_it(tmp_path):
    source = tmp_path / 'brim-tight.3mf'
    _mesh_source(source, {'1': _rect_points(200, 200, 10)}, [['1']])
    (plain,) = split_fit.per_part_fit(source, 220)
    assert plain['fits_full_size'] is True and plain['feature_edge_mm'] == 0.0
    assert plain['usable_mm'] == [204.0, 204.0]
    (row,) = split_fit.per_part_fit(source, 220, brim_policy=_BRIM_10, state=_BRIM_STATE)
    assert row['fits_full_size'] is False
    assert row['feature_edge_mm'] == 10.0
    # Budget applied exactly once: usable = 220 - 2 * (8 edge + 10 brim).
    assert row['usable_mm'] == [184.0, 184.0]
    assert 'brim' in row['blocking_reason'] and 'without a brim' in row['blocking_reason']
    # And its split plan goes with it, while the no-brim plan shape is moot here
    # (a single part has no split plan either way).
    assert split_fit.split_plan_100(source, 220, brim_policy=_BRIM_10, state=_BRIM_STATE) is None


def test_split_plan_brim_blocks_where_no_brim_plan_exists(tmp_path):
    source = tmp_path / 'brim-split.3mf'
    _source(source, {'1': (200, 200, 10), '2': (150, 150, 10)}, [['1', '2']])
    plan = split_fit.split_plan_100(source, 220)
    assert plan is not None and len(plan['plates']) == 2
    assert split_fit.split_plan_100(source, 220, brim_policy=_BRIM_10, state=_BRIM_STATE) is None


def test_per_part_fit_brim_still_fits_with_the_budget_accounted(tmp_path):
    source = tmp_path / 'brim-roomy.3mf'
    _mesh_source(source, {'1': _rect_points(150, 150, 10)}, [['1']])
    (row,) = split_fit.per_part_fit(source, 220, brim_policy=_BRIM_10, state=_BRIM_STATE)
    assert row['fits_full_size'] is True and row['fits_authored'] is True
    assert row['feature_edge_mm'] == 10.0 and row['usable_mm'] == [184.0, 184.0]
    assert row['blocking_reason'] is None


def test_per_part_fit_brim_off_is_unchanged(tmp_path):
    source = tmp_path / 'brim-off.3mf'
    _mesh_source(source, {'1': _rect_points(200, 200, 10)}, [['1']])
    (plain,) = split_fit.per_part_fit(source, 220)
    for kwargs in ({'brim_policy': {'type': 'no_brim', 'width_mm': 0.0}, 'state': _BRIM_STATE},
                   {'state': _BRIM_STATE}):
        (row,) = split_fit.per_part_fit(source, 220, **kwargs)
        assert row['feature_edge_mm'] == 0.0
        for key in ('fits_full_size', 'fits_authored', 'usable_mm', 'best_yaw_deg',
                    'best_extent_mm', 'placement_mm', 'blocking_reason'):
            assert row[key] == plain[key]


def test_per_part_fit_brim_and_exclusion_compose(tmp_path):
    exclusions = [(0, 0, 18, 28)]
    # Placement: the brimmed footprint avoids the exclusion, so the recorded
    # placement is the grown footprint's spot shifted back by the budget.
    source = tmp_path / 'brim-placed.3mf'
    _mesh_source(source, {'1': _rect_points(100, 50, 10)}, [['1']])
    (row,) = split_fit.per_part_fit(source, 220, exclusions=exclusions,
                                    brim_policy={'type': 'outer_only', 'width_mm': 5.0},
                                    state=_BRIM_STATE)
    assert row['fits_full_size'] is True and row['feature_edge_mm'] == 5.0
    assert row['placement_mm'] == [23.0, 13.0]
    px, py = row['placement_mm']
    assert px - 5.0 >= 18  # the brim itself clears the exclusion's right edge
    # Blocking: a 190 mm part has an avoiding placement without a brim, but the
    # brim budget alone makes it not fit, and the reason names the brim.
    tight = tmp_path / 'brim-exclusion-tight.3mf'
    _mesh_source(tight, {'1': _rect_points(190, 190, 10)}, [['1']])
    (plain,) = split_fit.per_part_fit(tight, 220, exclusions=exclusions)
    assert plain['fits_full_size'] is True and plain['placement_mm'] is not None
    (row,) = split_fit.per_part_fit(tight, 220, exclusions=exclusions,
                                    brim_policy=_BRIM_10, state=_BRIM_STATE)
    assert row['fits_full_size'] is False
    assert 'brim' in row['blocking_reason']
    assert split_fit.split_plan_100(tight, 220, exclusions=exclusions,
                                    brim_policy=_BRIM_10, state=_BRIM_STATE) is None
