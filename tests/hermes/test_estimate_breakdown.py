"""Issue #17: per-plate and per-part estimates, aggregate totals, and the split-plan estimate fields."""
import json

from print_buddy.core import prepared_intake
from print_buddy.hermes import discord_print_summary as summary
from print_buddy.hermes import print_records as records


def _gcode(path, duration, grams):
    path.write_text(f"; estimated printing time (normal mode) = {duration}\n; total filament used [g] = {grams}\nG1 X1\n")
    return str(path)


def _job(tmp_path, copies=1, third_known=True):
    parts = [{'key': 'a', 'name': 'Stand.stl', 'source_extruder': 1, 'volume_mm3': 30000},
             {'key': 'b', 'name': 'Clip.stl', 'source_extruder': 1, 'volume_mm3': 10000, 'author_color': 'Crimson'},
             {'key': 'c', 'name': 'Lid.stl', 'source_extruder': 2},
             {'key': 'd', 'name': 'Base.stl', 'source_extruder': 2}]
    sel = {'a': ('Black', 1), 'b': ('Black', 1), 'c': ('White', 2), 'd': ('White', 2)}
    return {'title': 'Desk set', 'copies': copies, 'color_manifest': {'parts': parts},
            'color_decisions': {'mode': 'per_part', 'choices': {
                k: {'slot': slot, 'color': color, 'material': 'PLA'} for k, (color, slot) in sel.items()}},
            'derived_plates': [
                {'gcode': _gcode(tmp_path / 'p1.gcode', '1h 30m', 40.0), 'plate_id': 1, 'slot': 1, 'part_keys': ['a', 'b']},
                {'gcode': _gcode(tmp_path / 'p2.gcode', '45m', 20.0), 'plate_id': 2, 'slot': 2, 'part_keys': ['c']},
                {'gcode': _gcode(tmp_path / 'p3.gcode', '2h', 10.0) if third_known else str(tmp_path / 'missing.gcode'),
                 'plate_id': 3, 'slot': 2, 'part_keys': ['d']}]}


def test_totals_sum_every_plate_not_plate_one(tmp_path):
    text = summary.format_estimate_breakdown(_job(tmp_path))
    assert "Total: ~4h 15m printing (+~5 min warmup per plate), ~70 g filament" in text
    assert "Plate 1: ~1h 30m" in text and "Plate 2: ~45m" in text and "Plate 3: ~2h 0m" in text


def test_part_grams_are_shares_never_the_repeated_total(tmp_path):
    plates = summary.plate_estimates(_job(tmp_path))
    first = {p['name']: p['filament_g'] for p in plates[0]['parts']}
    assert first == {'Stand': 30.0, 'Clip': 10.0}  # volume split of the 40 g plate
    assert sum(first.values()) == plates[0]['filament_g']
    assert all(p['filament_g'] != plates[0]['filament_g'] for p in plates[0]['parts'])
    text = summary.format_estimate_breakdown(_job(tmp_path))
    assert "Clip (Crimson PLA, ~10 g)" in text and "Stand (Black PLA, ~30 g)" in text  # author color kept


def _single(tmp_path, copies):
    """Single plate job: Orca clones the copies into the plate, so the G-code covers them."""
    return {'title': 'Hook', 'copies': copies, 'filament_selection': {'slot': 1, 'color': 'Black', 'material': 'PLA'},
            'color_manifest': {'parts': [{'key': 'a', 'name': 'Hook.stl', 'source_extruder': 1}]},
            'derived_plates': [{'gcode': _gcode(tmp_path / 'one.gcode', '1h', 12.0), 'plate_id': 1, 'part_keys': ['a']}]}


def test_quantity_change_updates_totals(tmp_path):
    one = summary.format_estimate_breakdown(_single(tmp_path, 1))
    two = summary.format_estimate_breakdown(_single(tmp_path, 2))
    assert "for 2 copies" in two and "for 2 copies" not in one
    assert "Hook x2" in two and "Hook x2" not in one


def test_split_plates_never_claim_copies_their_gcode_lacks(tmp_path):
    # Per part slicing makes one copy per plate whatever was requested; do not promise two.
    text = summary.format_estimate_breakdown(_job(tmp_path, copies=2))
    assert "for 2 copies" not in text and "Stand x2" not in text
    assert "Total: ~4h 15m printing" in text


def test_same_name_in_different_colors_stays_separate(tmp_path):
    job = _job(tmp_path)
    job['color_manifest']['parts'][1]['name'] = 'Stand.stl'  # second part on plate 1 shares the name
    job['color_manifest']['parts'][1].pop('author_color')
    job['color_decisions']['choices']['b']['color'] = 'Red'
    rows = {(p['name'], p['color']): p['filament_g'] for p in summary.plate_estimates(job)[0]['parts']}
    assert rows == {('Stand', 'Black'): 30.0, ('Stand', 'Red'): 10.0}


def test_unknown_estimates_are_labeled_not_zero(tmp_path):
    text = summary.format_estimate_breakdown(_job(tmp_path, third_known=False))
    assert "Plate 3: time unknown" in text
    assert "at least ~2h 15m printing, 1 plate unknown" in text
    assert "at least 60 g filament" in text


def test_model_page_estimate_fills_missing_plate_and_scales_with_copies(tmp_path):
    job = _single(tmp_path, 2)
    job['derived_plates'][0]['gcode'] = str(tmp_path / 'missing.gcode')
    job['selected_source'] = {'plates': [{'prediction_s': 3600, 'weight_g': 8}]}
    plates = summary.plate_estimates(job)
    assert plates[0]['seconds'] == 7200 and plates[0]['basis'] == 'model page' and plates[0]['filament_g'] == 16.0


def test_many_plates_stay_short(tmp_path):
    job = _job(tmp_path)
    job['derived_plates'] = job['derived_plates'][:1] * 14
    text = summary.format_estimate_breakdown(job)
    assert "+4 more plates" in text and len(text) < 1990


def test_split_plan_records_estimates_so_remaining_duration_is_known(tmp_path):
    job = _job(tmp_path)
    jp = tmp_path / 'JOB.json'
    jp.write_text(json.dumps(job))
    manifest = {'parts': job['color_manifest']['parts']}
    gcodes = [r['gcode'] for r in job['derived_plates']]
    plan = prepared_intake.write_split_plan(jp, job, manifest, gcodes, 'intake-est', plans_dir=tmp_path)
    assert [p['plate_estimate_seconds'] for p in plan['parts']] == [5400, 2700, 7200]
    assert [p['estimated_part_seconds'] for p in plan['parts']] == [5400, 2700, 7200]
    assert [p['estimated_filament_g'] for p in plan['parts']] == [40.0, 20.0, 10.0]
    text = records.format_multipart_summary(plan)
    assert "Combined remaining duration: ~4h 15m" in text
