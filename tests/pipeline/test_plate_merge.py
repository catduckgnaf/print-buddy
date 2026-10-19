"""Offline tests for one-bed merging of multi-plate 3MF sources."""
import json
import re
import zipfile
from pathlib import Path

import pytest

from print_buddy.core import model_job
from print_buddy.core import plate_merge
from print_buddy.core import source_colors

STATE = Path(__file__).parent / 'fixtures' / 'printer_hardware.json'


def _box(w, d, h):
    pts = [(0, 0, 0), (w, 0, 0), (0, d, 0), (0, 0, h)]
    body = ''.join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in pts)
    return f'<model unit="millimeter"><resources><object id="1"><mesh><vertices>{body}</vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources></model>'


def _source(path, sizes, plates, notes=None):
    """sizes {object_id: (w, d, h)}; plates [[object ids], ...]. All objects use extruder 1."""
    resources, items, objects = [], [], []
    for oid, (w, d, h) in sizes.items():
        resources.append(f'<object id="{oid}" name="Part {oid}"><components><component p:path="/3D/Objects/object_{oid}.model" objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object>')
        items.append(f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 {20 + 5 * int(oid)} 30 0"/>')
        objects.append(f'<object id="{oid}"><metadata key="name" value="Part {oid}"/><metadata key="extruder" value="1"/><part id="1"><metadata key="name" value="Part {oid}"/><metadata key="extruder" value="1"/></part></object>')
    plate_xml = ''.join(
        f'<plate><metadata key="plater_id" value="{i}"/>' +
        ''.join(f'<model_instance><metadata key="object_id" value="{o}"/></model_instance>' for o in ids) + '</plate>'
        for i, ids in enumerate(plates, 1))
    meta = f'<metadata name="Description">{notes}</metadata>' if notes else ''
    with zipfile.ZipFile(path, 'w') as archive:
        for oid, size in sizes.items():
            archive.writestr(f'3D/Objects/object_{oid}.model', _box(*size))
        archive.writestr('3D/3dmodel.model', f'<model xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" unit="millimeter">{meta}<resources>{"".join(resources)}</resources><build>{"".join(items)}</build></model>')
        archive.writestr('Metadata/model_settings.config', f'<config>{"".join(objects)}{plate_xml}</config>')
        archive.writestr('Metadata/project_settings.config', '{\n  "filament_colour": [\n    "#FFFFFF"\n  ],\n  "filament_type": [\n    "PLA"\n  ]\n}')
        archive.writestr('3D/_rels/3dmodel.model.rels', '<Relationships>' + ''.join(f'<Relationship Target="/3D/Objects/object_{o}.model" Id="r{o}"/>' for o in sizes) + '</Relationships>')
        for i in range(1, len(plates) + 1):
            archive.writestr(f'Metadata/plate_{i}.png', b'png')


def _job(tmp_path, source, plate_mode=None):
    state = json.loads(STATE.read_text())
    manifest = source_colors.inventory(source)
    white = model_job.resolve_filament_selection(state, dict(state['ifs_slots']['1'], slot=1))
    job = {'downloaded_file': str(source), 'audit': {'plates': len(set(re.findall(r'plate_(\d+)\.png', ' '.join(zipfile.ZipFile(source).namelist()))))},
           'color_decisions': {'schema': 'part_slots_v1', 'mode': 'single_color', 'source_sha256': manifest['source_sha256'], 'selection': white}}
    if plate_mode:
        job['plate_mode'] = plate_mode
    path = tmp_path / 'JOB.json'
    path.write_text(json.dumps(job))
    return path


def _fake_slice(estimate='2h 10m 0s'):
    calls = []

    def fake(source, folder, state, brim=None, first_layer=False, color_decisions=None, preserve_layout=False, filament_slot=None, item_shifts=None):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source) as archive:
            model = archive.read('3D/3dmodel.model').decode()
        printable = re.findall(r'<item objectid="(\d+)"[^>]*printable="1"', model)
        slot = state['ifs_slots'][str(filament_slot)]
        out = folder / 'plate_1.gcode'
        labels = ''.join(f'; printing object Part {o} id:{i} copy 0\n' for i, o in enumerate(printable))
        out.write_text(f'; filament_colour = {slot["hex"]}\n; nozzle_diameter = 0.4\n; estimated printing time (normal mode) = {estimate}\n'
                       f'M190 S{state["temps_c"]["bed"]}\nM104 S{state["temps_c"]["nozzle"]} T0\n'
                       f'START_PRINT BED_TEMP={state["temps_c"]["bed"]} EXTRUDER_TEMP={state["temps_c"]["nozzle"]}\n{labels}G1 X10 Y10 Z0.2\nEND_PRINT\n')
        calls.append({'source': str(source), 'printable': printable, 'slot': filament_slot, 'item_shifts': item_shifts})
        return out, {'slot': filament_slot}, []
    fake.calls = calls
    return fake


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(model_job.printer_state, 'check', lambda *a, **k: (_ for _ in ()).throw(AssertionError('slice contacted the printer')))


