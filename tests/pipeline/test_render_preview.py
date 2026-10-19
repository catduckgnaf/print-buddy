"""Preview must show the model centered on the bed, like a slicer would place it."""
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

from print_buddy.core import render_preview  # noqa: E402

pytestmark = pytest.mark.skipif(not (shutil.which('openscad') and shutil.which('xvfb-run')),
                                reason='openscad/xvfb-run not installed')


def _offset_box(tmp_path, size, origin):
    import trimesh
    box = trimesh.creation.box(extents=size)
    box.apply_translation([o + s / 2 for o, s in zip(origin, size)])
    path = tmp_path / 'box.stl'
    box.export(path)
    return path


def test_far_offset_model_is_centered_and_rendered(tmp_path, monkeypatch):
    # Author origin far from the bed reproduced the "model floating off the bed" preview.
    stl = _offset_box(tmp_path, (140, 210, 20), (500, -300, 40))
    seen = {}
    real_run = render_preview.subprocess.run

    def spy(cmd, **kw):
        seen['scad'] = Path(cmd[-1]).read_text()
        seen['cmd'] = cmd
        return real_run(cmd, **kw)
    monkeypatch.setattr(render_preview.subprocess, 'run', spy)
    out = render_preview.render(stl)
    assert Path(out).is_file()
    assert '--autocenter' not in seen['cmd'] and '--viewall' not in seen['cmd']
    # Translation column centers X/Y on the 220 bed and drops Z to 0.
    assert ',-460.0]' in seen['scad'] and ',305.0]' in seen['scad'] and ',-40.0]' in seen['scad']
    assert '[0.2,0.55,0.9]' in seen['scad']  # fits -> blue


def test_oversized_model_is_flagged_red(tmp_path, monkeypatch):
    stl = _offset_box(tmp_path, (140, 210, 20), (0, 0, 0))
    seen = {}
    real_run = render_preview.subprocess.run

    def spy(cmd, **kw):
        seen['scad'] = Path(cmd[-1]).read_text()
        return real_run(cmd, **kw)
    monkeypatch.setattr(render_preview.subprocess, 'run', spy)
    render_preview.render(stl, scale=1.2)
    assert '[0.9,0.25,0.2]' in seen['scad']
