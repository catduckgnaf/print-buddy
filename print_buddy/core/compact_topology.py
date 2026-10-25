"""Compact exact topology for dense meshes, without Python adjacency graphs."""
from array import array


def _indexed_faces(triangles):
    """Welded face table + degenerate count from IndexedTriangles storage.

    Welding rounds each *unique vertex* once with the historical Python
    round(v, 6) (not once per face corner, which is where the previous
    implementation re-expanded the whole mesh into a float64 soup), and the
    degenerate cross-product test is evaluated on gathered faces in bounded
    chunks with the same per-face operation order as the scalar code.
    """
    import numpy as np

    vertices = triangles.vertices
    faces = triangles.faces
    storage = array('d')
    for start in range(0, len(vertices), 8192):
        for row in vertices[start:start + 8192].tolist():
            storage.extend(round(float(v), 6) for v in row)
    points = np.frombuffer(storage, dtype=np.float64).reshape((-1, 3))
    del storage
    _, inverse = np.unique(points, axis=0, return_inverse=True)
    del points
    inverse = np.asarray(inverse).reshape(-1)
    mapped = inverse[faces]
    del inverse
    degenerate = 0
    kept = []
    for start in range(0, len(faces), 65536):
        chunk = faces[start:start + 65536]
        pts = vertices[chunk].reshape((-1, 3, 3))
        u = pts[:, 1] - pts[:, 0]
        v = pts[:, 2] - pts[:, 0]
        cross = np.stack((u[:, 1] * v[:, 2] - u[:, 2] * v[:, 1],
                          u[:, 2] * v[:, 0] - u[:, 0] * v[:, 2],
                          u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]), axis=1)
        sumsq = cross[:, 0] * cross[:, 0]
        sumsq = sumsq + cross[:, 1] * cross[:, 1]
        sumsq = sumsq + cross[:, 2] * cross[:, 2]
        ids = mapped[start:start + 65536]
        distinct = (ids[:, 0] != ids[:, 1]) & (ids[:, 1] != ids[:, 2]) & (ids[:, 0] != ids[:, 2])
        keep = distinct & (sumsq > 1e-18)
        degenerate += int(len(chunk) - int(np.count_nonzero(keep)))
        if np.all(keep):
            kept.append(ids)
        elif np.any(keep):
            kept.append(ids[keep])
    faces = np.concatenate(kept) if kept else np.empty((0, 3), dtype=np.int64)
    if not len(faces):
        return faces, degenerate, 0
    # Match the legacy vertex set exactly: only welded vertices referenced by
    # a kept (non-degenerate) face exist, relabelled contiguously.
    used, remap = np.unique(faces.ravel(), return_inverse=True)
    faces = remap.reshape((-1, 3))
    return faces, degenerate, len(used)


def mesh_topology_compact(triangles):
    import numpy as np

    from .compact_geometry import IndexedTriangles
    if isinstance(triangles, IndexedTriangles):
        faces, degenerate, nv = _indexed_faces(triangles)
    else:
        # Keep historical Python round/area arithmetic, including tie handling.
        storage = array('d')
        degenerate = 0
        for tri in triangles:
            points = [tuple(float(v) for v in point) for point in tri]
            keys = [tuple(round(v, 6) for v in point) for point in points]
            u = tuple(b-a for a, b in zip(points[0], points[1]))
            v = tuple(b-a for a, b in zip(points[0], points[2]))
            cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
            if len(set(keys)) < 3 or sum(c*c for c in cross) <= 1e-18:
                degenerate += 1
            else:
                storage.extend(x for p in keys for x in p)
        points = np.frombuffer(storage, dtype=np.float64).reshape((-1, 3))
        unique, inverse = np.unique(points, axis=0, return_inverse=True)
        nv = len(unique)
        faces = inverse.reshape((-1, 3))
        del points, storage, unique
    nf = len(faces)
    # int32 indices halve the edge/union arrays whenever the mesh fits them.
    idx = np.int32 if max(nf * 3, nv) < 2 ** 31 else np.int64
    faces = faces.astype(idx, copy=False)
    # Edges retain original corner indices; direction reproduces winding checks.
    corner = np.arange(nf*3, dtype=idx)
    next_corner = (corner // 3)*3 + (corner+1) % 3
    flat = faces.ravel()
    a, b = flat, flat[next_corner]
    del next_corner
    order = np.lexsort((np.maximum(a, b), np.minimum(a, b)))
    low, high = np.minimum(a, b)[order], np.maximum(a, b)[order]
    boundaries = np.r_[0, np.flatnonzero((low[1:] != low[:-1]) | (high[1:] != high[:-1]))+1, len(order)]
    del low, high
    shell_parent = np.arange(nf, dtype=idx)
    corner_parent = corner.copy()
    del corner
    singular = np.zeros(nv, dtype=np.bool_)

    def find(parent, i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = int(parent[i])
        return i

    def union(parent, x, y):
        x, y = find(parent, x), find(parent, y)
        if x != y:
            parent[max(x, y)] = min(x, y)

    boundary = nonmanifold = winding = 0
    for start, stop in zip(boundaries[:-1], boundaries[1:]):
        if start == stop:
            continue
        first = int(order[start])
        count = int(stop-start)
        for j in range(int(start)+1, int(stop)):
            union(shell_parent, first//3, int(order[j])//3)
        if count != 2:
            singular[a[first]] = singular[b[first]] = True
            boundary += count == 1
            nonmanifold += count > 2
        else:
            other = int(order[start+1])
            same = (a[first] < b[first]) == (a[other] < b[other])
            winding += int(same)
            # Unite incident face corners at each endpoint of a closed edge.
            next_first = (first // 3) * 3 + (first + 1) % 3
            next_other = (other // 3) * 3 + (other + 1) % 3
            union(corner_parent, first, other if same else next_other)
            union(corner_parent, next_first, next_other if same else other)
    # Vector path compression avoids sets of Python integers per vertex/face.
    def compress(parent):
        while True:
            new = parent[parent]
            if np.array_equal(new, parent):
                return parent
            parent[:] = new
    shell_roots = compress(shell_parent)
    corner_roots = compress(corner_parent)
    mins = np.full(nv, nf*3, dtype=idx)
    maxs = np.full(nv, -1, dtype=idx)
    np.minimum.at(mins, flat, corner_roots)
    np.maximum.at(maxs, flat, corner_roots)
    singular |= mins != maxs
    n_singular = int(np.count_nonzero(singular))
    shells = int(np.count_nonzero(shell_roots == np.arange(nf)))
    count = nf + degenerate
    return {'format': 'triangle-mesh', 'triangles': count, 'shells': shells,
            'triangle_count': count, 'connected_shells': shells,
            'boundary_edges': int(boundary), 'non_manifold_edges': int(nonmanifold),
            'non_manifold_vertices': n_singular, 'singular_vertices': n_singular,
            'winding_inconsistencies': int(winding), 'degenerate_triangles': degenerate,
            'watertight': boundary == 0 and nonmanifold == 0,
            'manifold': not (boundary or nonmanifold or n_singular or degenerate or winding)}