def test_fits_is_merged_into_one_gcode_with_every_object(tmp_path, monkeypatch):
    source = tmp_path / 's.3mf'
    _source(source, {'1': (60, 40, 10), '2': (50, 50, 8), '3': (30, 30, 5)}, [['1', '2'], ['3']])
    job_path = _job(tmp_path, source)
    fake = _fake_slice()
    monkeypatch.setattr('print_buddy.core.orca_adapter.slice_model', fake)
    out = model_job.slice_job(job_path)
    saved = json.loads(job_path.read_text())
    assert isinstance(out, (str, Path)) and len(fake.calls) == 1
    assert sorted(fake.calls[0]['printable']) == ['1', '2', '3']
    merge = saved['plate_merge']
    assert (merge['mode'], merge['plates_in'], merge['objects_in'], merge['objects_out'], merge['fits_bed']) == ('merge', 2, 3, 3, True)
    assert 'derived_plates' not in saved and saved['gcode_verified'] is True
    # spacing between every pair of placed footprints
    boxes = list(merge['placed_bounds_mm'].values())
    for i, a in enumerate(boxes):
        assert a[0][0] >= plate_merge.EDGE_MARGIN_MM - 1e-6 and a[1][0] >= plate_merge.EDGE_MARGIN_MM - 1e-6
        assert a[0][1] <= 220 - plate_merge.EDGE_MARGIN_MM + 1e-6 and a[1][1] <= 220 - plate_merge.EDGE_MARGIN_MM + 1e-6
        for b in boxes[i + 1:]:
            gap_x = max(b[0][0] - a[0][1], a[0][0] - b[0][1])
            gap_y = max(b[1][0] - a[1][1], a[1][0] - b[1][1])
            assert max(gap_x, gap_y) >= plate_merge.SPACING_MM - 1e-6
    model_job.require_current_artifact(saved, out)


def test_too_big_splits_with_reason_and_still_covers_every_part(tmp_path, monkeypatch):
    source = tmp_path / 's.3mf'
    _source(source, {'1': (150, 150, 10), '2': (150, 150, 10), '3': (30, 30, 5)}, [['1'], ['2', '3']])
    job_path = _job(tmp_path, source)
    fake = _fake_slice()
    monkeypatch.setattr('print_buddy.core.orca_adapter.slice_model', fake)
    paths = model_job.slice_job(job_path)
    saved = json.loads(job_path.read_text())
    assert len(paths) == 2 and len(fake.calls) == 2
    assert saved['plate_merge']['mode'] == 'split' and 'do not fit' in saved['plate_merge']['reason']
    assert sorted(k for row in saved['derived_plates'] for k in row['part_keys']) == ['1:1', '2:1', '3:1']
    model_job.require_current_artifact(saved, paths[1])


