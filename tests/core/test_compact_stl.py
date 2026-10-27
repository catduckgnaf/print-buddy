"""Derived binary STL must not reconstruct a Python object graph."""
import struct
import tracemalloc
from print_handy.core.compact_geometry import CompactTriangles
from print_handy.core.orca_adapter import read_stl_triangles


def test_binary_stl_streams_into_compact_storage(tmp_path):
    path = tmp_path/'derived.stl'
    record = struct.pack('<12fH', 0,0,0, 1,2,3, 4,5,6, 7,8,9, 0)
    with path.open('wb') as out:
        out.write(b'bounded STL'.ljust(80,b'\0'))
        out.write(struct.pack('<I', 100000))
        for _ in range(100):
            out.write(record*1000)
    tracemalloc.start()
    try:
        result = read_stl_triangles(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert isinstance(result, CompactTriangles)
    assert len(result) == 100000
    assert result[-1] == [(1.,2.,3.), (4.,5.,6.), (7.,8.,9.)]
    assert peak < 12*1024*1024
