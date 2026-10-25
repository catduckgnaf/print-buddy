"""Byte-level 3MF mesh reader.

ElementTree builds one Python object per <vertex> and <triangle>; a 1M-triangle
FlexyRing mesh costs ~50 s to parse that way, and the same file was parsed twice.
Here the mesh payload is read with compiled regexes straight from the bytes and
the remaining document structure is parsed with ElementTree after the mesh
bodies are stripped. Values are identical: float()/int() on the same digits.

Anything unexpected (namespaced mesh tags, reordered attributes, a count that
does not match) returns None so callers fall back to the full ElementTree path.
"""
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat

_OBJECT = re.compile(rb'<object\b[^>]*?\sid="([^"]*)"')
_VERTEX = re.compile(rb'<vertex\s+x="([^"]*)"\s+y="([^"]*)"\s+z="([^"]*)"')
_TRIANGLE = re.compile(rb'<triangle\s+v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"')


# Fast extraction is only safe for this deliberately narrow grammar. Other XML
# layouts keep their original bytes and use ElementTree, including extensions.
_MESH_BODY = re.compile(
    rb'<mesh>\s*<vertices>\s*(?:<vertex\s+x="[^"<&]*"\s+y="[^"<&]*"\s+z="[^"<&]*"\s*/>\s*)*'
    rb'</vertices>\s*<triangles>\s*(?:<triangle\s+v1="\d+"\s+v2="\d+"\s+v3="\d+"'
    rb'(?:\s+(?!xmlns)[\w:.-]+="[^"<&]*")*\s*/>\s*)*</triangles>\s*</mesh>')
_CORE = '{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}'


def _safe_layout(data):
    # Expat checks the ORIGINAL document without allocating an Element per face.
    # Never let mesh stripping turn malformed XML into valid XML.
    if b'<!' in data or b'&' in data or b'\x00' in data:
        return False
    try:
        expat.ParserCreate().Parse(data, True)
    except expat.ExpatError:
        return False
    # str.find spans, not a lazy DOTALL regex: a prefix match such as <meshfoo never matches the
    # grammar below, so any surprise ends in the ElementTree fallback, never in accepted geometry.
    meshes, pos = 0, 0
    while True:
        start = data.find(b'<mesh', pos)
        if start == -1:
            break
        end = data.find(b'</mesh>', start)
        if end == -1 or _MESH_BODY.fullmatch(data, start, end + 7) is None:
            return False
        meshes += 1
        pos = end + 7
    if not meshes:
        return False
    root = ET.fromstring(strip_mesh_bodies(data))
    objects = root.findall(_CORE + 'resources/' + _CORE + 'object')
    ids = [o.get('id') for o in objects]
    if (root.tag != _CORE + 'model' or None in ids or len(ids) != len(set(ids))
            or len(objects) != len(_OBJECT.findall(data))):
        return False
    # Namespace changes, nested objects/meshes and prefix aliases must fall back.
    core_meshes = [o.find(_CORE + 'mesh') for o in objects]
    return sum(m is not None for m in core_meshes) == meshes


def _object_spans(data):
    """[(object_id, start, end)] byte spans of each <object> element (objects never nest)."""
    found = list(_OBJECT.finditer(data))
    spans = []
    for i, match in enumerate(found):
        start = match.end()
        stop = found[i + 1].start() if i + 1 < len(found) else len(data)
        spans.append((match.group(1).decode(), start, stop))
    return spans


def mesh_tables(data, want_triangles=True):
    """{object_id: (vertices, triangles)} for every object with a mesh, or None.

    vertices is a list of (x, y, z) float tuples; triangles a list of (v1, v2, v3)
    int tuples (empty when want_triangles is False). None means "use ElementTree".
    """
    if b'<mesh' not in data or b':mesh' in data or b':vertex' in data or b':triangle' in data:
        return None
    if not _safe_layout(data):
        return None
    tables = {}
    for oid, start, stop in _object_spans(data):
        mesh_at = data.find(b'<mesh', start, stop)
        if mesh_at == -1:
            continue
        mesh_end = data.find(b'</mesh>', mesh_at, stop)
        if mesh_end == -1:
            return None  # self-closing or malformed: let ElementTree decide
        body = data[mesh_at:mesh_end]
        tri_at = body.find(b'<triangles')
        vpart = body if tri_at == -1 else body[:tri_at]
        raw = _VERTEX.findall(vpart)
        if len(raw) != vpart.count(b'<vertex'):  # '<vertices' does not match '<vertex'
            return None
        vertices = [(float(x), float(y), float(z)) for x, y, z in raw]
        triangles = []
        if want_triangles and tri_at != -1:
            tpart = body[tri_at:]
            idx = _TRIANGLE.findall(tpart)
            if len(idx) != tpart.count(b'<triangle') - tpart.count(b'<triangles'):
                return None
            triangles = [(int(a), int(b), int(c)) for a, b, c in idx]
            if triangles and max(max(t) for t in triangles) >= len(vertices):
                return None
        tables[oid] = (vertices, triangles)
    return tables


def strip_mesh_bodies(data):
    """<mesh>...</mesh> -> <mesh/> so structure-only ElementTree parsing is cheap."""
    if b'<mesh' not in data or b':mesh' in data:
        return data
    out, pos = [], 0
    while True:
        start = data.find(b'<mesh', pos)
        if start == -1:
            break
        end = data.find(b'</mesh>', start)
        if end == -1:
            return data
        out += [data[pos:start], b'<mesh/>']
        pos = end + len(b'</mesh>')
    out.append(data[pos:])
    return b''.join(out)


def bounds_and_volume(triangles):
    """(lo, hi, signed_volume) with the same float operation order as the old loops."""
    xs, ys, zs = [], [], []
    vol = 0.0
    for (ax, ay, az), (bx, by, bz), (cx, cy, cz) in triangles:
        xs += (ax, bx, cx)
        ys += (ay, by, cy)
        zs += (az, bz, cz)
        vol += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)) / 6.0
    return [min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)], vol


_TABLE_CACHE = {}


def archive_tables(archive, name):
    """(data, tables) for one 3MF member; tables cached per archive member version.

    Intake reads the same mesh for part sizes and again for the printable triangles;
    this keeps one parsed copy (one model at a time, like the triangle cache).
    """
    info = archive.getinfo(name)
    source = str(getattr(archive, 'filename', '') or id(archive))
    key = (name, info.CRC, info.file_size)
    if _TABLE_CACHE.get('source') != source:
        # One archive at a time, but every member of it: a Bambu 3MF alternates
        # between 3D/3dmodel.model and 3D/Objects/*.model, and evicting on each
        # switch reparsed the 88 MB object mesh three times per intake.
        _TABLE_CACHE.clear()
        _TABLE_CACHE['source'] = source
    hit = _TABLE_CACHE.get(key)
    if hit is not None:
        return hit
    data = archive.read(name)
    tables = mesh_tables(data)
    if tables is not None:
        data = strip_mesh_bodies(data)
    _TABLE_CACHE[key] = (data, tables)
    return data, tables