def test_estimate_over_twelve_hours_splits_with_reason(tmp_path, monkeypatch):
    source = tmp_path / 's.3mf'
    _source(source, {'1': (40, 40, 10), '2': (40, 40, 10)}, [['1'], ['2']])
    job_path = _job(tmp_path, source)
    seq = iter(['13h 5m 0s', '6h 0m 0s', '6h 0m 0s'])
    calls = []

    def fake(*args, **kwargs):
        calls.append(Path(args[0]).name)
        return _fake_slice(next(seq))(*args, **kwargs)
    monkeypatch.setattr('print_buddy.core.orca_adapter.slice_model', fake)
    paths = model_job.slice_job(job_path)
    saved = json.loads(job_path.read_text())
    assert len(paths) == 2 and calls[0] == 'merged.3mf' and 'merged' not in ''.join(calls[1:])
    assert saved['plate_merge']['mode'] == 'split' and '12 h' in saved['plate_merge']['reason']


def test_author_note_requests_separate_printing(tmp_path, monkeypatch):
    source = tmp_path / 's.3mf'
    _source(source, {'1': (40, 40, 10), '2': (40, 40, 10)}, [['1'], ['2']], notes='Please print the parts separately, one at a time.')
    job_path = _job(tmp_path, source)
    fake = _fake_slice()
    monkeypatch.setattr('print_buddy.core.orca_adapter.slice_model', fake)
    paths = model_job.slice_job(job_path)
    saved = json.loads(job_path.read_text())
    assert len(paths) == 2
    assert 'author notes' in saved['plate_merge']['reason']


def test_explicit_separate_mode_skips_merge(tmp_path, monkeypatch):
    source = tmp_path / 's.3mf'
    _source(source, {'1': (40, 40, 10), '2': (40, 40, 10)}, [['1'], ['2']])
    assert plate_merge.full_size_split_possible(source, source_colors.inventory(source))
    _source(source, {'1': (220, 40, 10), '2': (40, 40, 10)}, [['1'], ['2']])
    assert not plate_merge.full_size_split_possible(source, source_colors.inventory(source))
    _source(source, {'1': (40, 40, 10), '2': (40, 40, 10)}, [['1', '2']])
    assert not plate_merge.full_size_split_possible(source, source_colors.inventory(source))
    _source(source, {'1': (40, 40, 10), '2': (40, 40, 10)}, [['1'], ['2']])
    job_path = _job(tmp_path, source, plate_mode='separate')
    monkeypatch.setattr('print_buddy.core.orca_adapter.slice_model', _fake_slice())
    assert len(model_job.slice_job(job_path)) == 2
    assert json.loads(job_path.read_text())['plate_merge']['reason'] == 'Print parts separately was chosen'


def test_pack_refuses_when_nothing_fits_and_is_deterministic():
    assert plate_merge.pack({'a': (250, 10)}, 220) is None
    assert plate_merge.pack({'a': (100, 100), 'b': (100, 100), 'c': (100, 100)}, 220) is None
    first = plate_merge.pack({'a': (90, 90), 'b': (90, 90), 'c': (40, 40)}, 220)
    assert first == plate_merge.pack({'a': (90, 90), 'b': (90, 90), 'c': (40, 40)}, 220)


def test_missing_object_in_merged_output_is_refused(tmp_path, monkeypatch):
    source = tmp_path / 's.3mf'
    _source(source, {'1': (40, 40, 10), '2': (40, 40, 10)}, [['1'], ['2']])
    job_path = _job(tmp_path, source)
    real = _fake_slice()

    def drop_one(*args, **kwargs):
        out, prov, cfg = real(*args, **kwargs)
        out.write_text(out.read_text().replace('; printing object Part 2 id:1 copy 0\n', ''))
        return out, prov, cfg
    monkeypatch.setattr('print_buddy.core.orca_adapter.slice_model', drop_one)
    with pytest.raises(RuntimeError, match='prints 1 objects but the source has 2'):
        model_job.slice_job(job_path)


def _two_slot_decisions(manifest):
    """Parts 1 and 3 print in slot 1, part 2 in slot 2 (a real multi-slot source)."""
    state = json.loads(STATE.read_text())
    sel = {s: model_job.resolve_filament_selection(state, dict(state['ifs_slots'][s], slot=int(s))) for s in ('1', '2')}
    choices = {}
    for part in manifest['parts']:
        choices['part:' + part['key']] = sel['2'] if part['object_id'] == '2' else sel['1']
    for row in source_colors.canonical_prompts(manifest):
        choices.setdefault(row['key'], choices.get(row['key']) or sel['1'])
    return {'schema': 'part_slots_v1', 'mode': 'per_part', 'source_sha256': manifest['source_sha256'], 'choices': choices}


