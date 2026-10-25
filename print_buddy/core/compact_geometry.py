"""Compact, native-scalar triangle sequences for legacy geometry consumers.

Double precision preserves the existing transform arithmetic. Iteration creates
only one triangle at a time; no persistent Python point/face object graph.
"""
from array import array
from collections.abc import Sequence


class CompactTriangles(Sequence):
    def __init__(self, triangles=()):
        self.coordinates = array('d')
        self.extend(triangles)

    def extend(self, triangles):
        if isinstance(triangles, CompactTriangles):
            self.coordinates.extend(triangles.coordinates)
        else:
            for triangle in triangles:
                self.coordinates.extend(value for point in triangle for value in point)

    def append(self, triangle):
        self.coordinates.extend(value for point in triangle for value in point)

    def __len__(self):
        return len(self.coordinates) // 9

    def __getitem__(self, index):
        if isinstance(index, slice):
            return CompactTriangles(self[i] for i in range(*index.indices(len(self))))
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        offset = index * 9
        data = self.coordinates
        return [tuple(data[offset + k:offset + k + 3]) for k in (0, 3, 6)]

    def __repr__(self):
        return repr(list(self))

    def __eq__(self, other):
        if isinstance(other, CompactTriangles):
            return self.coordinates == other.coordinates
        if isinstance(other, (list, tuple)):
            return list(self) == list(other)
        return False


class TransformedTriangles(Sequence):
    """Reiterable scalar transform view; orientations share the source storage."""
    def __init__(self, source, transform):
        self.source = source
        self.transform = transform

    def __len__(self):
        return len(self.source)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return CompactTriangles(self[i] for i in range(*index.indices(len(self))))
        return [self.transform(*point) for point in self.source[index]]


def transformed_rows(vertices, chain, transform):
    """Apply transforms with historical scalar operation order, compactly."""
    from .mesh_fast import _LegacyRows
    import numpy as np
    def points():
        for point in vertices:
            for matrix in chain:
                point = transform(matrix, point)
            yield from point
    storage = array('d', points())
    return _LegacyRows(np.frombuffer(storage, dtype=np.float64).reshape((-1, 3)))
