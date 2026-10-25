"""Packing keeps orientation candidates as views, never whole-mesh graphs."""
import tracemalloc

import pytest

from print_buddy.core.compact_geometry import CompactTriangles, TransformedTriangles
from print_buddy.core.geometry_layout import pack_parts, rotate_triangles_z


def test_rotation_preserves_scalar_math_and_reiterability():
    source = [[(1., 2., 3.), (3., 2., 3.), (1., 4., 5.)]]
    result, ext, meta = rotate_triangles_z(source, 90)
    assert isinstance(result, TransformedTriangles)
    assert list(result) == list(result)
    assert result[0][0] == pytest.approx((2., 0., 0.))
    assert ext == pytest.approx((2., 2., 2.))
    assert meta[2] == pytest.approx((-4., 1., 3.))


def test_packing_orientation_candidates_have_bounded_allocations():
    source = CompactTriangles([[(0., 0., 0.), (10., 0., 0.), (0., 20., 1.)]] * 20000)
    tracemalloc.start()
    try:
        placed, _ = pack_parts([{'id': 'mesh', 'triangles': source}], angles=[0, 30, 60, 90])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert isinstance(placed[0]['triangles'], TransformedTriangles)
    assert placed[0]['triangles'].source.source is source
    # Fixed 8192-face bounds batches fit comfortably; Python mesh graphs do not.
    assert peak < 8 * 1024 * 1024
    assert len(placed[0]['triangles']) == 20000