def test_multi_slot_merge_collapses_plates_and_parks_other_slot(tmp_path):
    """Regression for real Orca -50 (empty plate 2) and -52 (printable=0 item overlapping the bed)."""
    from print_buddy.core import color_geometry
    source = tmp_path / 's.3mf'
    _source(source, {'1': (60, 40, 10), '2': (50, 50, 8), '3': (30, 30, 5)}, [['1'], ['2'], ['3']])
    manifest = source_colors.inventory(source)
    decisions = _two_slot_decisions(manifest)
    keys = [p['key'] for p in manifest['parts'] if p['object_id'] in ('1', '3')]
    shifts = {'1': [0, 0, 0], '3': [80, 0, 0]}
    target = tmp_path / 'slot1.3mf'
    report = color_geometry.export_single_color_plate(source, target, decisions, keys, item_shifts=shifts)
    assert report['slot'] == 1 and report['object_ids'] == ['1', '3'] and report['merged_placement'] is True
    with zipfile.ZipFile(target) as archive:
        settings = archive.read('Metadata/model_settings.config').decode()
        model = archive.read('3D/3dmodel.model').decode()
    # every selected object sits on the single remaining plate; no empty plate is left behind
    assert settings.count('<plate>') == 1
    plate = re.search(r'<plate>.*?</plate>', settings, re.S).group(0)
    assert sorted(re.findall(r'key="object_id" value="(\d+)"', plate)) == ['1', '3']
    assert '"2"' not in plate
    # the slot 2 object is printable=0 and parked outside the 220 mm bed (+50 mm margin)
    items = {m[0]: m[1] for m in re.findall(r'<item objectid="(\d+)"([^>]*)>', model)}
    assert 'printable="1"' in items['1'] and 'printable="1"' in items['3'] and 'printable="0"' in items['2']
    parked_x = float(re.search(r'transform="([^"]+)"', items['2']).group(1).split()[9])
    assert parked_x >= 220 + 50
    # selected shifts applied per object
    x1 = float(re.search(r'transform="([^"]+)"', items['1']).group(1).split()[9])
    x3 = float(re.search(r'transform="([^"]+)"', items['3']).group(1).split()[9])
    assert x3 - x1 == pytest.approx((20 + 5 * 3 + 80) - (20 + 5 * 1))


def test_multi_slot_merge_other_slot_gets_its_own_plate(tmp_path):
    from print_buddy.core import color_geometry
    source = tmp_path / 's.3mf'
    _source(source, {'1': (60, 40, 10), '2': (50, 50, 8), '3': (30, 30, 5)}, [['1'], ['2'], ['3']])
    manifest = source_colors.inventory(source)
    decisions = _two_slot_decisions(manifest)
    key2 = [p['key'] for p in manifest['parts'] if p['object_id'] == '2']
    target = tmp_path / 'slot2.3mf'
    report = color_geometry.export_single_color_plate(source, target, decisions, key2)
    assert report['slot'] == 2 and report['object_ids'] == ['2']
    with zipfile.ZipFile(target) as archive:
        settings = archive.read('Metadata/model_settings.config').decode()
    assert settings.count('<plate>') == 1 and 'value="2"' in settings


def test_multi_slot_item_shifts_must_name_exactly_selected_objects(tmp_path):
    from print_buddy.core import color_geometry
    source = tmp_path / 's.3mf'
    _source(source, {'1': (60, 40, 10), '2': (50, 50, 8)}, [['1'], ['2']])
    manifest = source_colors.inventory(source)
    decisions = _two_slot_decisions(manifest)
    keys = [p['key'] for p in manifest['parts'] if p['object_id'] == '1']
    with pytest.raises(RuntimeError, match='item shifts must name exactly'):
        color_geometry.export_single_color_plate(source, tmp_path / 'x.3mf', decisions, keys, item_shifts={'1': [0, 0, 0], '2': [0, 0, 0]})
