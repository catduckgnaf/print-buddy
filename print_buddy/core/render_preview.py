"""Headless, validated STL preview rendering for Discord intake."""
from __future__ import annotations
import math
import subprocess
import tempfile
from pathlib import Path

from .. import settings


def render(path, scale=1.0, rotation=None, bed=None):
    """Render an STL through OpenSCAD in a headless subprocess; reject blank output."""
    from PIL import Image, ImageStat
    source = Path(path).resolve()
    if not source.is_file() or source.suffix.lower() != '.stl':
        raise ValueError('Preview is supported for STL models only.')
    matrix = rotation or [1, 0, 0, 0, 1, 0, 0, 0, 1]
    if len(matrix) != 9 or not all(math.isfinite(float(x)) for x in matrix):
        raise ValueError('The selected orientation is invalid.')
    s = float(scale)
    if not math.isfinite(s) or s <= 0:
        raise ValueError('The selected scale is invalid.')
    bedx, bedy = map(float, bed or settings.current()['printer']['bed_mm'])
    # Place the transformed mesh like a slicer would: centered on the bed, resting on Z0.
    import numpy as np
    import trimesh
    mesh = trimesh.load(str(source), force='mesh')
    lin = np.array(matrix, dtype=float).reshape(3, 3) * s
    pts = np.asarray(mesh.vertices) @ lin.T
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    off = [bedx / 2 - (lo[0] + hi[0]) / 2, bedy / 2 - (lo[1] + hi[1]) / 2, -lo[2]]
    size = hi - lo
    # Center on the build plate and normalize negative/far-away authored origins.
    # The translation above is applied after the model's scale and rotation.
    fits = size[0] <= bedx + 1e-6 and size[1] <= bedy + 1e-6
    rgb = '[0.2,0.55,0.9]' if fits else '[0.9,0.25,0.2]'
    m = [[float(v) for v in row] for row in lin]
    cam = f'{bedx / 2},{bedy / 2},{size[2] / 2},55,0,25,{round(max(bedx, bedy, size[0], size[1]) * 2.4)}'
    with tempfile.TemporaryDirectory(prefix='model-preview-') as td:
        scad, output = Path(td) / 'preview.scad', Path(td) / 'preview.png'
        scad.write_text(f'''$fn=24;
color([0.18,0.22,0.27]) translate([0,0,-0.7]) cube([{bedx},{bedy},0.7]);
color({rgb}) multmatrix([[{m[0][0]},{m[0][1]},{m[0][2]},{off[0]}],[{m[1][0]},{m[1][1]},{m[1][2]},{off[1]}],[{m[2][0]},{m[2][1]},{m[2][2]},{off[2]}],[0,0,0,1]]) import("{source}");
''')
        proc = subprocess.run(['/usr/bin/xvfb-run', '-a', '/usr/bin/openscad', '-o', str(output), '--camera=' + cam, '--imgsize=900,700',
                               '--colorscheme=Tomorrow', str(scad)], capture_output=True, text=True, timeout=90)
        if proc.returncode or not output.is_file():
            raise RuntimeError('The 3D preview renderer could not produce an image: ' + proc.stderr[-300:])
        image = Image.open(output).convert('RGB')
        pixels = list(image.getdata())
        if not pixels:
            raise RuntimeError('The 3D preview was empty; no image was sent.')
        if max(ImageStat.Stat(image).stddev) < 2.0 or len(set(pixels[::max(1, len(pixels)//20000)])) < 4:
            raise RuntimeError('The 3D preview was blank or near-uniform; no image was sent.')
        dest = Path.home() / '.hermes/cache/model-previews'
        dest.mkdir(parents=True, exist_ok=True)
        final = dest / f'{source.stem}-{abs(hash((str(source), s, tuple(matrix)))) & 0xffffffff:08x}.png'
        image.save(final)
        return str(final)
