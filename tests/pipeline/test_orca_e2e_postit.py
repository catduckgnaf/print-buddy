"""Real OrcaSlicer end to end: the post-it stencil job slices to ONE multicolor G-code (t_07b8d012).

Runs the actual flatpak Orca; never touches the printer (slice_job is disk only).
Skips when Orca or the archived reference model is not on this host.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from print_handy import settings
from print_handy.core import model_job  # noqa: E402
from print_handy.core import source_colors  # noqa: E402

ARCHIVE = settings.current()['paths']['archive']
STATE = Path(__file__).parent / 'fixtures' / 'printer_hardware.json'
SOURCE = next(ARCHIVE.glob('holder-for-post-it-notes-stencils-included--bbb*/source/*.3mf'), None)


def _orca_installed():
    if not shutil.which('flatpak'):
        return False
    return subprocess.run(['flatpak', 'info', 'com.orcaslicer.OrcaSlicer'],
                          capture_output=True).returncode == 0


pytestmark = [
    pytest.mark.real_slicer,
    pytest.mark.skipif(SOURCE is None, reason='post-it reference model not archived on this host'),
    pytest.mark.skipif(not _orca_installed(), reason='OrcaSlicer flatpak not installed'),
    pytest.mark.skipif(not STATE.exists(), reason='printer hardware state not present'),
]


def test_postit_per_part_slices_once_with_real_orca(tmp_path):
    src = tmp_path / 'source' / SOURCE.name
    src.parent.mkdir()
    shutil.copy2(SOURCE, src)
    state = json.loads(STATE.read_text())
    manifest = source_colors.inventory(src)
    white = model_job.resolve_filament_selection(state, dict(state['filament_slots']['1'], slot=1))
    pink = model_job.resolve_filament_selection(state, dict(state['filament_slots']['2'], slot=2))
    # Holder in slot 2, every stencil in slot 1: the grouped intake asks two questions for this.
    assert len(source_colors.grouped_prompts(manifest)) == 2
    choices = {}
    for row in source_colors.canonical_prompts(manifest):
        part = next(p for p in manifest['parts'] if p['key'] == row['key'][5:])
        choices[row['key']] = pink if 'Holder' in part['name'] else white
    job_path = tmp_path / 'JOB.json'
    job_path.write_text(json.dumps({
        'downloaded_file': str(src), 'audit': {'plates': 1}, 'color_schema': 'part_slots_v1',
        'color_manifest': manifest,
        'color_decisions': {'schema': 'part_slots_v1', 'mode': 'per_part',
                            'source_sha256': manifest['source_sha256'], 'choices': choices}}))

    model_job.slice_job(job_path)

    job = json.loads(job_path.read_text())
    assert job['plate_merge']['mode'] == 'merge', job['plate_merge']
    assert 'derived_plates' not in job and 'multipart_plan' not in job
    gcode = Path(job['gcode'])
    assert gcode.is_file() and gcode.stat().st_size > 100_000
    text = gcode.read_text(errors='replace')
    # Real Orca output that uses both chosen slots on one bed.
    assert 'OrcaSlicer' in text[:4000] or 'OrcaSlicer' in text[-60000:]
    assert '; hermes_tool_slots' in text
    tool_slots = json.loads(text.split('; hermes_tool_slots = ', 1)[1].split('\n', 1)[0])
    assert sorted({row['physical_slot'] for row in tool_slots.values()}) == [1, 2]
