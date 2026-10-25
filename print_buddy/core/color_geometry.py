"""Source-bound, instance-preserving multipart core 3MF for Orca."""
import copy
import json
import math
import re
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
import zipfile

from .. import settings
from . import source_colors
from .source_colors import inventory
from .orca_adapter import digest

CORE = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]


def export_color_geometry(source, target, decisions, item_shifts=None, object_ids=None, scale=None):
    """object_ids limits export to those build objects (one authored plate);
    scale shrinks the selection uniformly before bed centering."""
    manifest = inventory(source)
    full_parts = manifest['parts']
    if object_ids is not None:
        object_ids = {str(o) for o in object_ids}
        manifest = dict(manifest, parts=[p for p in full_parts if str(p['object_id']) in object_ids])
        if not manifest['parts']:
            raise RuntimeError('object subset selects no source parts')
    scale = float(scale) if scale is not None else 1.0
    if not 0 < scale <= 1:
        raise RuntimeError('painted export scale must be greater than 0 and no more than 1')
    if decisions.get('source_sha256') != manifest['source_sha256'] or decisions.get('mode') != 'per_part':
        raise RuntimeError('multicolor geometry requires exact-source per_part decisions')
    painted = bool(manifest['painted'])
    choices = decisions['choices']
    schema = decisions.get('schema')
    if schema not in (None, 'part_slots_v1'):
        raise RuntimeError('unknown color decision schema')
    planner = source_colors.canonical_prompts if schema == 'part_slots_v1' else source_colors.prompts
    expected = {row['key'] for row in planner(dict(manifest, parts=full_parts))}
    if set(choices) != expected:
        raise RuntimeError('incomplete part/source-filament decisions')
    # Parts and their source palette rows are distinct UI decisions, but a part
    # cannot silently disagree with the palette assignment it refers to.
    if painted:
        # Triangle paint: each painted state N is source filament N; unpainted
        # triangles and state 0 use the part's own extruder. Map every state
        # actually present to a contiguous tool for the chosen physical slot.
        from . import painted_geometry
        used = set()
        base_state = {}
        for part in manifest['parts']:
            row = painted_geometry.leaf_states(source, part)
            # Fully painted parts never print their base extruder; give the
            # object-level extruder the part's dominant paint instead.
            dominant = max(row['states'], key=row['states'].get) if row['states'] else None
            base_state[part['key']] = part['source_extruder'] if row['unpainted'] or not dominant else dominant
            used |= {state or part['source_extruder'] for state in row['states']}
            if row['unpainted']:
                used.add(part['source_extruder'])
        missing = sorted(n for n in used if f'filament:{n}' not in choices)
        if missing:
            raise RuntimeError(f'painted source filament(s) {missing} have no slot choice')
        slots = sorted({choices[f'filament:{n}']['slot'] for n in used})
        paint_table = {n: slots.index(choices[f'filament:{n}']['slot']) + 1 for n in used}
    else:
        for part in manifest['parts']:
            palette = choices.get(f"filament:{part['source_extruder']}")
            if palette and palette != choices['part:' + part['key']]:
                raise RuntimeError('part selection contradicts its source filament selection')
        slots = sorted({choices['part:' + part['key']]['slot'] for part in manifest['parts']})
    if not slots or len(slots) > 4:
        raise RuntimeError('multipart selection requires one to four IFS slots')
    mapping = {str(i): slot for i, slot in enumerate(slots)}
    with zipfile.ZipFile(source) as archive:
        models = {}
        for name in archive.namelist():
            if name.endswith('.model'):
                root = ET.fromstring(archive.read(name))
                if root.get('unit', 'millimeter') != 'millimeter':
                    raise RuntimeError('only millimeter 3MF geometry supported')
                models[name] = (root, {n.get('id'): n for n in root if n.tag.split('}')[-1] == 'resources' for n in n if n.tag.split('}')[-1] == 'object'})
        leaves = []

        def transform(node):
            values = list(map(float, node.get('transform', ' '.join(map(str, IDENTITY))).split()))
            if len(values) != 12 or not all(math.isfinite(v) for v in values):
                raise RuntimeError('invalid 3MF transform')
            return values

        def visit(name, oid, chain, key):
            obj = models[name][1][oid]
            mesh = next((n for n in obj if n.tag.split('}')[-1] == 'mesh'), None)
            if mesh is not None:
                vertices = next(n for n in mesh if n.tag.split('}')[-1] == 'vertices')
                points = []
                for vertex in vertices:
                    point = tuple(float(vertex.get(k)) for k in ('x', 'y', 'z'))
                    for matrix in chain:
                        point = tuple(sum(point[j] * matrix[j * 3 + i] for j in range(3)) + matrix[9 + i] for i in range(3))
                    if not all(math.isfinite(v) for v in point):
                        raise RuntimeError('nonfinite 3MF vertex')
                    points.append(point)
                if not points:
                    raise RuntimeError('empty part geometry')
                leaves.append((key, mesh, points))
                return
            components = next(n for n in obj if n.tag.split('}')[-1] == 'components')
            for i, component in enumerate(components):
                path = next((v for k, v in component.attrib.items() if k.split('}')[-1] == 'path'), None)
                path = path.lstrip('/') if path and path.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(name), path)) if path else name
                visit(path, component.get('objectid'), [transform(component)] + chain, f'{key}/{i}')

        root = models['3D/3dmodel.model'][0]
        build = next(n for n in root if n.tag.split('}')[-1] == 'build')
        for i, item in enumerate(build):
            if object_ids is not None and item.get('objectid') not in object_ids:
                continue
            if item.get('printable', '1') != '1':
                raise RuntimeError('nonprintable build item requires explicit selection')
            path = next((v for k, v in item.attrib.items() if k.split('}')[-1] == 'path'), None)
            path = path.lstrip('/') if path and path.startswith('/') else posixpath.normpath(posixpath.join('3D', path)) if path else '3D/3dmodel.model'
            visit(path, item.get('objectid'), [transform(item)], f'build:{i}')
    if scale != 1.0:
        leaves[:] = [(k, m, [tuple(c * scale for c in pt) for pt in pts]) for k, m, pts in leaves]
    # Negative/modifier volumes ride along inside their own object, never as a
    # separate solid (a solid cutter collides with its body: Orca -101).
    cutter_rows = {c['instance_key']: c for c in manifest.get('cutters', [])
                   if object_ids is None or str(c['object_id']) in object_ids}
    cut_leaves = [leaf for leaf in leaves if leaf[0] in cutter_rows]
    leaves[:] = [leaf for leaf in leaves if leaf[0] not in cutter_rows]
    if len(leaves) != len(manifest['parts']):
        raise RuntimeError('geometry and selection inventory disagree')
    bounds = [(min(p[a] for _, _, ps in leaves for p in ps), max(p[a] for _, _, ps in leaves for p in ps)) for a in range(3)]
    delta = [110 - sum(bounds[a]) / 2 for a in (0, 1)] + [-bounds[2][0]]
    if item_shifts is None:
        delta = _tower_friendly_delta(bounds, delta)
    if item_shifts is not None and {str(k) for k in item_shifts} != {str(p['object_id']) for p in manifest['parts']}:
        raise RuntimeError('item shifts must name exactly the source objects')
    tag = lambda name: '{' + CORE + '}' + name
    ET.register_namespace('', CORE)
    model = ET.Element(tag('model'), unit='millimeter')
    resources = ET.SubElement(model, tag('resources'))
    config = ET.Element('config')
    # One plate object per source build leaf. A single assembly makes Orca
    # treat every part as one object, so the wipe tower cannot sit between them
    # and slicing returns -101 (placeable areas / gcode conflict).
    plate = ET.SubElement(config, 'plate')
    ET.SubElement(plate, 'metadata', key='plater_id', value='1')
    build = ET.SubElement(model, tag('build'))
    records = []
    part_bounds = []
    group_of = {}
    # Group per source build item (not object id: repeated instances of one
    # object stay separate). Parts of one build item share space by design;
    # exported as separate Orca objects they overlap and fail as G-code
    # conflicts, and auto-arrange scatters them into the tower lane.
    item_of = lambda instance_key: instance_key.split('/')[0]
    leaf_boxes = {}
    for key, _mesh, points in leaves:
        leaf_boxes.setdefault(item_of(key), []).append(
            [(min(p[a] for p in points), max(p[a] for p in points)) for a in (0, 1)])
    # Orca's conflict checker uses extrusion paths, so touching or near-touching
    # footprints (within one perimeter-ish gap) also count as overlapping.
    touch = lambda a, b: all(a[i][0] < b[i][1] + 1 and b[i][0] < a[i][1] + 1 for i in (0, 1))
    overlapping_items = {item for item, boxes in leaf_boxes.items()
                         if any(touch(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:])}
    cut_items = {item_of(cutter_rows[k]['instance_key']) for k, _, _ in cut_leaves}
    for part in manifest['parts']:
        item = item_of(part['instance_key'])
        if painted or item in cut_items or item in overlapping_items:
            group_of.setdefault(item, {'name': part.get('object_name') or part['name'],
                                       'parts': [], 'cutters': []})
    for i, ((key, mesh, points), part) in enumerate(zip(leaves, manifest['parts']), 1):
        # inventory metadata may reorder parts: match resolved build instance.
        part = next(p for p in manifest['parts'] if p['instance_key'] == key)
        if painted:
            tool = paint_table[base_state[part['key']]] - 1
            slot = slots[tool]
        else:
            slot = choices['part:' + part['key']]['slot']
            tool = slots.index(slot)
        mesh_id = str(i)
        group = group_of.get(item_of(part['instance_key']))
        obj = ET.SubElement(resources, tag('object'), id=mesh_id, type='model', name=part['name'])
        new_mesh = copy.deepcopy(mesh)
        for node in new_mesh.iter():
            node.tag = tag(node.tag.split('}')[-1])
        if painted:
            from . import painted_geometry
            for tri in new_mesh.find(tag('triangles')):
                code = tri.get('paint_color')
                if code:
                    tri.set('paint_color', painted_geometry.remap_code(code, paint_table))
        else:
            for tri in new_mesh.find(tag('triangles')):
                tri.attrib.pop('paint_color', None)
        placed = []
        move = [float(v) for v in item_shifts[str(part['object_id'])]] if item_shifts is not None else delta
        for vertex, point in zip(new_mesh.find(tag('vertices')), points):
            xyz = tuple(point[a] + move[a] for a in range(3))
            placed.append(xyz)
            for a, axis in enumerate(('x', 'y', 'z')):
                vertex.set(axis, repr(xyz[a]))
        obj.append(new_mesh)
        if group is not None:
            # Volumes of one source object stay one Orca object (assembly of
            # parts); separate objects would overlap and fail as G-code conflicts.
            group['parts'].append((mesh_id, part['name'], tool))
        else:
            obj_config = ET.SubElement(config, 'object', id=mesh_id)
            ET.SubElement(obj_config, 'metadata', key='name', value=part['name'])
            ET.SubElement(obj_config, 'metadata', key='extruder', value=str(tool + 1))
            pc = ET.SubElement(obj_config, 'part', id=mesh_id, subtype='normal_part')
            ET.SubElement(pc, 'metadata', key='name', value=part['name'])
            ET.SubElement(pc, 'metadata', key='extruder', value=str(tool + 1))
            instance = ET.SubElement(plate, 'model_instance')
            ET.SubElement(instance, 'metadata', key='object_id', value=mesh_id)
            ET.SubElement(instance, 'metadata', key='instance_id', value='0')
            ET.SubElement(build, tag('item'), objectid=mesh_id, printable='1')
        box = [(min(p[a] for p in placed), max(p[a] for p in placed)) for a in range(3)]
        part_bounds.append(box)
        records.append({'part_key': part['key'], 'build_key': key, 'tool': tool, 'slot': slot,
                        'vertices': len(points), 'triangles': len(new_mesh.find(tag('triangles'))),
                        'bounds_mm': box})
    next_id = len(leaves) + 1
    for key, mesh, points in cut_leaves:
        row = cutter_rows[key]
        group = group_of[item_of(row['instance_key'])]
        move = [float(v) for v in item_shifts[str(row['object_id'])]] if item_shifts is not None else delta
        cut_id = str(next_id)
        next_id += 1
        obj = ET.SubElement(resources, tag('object'), id=cut_id, type='model', name=row['name'])
        new_mesh = copy.deepcopy(mesh)
        for node in new_mesh.iter():
            node.tag = tag(node.tag.split('}')[-1])
            node.attrib.pop('paint_color', None)
        for vertex, point in zip(new_mesh.find(tag('vertices')), points):
            for a, axis in enumerate(('x', 'y', 'z')):
                vertex.set(axis, repr(point[a] + move[a]))
        obj.append(new_mesh)
        group['cutters'].append((cut_id, row['name'], row['subtype']))
    for group in group_of.values():
        wrapper_id = str(next_id)
        next_id += 1
        wrapper = ET.SubElement(resources, tag('object'), id=wrapper_id, type='model', name=group['name'])
        comps = ET.SubElement(wrapper, tag('components'))
        obj_config = ET.SubElement(config, 'object', id=wrapper_id)
        ET.SubElement(obj_config, 'metadata', key='name', value=group['name'])
        ET.SubElement(obj_config, 'metadata', key='extruder', value=str(group['parts'][0][2] + 1))
        for mesh_id, name, tool in group['parts']:
            ET.SubElement(comps, tag('component'), objectid=mesh_id)
            pc = ET.SubElement(obj_config, 'part', id=mesh_id, subtype='normal_part')
            ET.SubElement(pc, 'metadata', key='name', value=name)
            ET.SubElement(pc, 'metadata', key='extruder', value=str(tool + 1))
        for cut_id, name, subtype in group['cutters']:
            ET.SubElement(comps, tag('component'), objectid=cut_id)
            pc = ET.SubElement(obj_config, 'part', id=cut_id, subtype=subtype)
            ET.SubElement(pc, 'metadata', key='name', value=name)
        instance = ET.SubElement(plate, 'model_instance')
        ET.SubElement(instance, 'metadata', key='object_id', value=wrapper_id)
        ET.SubElement(instance, 'metadata', key='instance_id', value='0')
        ET.SubElement(build, tag('item'), objectid=wrapper_id, printable='1')
    if group_of:
        # Tower clearance is per printed object, i.e. per assembly.
        merged = {}
        for record, box in zip(records, part_bounds):
            oid = item_of(next(p['instance_key'] for p in manifest['parts'] if p['instance_key'] == record['build_key']))
            prev = merged.get(oid)
            merged[oid] = box if prev is None else [(min(prev[a][0], box[a][0]), max(prev[a][1], box[a][1])) for a in range(3)]
        part_bounds = list(merged.values())
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as out:
        out.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        out.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        out.writestr('3D/3dmodel.model', ET.tostring(model, encoding='utf-8', xml_declaration=True))
        out.writestr('Metadata/model_settings.config', ET.tostring(config, encoding='utf-8', xml_declaration=True))
    towers = prime_tower_candidates(part_bounds)
    tower = towers[0]
    return mapping, {'source_sha256': digest(source), 'converted_sha256': digest(target), 'parts': records,
                     'build_bounds_mm': bounds, 'translation_mm': delta if item_shifts is None else None, 'merged_placement': item_shifts is not None, 'prime_tower_xy_mm': list(tower),
                     'prime_tower_candidates_mm': [list(t) for t in towers],
                     'policy': 'all mesh leaves as independent build items; component transforms; one rigid translation; float64 XML'}


def export_volume_plate(source, target, scale=1.0, rotation=None):
    """Single-filament 3MF that keeps negative/modifier volumes inside their object.

    Same placement contract as orca_adapter.export_geometry (optional rigid
    rotation, uniform scale, center XY on the AD5X bed, lowest printed vertex on
    Z0) but cutters stay typed volumes so Orca subtracts them instead of
    printing them as a colliding solid.
    """
    from .orca_adapter import _check_rotation, _rotate
    from . import source_colors
    scale = float(scale) if scale is not None else 1.0
    if not 0 < scale <= 1:
        raise ValueError('scale must be greater than 0 and no more than 1')
    rotation = _check_rotation(rotation)
    manifest = inventory(source)
    kind = {p['instance_key']: (p, p.get('subtype', 'normal_part'))
            for p in manifest['parts'] + manifest.get('cutters', [])}
    with zipfile.ZipFile(source) as archive:
        models = {}
        for name in archive.namelist():
            if name.endswith('.model'):
                root = ET.fromstring(archive.read(name))
                if root.get('unit', 'millimeter') != 'millimeter':
                    raise RuntimeError('only millimeter 3MF geometry supported')
                models[name] = (root, {n.get('id'): n for r in root if r.tag.split('}')[-1] == 'resources'
                                       for n in r if n.tag.split('}')[-1] == 'object'})
        leaves = []

        def transform(node):
            values = list(map(float, node.get('transform', ' '.join(map(str, IDENTITY))).split()))
            if len(values) != 12 or not all(math.isfinite(v) for v in values):
                raise RuntimeError('invalid 3MF transform')
            return values

        def visit(name, oid, chain, key, item_id):
            obj = models[name][1][oid]
            mesh = next((n for n in obj if n.tag.split('}')[-1] == 'mesh'), None)
            if mesh is not None:
                verts = next(n for n in mesh if n.tag.split('}')[-1] == 'vertices')
                pts = []
                for vertex in verts:
                    pt = tuple(float(vertex.get(k)) for k in ('x', 'y', 'z'))
                    for m in chain:
                        pt = tuple(sum(pt[j] * m[j * 3 + i] for j in range(3)) + m[9 + i] for i in range(3))
                    if rotation is not None:
                        pt = _rotate(pt, rotation)
                    pts.append(tuple(c * scale for c in pt))
                leaves.append((key, item_id, mesh, pts))
                return
            comps = next(n for n in obj if n.tag.split('}')[-1] == 'components')
            for i, comp in enumerate(comps):
                path = next((v for k, v in comp.attrib.items() if k.split('}')[-1] == 'path'), None)
                path = path.lstrip('/') if path and path.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(name), path)) if path else name
                visit(path, comp.get('objectid'), [transform(comp)] + chain, f'{key}/{i}', item_id)

        root = models['3D/3dmodel.model'][0]
        build = next(n for n in root if n.tag.split('}')[-1] == 'build')
        for i, item in enumerate(build):
            if item.get('printable', '1') != '1':
                raise RuntimeError('nonprintable build item requires explicit selection')
            path = next((v for k, v in item.attrib.items() if k.split('}')[-1] == 'path'), None)
            path = path.lstrip('/') if path and path.startswith('/') else posixpath.normpath(posixpath.join('3D', path)) if path else '3D/3dmodel.model'
            visit(path, item.get('objectid'), [transform(item)], f'build:{i}', i)
    if set(k for k, *_ in leaves) != set(kind):
        raise RuntimeError('geometry and volume inventory disagree')
    printed = [pt for k, _, _, pts in leaves if kind[k][1] == 'normal_part' for pt in pts]
    if not printed:
        raise RuntimeError('3MF contains no printable volume')
    bounds = [(min(p[a] for p in printed), max(p[a] for p in printed)) for a in range(3)]
    delta = [110 - sum(bounds[a]) / 2 for a in (0, 1)] + [-bounds[2][0]]
    tag = lambda name: '{' + CORE + '}' + name
    ET.register_namespace('', CORE)
    model = ET.Element(tag('model'), unit='millimeter')
    resources = ET.SubElement(model, tag('resources'))
    config = ET.Element('config')
    plate = ET.SubElement(config, 'plate')
    ET.SubElement(plate, 'metadata', key='plater_id', value='1')
    out_build = ET.SubElement(model, tag('build'))
    groups, next_id, counts = {}, 1, {}
    for key, item_id, mesh, pts in leaves:
        part, subtype = kind[key]
        mesh_id = str(next_id)
        next_id += 1
        obj = ET.SubElement(resources, tag('object'), id=mesh_id, type='model', name=part['name'])
        new_mesh = copy.deepcopy(mesh)
        for node in new_mesh.iter():
            node.tag = tag(node.tag.split('}')[-1])
            node.attrib.pop('paint_color', None)
        for vertex, pt in zip(new_mesh.find(tag('vertices')), pts):
            for a, axis in enumerate(('x', 'y', 'z')):
                vertex.set(axis, repr(pt[a] + delta[a]))
        obj.append(new_mesh)
        counts[subtype] = counts.get(subtype, 0) + 1
        groups.setdefault(item_id, {'name': part.get('object_name') or part['name'], 'vols': []})['vols'].append(
            (mesh_id, part['name'], subtype))
    for group in groups.values():
        if not any(sub == 'normal_part' for _, _, sub in group['vols']):
            raise RuntimeError('object has only negative/modifier volumes')
        wrapper_id = str(next_id)
        next_id += 1
        wrapper = ET.SubElement(resources, tag('object'), id=wrapper_id, type='model', name=group['name'])
        comps = ET.SubElement(wrapper, tag('components'))
        obj_config = ET.SubElement(config, 'object', id=wrapper_id)
        ET.SubElement(obj_config, 'metadata', key='name', value=group['name'])
        ET.SubElement(obj_config, 'metadata', key='extruder', value='1')
        for mesh_id, name, subtype in group['vols']:
            ET.SubElement(comps, tag('component'), objectid=mesh_id)
            pc = ET.SubElement(obj_config, 'part', id=mesh_id, subtype=subtype)
            ET.SubElement(pc, 'metadata', key='name', value=name)
            if subtype == 'normal_part':
                ET.SubElement(pc, 'metadata', key='extruder', value='1')
        instance = ET.SubElement(plate, 'model_instance')
        ET.SubElement(instance, 'metadata', key='object_id', value=wrapper_id)
        ET.SubElement(instance, 'metadata', key='instance_id', value='0')
        ET.SubElement(out_build, tag('item'), objectid=wrapper_id, printable='1')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as out:
        out.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        out.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        out.writestr('3D/3dmodel.model', ET.tostring(model, encoding='utf-8', xml_declaration=True))
        out.writestr('Metadata/model_settings.config', ET.tostring(config, encoding='utf-8', xml_declaration=True))
    placed = [(bounds[a][0] + delta[a], bounds[a][1] + delta[a]) for a in range(3)]
    res = {'volumes': counts, 'build_bounds_mm': bounds, 'translation_mm': delta, 'placed_bounds_mm': placed,
           'converted_sha256': digest(target),
           'policy': 'printed volumes plus typed negative/modifier volumes per object; rigid translation; float64 XML'}
    if scale != 1.0:
        res['uniform_scale'] = str(scale)
    if rotation is not None:
        res['rotation_matrix'] = rotation
    return res


PROD = 'http://schemas.microsoft.com/3dmanufacturing/production/2015/06'


def export_production_plate(source, target, decisions, slot_colors):
    """Copy a production 3MF and recolor the filament the plate already uses.

    Orca 2.4.2 slices this Bambu package only when every zip entry stays
    byte-identical except filament_colour. Rewriting model_settings extruder
    values aborts inside a vector access, and shortening the filament arrays
    does the same. Every plate object already names one filament index, so
    that index is recolored to the one slot the whole plate selected. A plate
    that mixes slots is refused rather than sliced as one color.
    """
    manifest = inventory(source)
    if decisions.get('source_sha256') != manifest['source_sha256'] or decisions.get('mode') != 'per_part':
        raise RuntimeError('multicolor geometry requires exact-source per_part decisions')
    choices = decisions['choices']
    expected = {row['key'] for row in source_colors.canonical_prompts(manifest)}
    if set(choices) != expected:
        raise RuntimeError('incomplete part/source-filament decisions')
    chosen = {choices['part:' + part['key']]['slot'] for part in manifest['parts']}
    if len(chosen) != 1:
        raise RuntimeError('production plate uses one filament index; mixed slots need per-object extruders')
    slot = chosen.pop()
    color = slot_colors.get(str(slot)) or slot_colors.get(slot)
    if not isinstance(color, str) or not re.fullmatch(r'#?[0-9A-Fa-f]{6}', color):
        raise RuntimeError('filament color must be an explicit six-digit RGB value')
    color = '#' + color.lstrip('#').upper()
    with zipfile.ZipFile(source) as archive:
        names = [name for name in archive.namelist() if not name.startswith('Auxiliaries/')]
        if 'Metadata/project_settings.config' not in names or 'Metadata/model_settings.config' not in names:
            raise RuntimeError('production plate export requires project and model settings')
        cfg = archive.read('Metadata/model_settings.config').decode()
        indexes = {meta.split('value="')[1].split('"')[0]
                   for meta in re.findall(r'<metadata key="extruder" value="\d+"', cfg)}
        if len(indexes) != 1:
            raise RuntimeError('production plate objects name more than one filament index')
        index = int(indexes.pop())
        project = archive.read('Metadata/project_settings.config')
        colours = json.loads(project)['filament_colour']
        if not 1 <= index <= len(colours):
            raise RuntimeError('plate filament index is outside the project filament list')
        current = colours[index - 1]
        payload = {name: archive.read(name) for name in names}
    # Recolor only the plate's own array entry. The same hex repeats, so match
    # by position inside the filament_colour array, not by value.
    lines = project.split(b'\n')
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(b'"filament_colour"'))
    entries = [i for i in range(start + 1, len(lines)) if lines[i].strip().startswith(b'"#')]
    end = next(i for i in range(start + 1, len(lines)) if b']' in lines[i])
    entries = [i for i in entries if i < end]
    if len(entries) != len(colours):
        raise RuntimeError('filament colour list does not match the project JSON')
    target_line = entries[index - 1]
    old = ('"' + current + '"').encode()
    if old not in lines[target_line]:
        raise RuntimeError('filament colour entry was not found verbatim')
    lines[target_line] = lines[target_line].replace(old, b'"' + color.encode() + b'"', 1)
    payload['Metadata/project_settings.config'] = b'\n'.join(lines)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as out:
        for name, data in payload.items():
            out.writestr(name, data)
    return {str(index - 1): slot}, {'source_sha256': digest(source), 'converted_sha256': digest(target),
                                    'filament_index': index, 'filament_colour': color,
                                    'policy': 'production package copy; one filament colour byte patch'}


_S = settings.current()
# Prime tower math assumes a square bed; use the short side so a rectangle stays safe.
BED_MM = min(_S['printer']['bed_mm'])
TOWER_MM = _S['prime_tower']['size_mm']
TOWER_MARGIN_MM = _S['prime_tower']['part_clearance_mm']
TOWER_EDGE_MM = _S['prime_tower']['edge_mm']


def _compose(outer, inner):
    """Apply inner, then outer.

    3MF transforms act on row vectors (see _apply): p' = p . A + t. Applying
    inner then outer gives A = A_inner . A_outer and t = t_inner . A_outer + t_outer.
    """
    out = [0.0] * 12
    for row in range(3):
        for col in range(3):
            out[row * 3 + col] = sum(inner[row * 3 + k] * outer[k * 3 + col] for k in range(3))
    for col in range(3):
        out[9 + col] = sum(inner[9 + k] * outer[k * 3 + col] for k in range(3)) + outer[9 + col]
    return out


def fit_transform(fit):
    """World-space 3MF transform for an operator-chosen fit, or None.

    fit is {'scale': s, 'rotation': [9 row-major, column-vector convention]},
    the same rotation orca_adapter.export_geometry applies (q = s * R * p).
    In 3MF row-vector form that is A = s * R^T with no translation, so the
    whole selection turns and shrinks rigidly about one common origin.
    """
    if not fit:
        return None
    from .orca_adapter import _check_rotation
    scale = float(fit.get('scale') or 1.0)
    if not 0 < scale <= 1:
        raise RuntimeError('fit scale must be greater than 0 and no more than 1')
    try:
        rotation = _check_rotation(fit.get('rotation')) or [1, 0, 0, 0, 1, 0, 0, 0, 1]
    except ValueError as exc:
        raise RuntimeError(f'fit {exc}') from exc
    if scale == 1.0 and rotation == [1, 0, 0, 0, 1, 0, 0, 0, 1]:
        return None
    return [scale * rotation[col * 3 + row] for row in range(3) for col in range(3)] + [0.0, 0.0, 0.0]


def _apply(matrix, point):
    return tuple(sum(point[j] * matrix[j * 3 + i] for j in range(3)) + matrix[9 + i] for i in range(3))


def _matrix(node):
    values = list(map(float, node.get('transform', ' '.join(map(str, IDENTITY))).split()))
    if len(values) != 12 or not all(math.isfinite(v) for v in values):
        raise RuntimeError('invalid 3MF transform')
    return values


def _world_item_points(archive, object_ids, fit=None):
    """World-space mesh vertices per selected build item, through the component chain.

    fit (a fit_transform matrix) is applied after the item transform, so the
    points are those of the scaled/rotated group. Original transforms stay in
    the archive; callers use the points to measure or place the derived plate.
    """
    root = ET.fromstring(archive.read('3D/3dmodel.model'))
    objects = {node.get('id'): node for node in root.iter() if node.tag.split('}')[-1] == 'object'}
    model_object_points = {}
    items = []
    for item in (node for node in root.iter() if node.tag.split('}')[-1] == 'item'):
        if item.get('objectid') not in object_ids:
            continue
        if item.get('printable', '1') != '1':
            raise RuntimeError('nonprintable build item requires explicit selection')
        obj = objects[item.get('objectid')]
        components = [node for node in obj.iter() if node.tag.split('}')[-1] == 'component']
        if not components:
            raise RuntimeError('production subset expects at least one component per build object')

        item_points = []
        for component in components:
            path_attr = next((value for key, value in component.attrib.items() if key.split('}')[-1] == 'path'), None)
            # Same-file components (BambuStudio painted projects) carry no path.
            path = path_attr.lstrip('/') if path_attr else '3D/3dmodel.model'
            if path not in model_object_points:
                m_root = ET.fromstring(archive.read(path))
                model_object_points[path] = {
                    o.get('id'): [(float(v.get('x')), float(v.get('y')), float(v.get('z')))
                                  for v in o.iter() if v.tag.split('}')[-1] == 'vertex']
                    for o in m_root.iter() if o.tag.split('}')[-1] == 'object'
                }
            comp_obj_id = component.get('objectid')
            points = model_object_points[path].get(comp_obj_id, [])
            if points:
                world = _compose(fit, _matrix(item)) if fit else _matrix(item)
                matrix = _compose(world, _matrix(component))
                item_points.extend([_apply(matrix, point) for point in points])
        if not item_points:
            raise RuntimeError('empty part geometry')
        items.append(item_points)
    if len(items) != len(object_ids):
        raise RuntimeError('geometry and selection inventory disagree')
    return items


def _world_points(archive, object_ids, fit=None):
    """Every world-space mesh vertex of the selected build items, flattened."""
    return [point for item_points in _world_item_points(archive, object_ids, fit)
            for point in item_points]


def _world_hull_xy(archive, object_ids, fit=None):
    """Convex hull of the selected build items' mesh vertices in the bed plane.

    Returns [(hull, bounds)] with one entry per build item: ``hull`` is the
    item's world-space XY convex hull as [(x, y), ...] in authored orientation
    (computed with orca_adapter's monotone-chain hull, the same one the
    full-size fit check sweeps), and ``bounds`` is the item's world AABB in
    the ``_world_bounds`` shape. The hull is a superset of the item's actual
    footprint, so hull separation implies mesh separation. Shared by the fit
    check (split_fit) and the merge planner (plate_merge) so both judge the
    same footprint.
    """
    from .orca_adapter import _hull
    out = []
    for item_points in _world_item_points(archive, object_ids, fit):
        hull = _hull([(p[0], p[1]) for p in item_points])
        bounds = [(min(p[a] for p in item_points), max(p[a] for p in item_points))
                  for a in range(3)]
        out.append((hull, bounds))
    return out


def _world_bounds(archive, object_ids, fit=None):
    """World AABB of selected build items, through their component chain.

    fit (a fit_transform matrix) is applied after the item transform, so the
    bounds are those of the scaled/rotated group. Original transforms stay in
    the archive; the caller uses this to choose the derived plate placement.
    """
    return [[(min(point[axis] for point in item_points), max(point[axis] for point in item_points))
             for axis in range(3)]
            for item_points in _world_item_points(archive, object_ids, fit)]


def export_single_color_plate(source, target, decisions, part_keys, bed=BED_MM, slot_colors=None, item_shifts=None, fit=None):
    """Derive one single-slot production plate without deleting source XML.

    Orca 2.4.2 refuses to load a package whose object or mesh blocks were
    removed (return -6), and it emits the source filament index (T2) when
    objects keep extruder 3. This copy therefore keeps every object,
    component, mesh file and relationship byte for byte. Plate membership is
    expressed only through the build item printable flag: selected items stay
    printable="1", every other item becomes printable="0". Every object and
    part extruder becomes logical filament 1, so the slice uses T0 only. The
    physical slot stays in the report and in slice_model(filament_slot=...).
    Selected items keep their original transforms when the group already fits
    the bed; otherwise one rigid translation is applied to selected items
    only. Mixed slots and a group that cannot fit are refused.

    item_shifts ({object_id: [dx, dy, dz]}) gives each selected object its own
    absolute translation (one-bed merge of several source plates). The caller
    owns spacing; every placed box is still checked against the bed.

    fit ({'scale': s, 'rotation': [9]}) is the operator's verified resize or
    reorientation. It is composed into every selected build item about one
    common origin before bounds, placement and the crop check, so the group
    keeps its authored layout, only smaller or turned. Meshes stay untouched.

    fit may also carry 'placement_mm': [x, y], the bed coordinates the
    (possibly turned) group's placed bounds must start at. The group is then
    shifted rigidly so its minimum XY lands exactly there instead of being
    kept as authored or centered; the caller owns proving that placement
    avoids any declared bed exclusion, and the bounds are still checked
    against the bed here.
    """
    manifest = inventory(source)
    world = fit_transform(fit)
    placement = None
    if fit and fit.get('placement_mm') is not None:
        raw = fit['placement_mm']
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise RuntimeError('fit placement_mm must be an [x, y] pair in bed coordinates')
        try:
            placement = [float(raw[0]), float(raw[1])]
        except (TypeError, ValueError) as exc:
            raise RuntimeError('fit placement_mm must be numeric bed coordinates') from exc
        if not all(math.isfinite(v) for v in placement) or any(v < 0 for v in placement):
            raise RuntimeError('fit placement_mm must be finite and on the bed')
        if item_shifts is not None:
            raise RuntimeError('a placed plate cannot reuse merge shifts planned without the placement')
    if world is not None and item_shifts is not None:
        raise RuntimeError('a resized plate cannot reuse merge shifts planned at authored size')
    if decisions.get('source_sha256') != manifest['source_sha256'] or decisions.get('mode') != 'per_part':
        raise RuntimeError('single-color plate requires exact-source per_part decisions')
    if decisions.get('schema') not in (None, 'part_slots_v1'):
        raise RuntimeError('unknown color decision schema')
    planner = source_colors.canonical_prompts if decisions.get('schema') == 'part_slots_v1' else source_colors.prompts
    if set(decisions['choices']) != {row['key'] for row in planner(manifest)}:
        raise RuntimeError('incomplete part/source-filament decisions')
    # Same rule as the multipart exporter: a part may not disagree with the
    # palette row it refers to, or the plate would be labeled for one slot
    # while the decisions say another.
    for part in manifest['parts']:
        palette = decisions['choices'].get(f"filament:{part['source_extruder']}")
        if palette and palette != decisions['choices']['part:' + part['key']]:
            raise RuntimeError('part selection contradicts its source filament selection')
    wanted = list(dict.fromkeys(part_keys))
    parts = [part for part in manifest['parts'] if part['key'] in wanted]
    if len(parts) != len(wanted) or len(wanted) != len(part_keys):
        raise RuntimeError('single-color plate part keys do not match the source inventory')
    slots = {decisions['choices']['part:' + part['key']]['slot'] for part in parts}
    if len(slots) != 1:
        raise RuntimeError('single-color plate mixes physical slots')
    slot = slots.pop()
    selected = {part['object_id'] for part in parts}
    # A build object that carries a selected part must not also carry a part
    # of another slot: the printable flag selects whole build objects.
    for part in manifest['parts']:
        if part['object_id'] in selected and part['key'] not in wanted:
            raise RuntimeError('selected build object also contains an unselected part')
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if 'Metadata/model_settings.config' not in names or '3D/3dmodel.model' not in names:
            raise RuntimeError('single-color plate requires production model settings')
        boxes = _world_bounds(archive, selected, world)
        payload = {name: archive.read(name) for name in names}
    minimum = [min(box[axis][0] for box in boxes) for axis in range(3)]
    maximum = [max(box[axis][1] for box in boxes) for axis in range(3)]
    margin = _S['layout']['single_copy_edge_mm']
    if item_shifts is not None:
        if {str(k) for k in item_shifts} != set(selected):
            raise RuntimeError('item shifts must name exactly the selected objects')
        shift = {str(k): [float(v) for v in vals] for k, vals in item_shifts.items()}
        with zipfile.ZipFile(source) as archive:
            single = {oid: _world_bounds(archive, {oid})[0] for oid in selected}
        moved = [[(box[a][0] + shift[oid][a], box[a][1] + shift[oid][a]) for a in range(3)]
                 for oid, box in single.items()]
        if any(b[a][0] < 0 or b[a][1] > bed - margin for b in moved for a in range(2)) or any(b[2][0] < -1e-3 for b in moved):
            raise RuntimeError('merged placement does not fit the target bed')
        if any(b[2][1] - b[2][0] > bed for b in moved):
            raise RuntimeError('part group exceeds the target bed height')
        placed = [(min(b[a][0] for b in moved), max(b[a][1] for b in moved)) for a in range(2)]
    else:
        if maximum[2] - minimum[2] > bed:
            raise RuntimeError('part group exceeds the target bed height')
        if world is not None and any(box[2][0] - minimum[2] > 0.05 for box in boxes):
            # Turning a laid-out group tips separate parts into the air.
            raise RuntimeError('resized layout lifts a part off the bed')
        if placement is not None:
            # Land the group's minimum XY exactly on the recorded placement
            # (e.g. one that avoids a declared bed exclusion, #221); Z keeps
            # the usual drop to the bed.
            shift = [placement[0] - minimum[0], placement[1] - minimum[1], -minimum[2]]
        elif all(minimum[axis] >= margin and maximum[axis] <= bed - margin for axis in range(2)) and abs(minimum[2]) < 1e-3:
            shift = [0.0, 0.0, 0.0]
        else:
            # Center, not corner: Orca adds brim/skirt outside the mesh and refuses
            # (-52) anything whose brim crosses the bed edge.
            shift = [bed / 2 - (minimum[0] + maximum[0]) / 2, bed / 2 - (minimum[1] + maximum[1]) / 2, -minimum[2]]
        placed = [(minimum[axis] + shift[axis], maximum[axis] + shift[axis]) for axis in range(2)]
        if any(high > bed - margin or low < 0 for low, high in placed):
            raise RuntimeError('part group does not fit the target bed without cropping')
        if placement is not None and any(abs(placed[axis][0] - placement[axis]) > 1e-6 for axis in range(2)):
            raise RuntimeError('placed plate does not start at the recorded placement')
    model_bytes = payload['3D/3dmodel.model']
    settings_bytes = payload['Metadata/model_settings.config']
    # Orca 2.4.2 rejects a plate (-52, "partly inside") when a printable=0 item
    # still overlaps the bed volume. Park those items in +X beyond the bed.
    park = {}
    with zipfile.ZipFile(source) as archive:
        for oid in sorted(_build_ids(model_bytes) - selected):
            low, high = _world_bounds(archive, {oid})[0][0]
            if low < bed + 50:
                park[oid] = float(bed + 50 - low)
    model_out, kept = _select_build_items(model_bytes, selected, shift, park, world)
    if sorted(kept) != sorted(selected):
        raise RuntimeError('derived plate dropped or duplicated a selected object')
    settings_out = _single_logical_filament(settings_bytes)
    settings_out = _collapse_to_one_plate(settings_out, selected)
    _validate_derived_plate(model_bytes, model_out, settings_out, selected)
    payload['3D/3dmodel.model'] = model_out
    payload['Metadata/model_settings.config'] = settings_out
    colour = None
    if slot_colors:
        row = slot_colors.get(str(slot)) or slot_colors.get(slot) or {}
        colour = row.get('hex') if isinstance(row, dict) else row
        if not isinstance(colour, str) or not re.fullmatch(r'#?[0-9A-Fa-f]{6}', colour):
            raise RuntimeError('filament color must be an explicit six-digit RGB value')
        if isinstance(row, dict) and row.get('physical_color_verified') is not True:
            raise RuntimeError('derived plate slot color is not physically verified')
        colour = '#' + colour.lstrip('#').upper()
        if 'Metadata/project_settings.config' not in payload:
            raise RuntimeError('derived plate slot color requires project settings')
        payload['Metadata/project_settings.config'] = _recolor_filament_indexes(
            payload['Metadata/project_settings.config'], {1}, colour)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as out:
        for name, data in payload.items():
            out.writestr(name, data)
    with zipfile.ZipFile(source) as archive:
        changed = sorted(name for name in payload if payload[name] != archive.read(name))
    return {'source_sha256': digest(source), 'converted_sha256': digest(target),
            'part_keys': [part['key'] for part in parts], 'object_ids': sorted(selected),
            'nonprintable_object_ids': sorted(_build_ids(model_out) - selected),
            'slot': slot, 'logical_filament': 1, 'translation_mm': shift,
            **({'fit': {'scale': float(fit.get('scale') or 1.0), 'rotation': fit.get('rotation'), 'item_transform': world,
                        **({'placement_mm': placement} if placement is not None else {})}} if world or placement is not None else {}),
            **({'placement_mm': placement} if placement is not None else {}), 'merged_placement': item_shifts is not None, 'bounds_mm': boxes,
            'placed_bounds_mm': placed, 'bed_mm': bed, 'changed_entries': changed,
            'policy': 'production package copy; every object, mesh and relationship kept; unselected build items printable=0; all extruders logical 1; selected transforms kept unless the group must shift to fit',
            **({'filament_colour': colour} if colour is not None else {})}


def _build_ids(model_bytes):
    return {match.decode() for match in re.findall(br'<item\b[^>]*\bobjectid="(\d+)"', model_bytes)}


def _select_build_items(model_bytes, selected, shift, park=None, fit=None):
    """Flip printable on build items only. Resource XML and meshes stay byte for byte.

    fit is composed into selected item transforms (item first, then fit), then
    the placement shift is added to the translation.
    """
    kept = []

    def edit(match):
        line = match.group(0)
        object_id = re.search(br'\bobjectid="(\d+)"', line).group(1).decode()
        flag = b'1' if object_id in selected else b'0'
        if re.search(br'\bprintable="[^"]*"', line):
            line = re.sub(br'\bprintable="[^"]*"', b'printable="' + flag + b'"', line, count=1)
        else:
            line = re.sub(br'\s*/?>$', lambda end: b' printable="' + flag + b'"' + end.group(0), line, count=1)
        if object_id not in selected:
            move = (park or {}).get(object_id)
            if move:
                transform = re.search(br'transform="([^"]+)"', line)
                values = list(map(float, transform.group(1).split()))
                values[9] += move
                line = line[:transform.start(1)] + b' '.join(repr(v).encode() for v in values) + line[transform.end(1):]
            return line
        kept.append(object_id)
        item_shift = shift.get(object_id, [0.0, 0.0, 0.0]) if isinstance(shift, dict) else shift
        if any(item_shift) or fit:
            transform = re.search(br'transform="([^"]+)"', line)
            if transform is None:
                raise RuntimeError('selected build item has no transform')
            values = list(map(float, transform.group(1).split()))
            if len(values) != 12:
                raise RuntimeError('invalid 3MF transform')
            if fit:
                values = _compose(fit, values)
            for axis in range(3):
                values[9 + axis] += item_shift[axis]
            line = line[:transform.start(1)] + b' '.join(repr(v).encode() for v in values) + line[transform.end(1):]
        return line

    out = re.sub(br'<item\b[^>]*>', edit, model_bytes)
    return out, kept


def _single_logical_filament(settings_bytes):
    """Point every object and part at logical filament 1. Nothing else changes."""
    return re.sub(br'(<metadata key="extruder" value=")\d+(")', br'\g<1>1\g<2>', settings_bytes)


def _collapse_to_one_plate(settings_bytes, selected):
    """Put every selected object on the first plate and drop the other plates.

    Orca decides plate membership from model_settings.config, not from build
    item positions. A merged layout that leaves an object listed on plate 2
    makes Orca see an empty plate 2 and exit with -50 (real Orca 2.4.2).
    """
    plates = list(re.finditer(br'<plate>.*?</plate>', settings_bytes, re.S))
    if len(plates) < 2:
        return settings_bytes
    instances = []
    for plate in plates:
        for inst in re.finditer(br'[ \t]*<model_instance>.*?</model_instance>\s*', plate.group(0), re.S):
            match = re.search(br'<metadata key="object_id" value="(\d+)"', inst.group(0))
            if match and match.group(1).decode() in selected:
                instances.append(inst.group(0))
    found = {re.search(br'value="(\d+)"', i).group(1).decode() for i in instances}
    if found != set(selected):
        raise RuntimeError('merged plate collapse lost or duplicated a selected object')
    first = plates[0].group(0)
    head = re.split(br'[ \t]*<model_instance>', first, maxsplit=1)[0]
    rebuilt = head + b''.join(instances) + b'  </plate>'
    out = settings_bytes[:plates[0].start()] + rebuilt
    tail = settings_bytes[plates[-1].end():]
    return out + tail


def _validate_derived_plate(model_before, model_after, settings_after, selected):
    """Fail closed before Orca sees a package whose references disagree."""
    strip = lambda data: re.sub(br'<item\b[^>]*>', b'', data)
    if strip(model_before) != strip(model_after):
        raise RuntimeError('derived plate changed resource XML outside build items')
    root = ET.fromstring(model_after)
    items = [node for node in root.iter() if node.tag.split('}')[-1] == 'item']
    printable = {item.get('objectid') for item in items if item.get('printable', '1') == '1'}
    if printable != set(selected):
        raise RuntimeError('derived plate printable build items disagree with the selected parts')
    resources = {node.get('id') for node in root.iter() if node.tag.split('}')[-1] == 'object'}
    if not {item.get('objectid') for item in items} <= resources:
        raise RuntimeError('derived plate build item names a missing object')
    values = set(re.findall(br'<metadata key="extruder" value="(\d+)"', settings_after))
    if values != {b'1'}:
        raise RuntimeError('derived plate still names more than one logical filament')
    settings = ET.fromstring(settings_after)
    configured = {node.get('id') for node in settings.iter() if node.tag == 'object'}
    if not set(selected) <= configured:
        raise RuntimeError('derived plate lost a selected object configuration')


def _recolor_filament_indexes(project, indexes, color):
    """Rewrite filament_colour entries this plate still uses. Other bytes stay."""
    colours = json.loads(project)['filament_colour']
    lines = project.split(b'\n')
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(b'"filament_colour"'))
    end = next(i for i in range(start + 1, len(lines)) if b']' in lines[i])
    entries = [i for i in range(start + 1, end) if lines[i].strip().startswith(b'"#')]
    if len(entries) != len(colours):
        raise RuntimeError('filament colour list does not match the project JSON')
    for index in indexes:
        if not 1 <= index <= len(colours):
            raise RuntimeError('plate filament index is outside the project filament list')
        target_line = entries[index - 1]
        old = ('"' + colours[index - 1] + '"').encode()
        if old not in lines[target_line]:
            raise RuntimeError('filament colour entry was not found verbatim')
        lines[target_line] = lines[target_line].replace(old, b'"' + color.encode() + b'"', 1)
    return b'\n'.join(lines)


def _translate_selected_items(model_bytes, selected, shift):
    """Translate selected build items and drop unselected resource objects.

    Mesh bytes are not rewritten. An unselected object is removed so its
    component cannot keep pointing at a mesh the plate no longer carries.
    """
    lines = model_bytes.split(b'\n')
    kept = []
    out = []
    for line in lines:
        match = re.search(br'<item\b[^>]*\bobjectid="(\d+)"[^>]*>', line)
        if match is None:
            out.append(line)
            continue
        if match.group(1).decode() not in selected:
            continue
        transform = re.search(br'transform="([^"]+)"', line)
        if transform is None:
            raise RuntimeError('selected build item has no transform')
        values = list(map(float, transform.group(1).split()))
        if len(values) != 12:
            raise RuntimeError('invalid 3MF transform')
        for axis in range(3):
            values[9 + axis] += shift[axis]
        replacement = b' '.join(repr(value).encode() for value in values)
        line = line[:transform.start(1)] + replacement + line[transform.end(1):]
        kept.append(match.group(1).decode())
        out.append(line)
    chosen = {str(object_id) for object_id in selected}

    def drop_resource(match):
        return b'' if match.group(1).decode() not in chosen else match.group(0)

    # Match one object open through its own close, including the multiline
    # component block. A greedy DOTALL match swallows every following object
    # and keeps an empty shell, which Orca then refuses to load.
    model_out = re.sub(br'<object\b[^>]*\bid="(\d+)"[^>]*>.*?</object>\n?', drop_resource, b'\n'.join(out), flags=re.S)
    return model_out, kept


def _drop_unselected_settings(settings_bytes, selected):
    """Remove unselected object and instance blocks without reformatting the rest."""
    text = settings_bytes.decode()
    def drop_object(match):
        return '' if match.group(1) not in selected else match.group(0)
    text = re.sub(r'<object id="(\d+)">.*?</object>\n?', drop_object, text, flags=re.S)
    def drop_instance(match):
        identity = dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"', match.group(0)))
        return '' if identity.get('object_id') not in selected else match.group(0)
    text = re.sub(r'<model_instance>.*?</model_instance>\n?', drop_instance, text, flags=re.S)
    return text.encode()


def _drop_unused_relationships(rels_bytes, unused_models):
    """Delete relationship lines whose target mesh was removed. Other lines stay."""
    unused = {name.lstrip('/') for name in unused_models}
    kept = []
    for line in rels_bytes.split(b'\n'):
        match = re.search(br'Target="([^"]+)"', line)
        target = match.group(1).decode().lstrip('/') if match else ''
        if target not in unused:
            kept.append(line)
    return b'\n'.join(kept)


def _tower_friendly_delta(bounds, centered, bed=BED_MM):
    """Centered placement unless the prime tower cannot fit beside it; then
    slide the whole layout (rigidly) toward a bed edge to free a tower lane."""
    w, h = bounds[0][1] - bounds[0][0], bounds[1][1] - bounds[1][0]
    lo, hi = TOWER_EDGE_MM, bed - TOWER_EDGE_MM
    cx, cy = (bed - w) / 2, (bed - h) / 2
    candidates = [(cx, cy), (cx, lo), (cx, hi - h), (lo, cy), (hi - w, cy),
                  (lo, lo), (hi - w, lo), (lo, hi - h), (hi - w, hi - h)]
    for x0, y0 in candidates:
        if x0 < lo - 1e-6 or y0 < lo - 1e-6 or x0 + w > hi + 1e-6 or y0 + h > hi + 1e-6:
            continue
        box = [(x0, x0 + w), (y0, y0 + h), (0, 0)]
        try:
            prime_tower_xy([box])
        except RuntimeError:
            continue
        return [x0 - bounds[0][0], y0 - bounds[1][0], centered[2]]
    return centered


def prime_tower_candidates(part_bounds, bed=BED_MM, tower=TOWER_MM, margin=TOWER_MARGIN_MM,
                           limit=4, spread=20):
    """Tower origins that clear every part by margin, best first.

    Mesh bounds are not the whole story: Orca's tree supports flare past the
    part footprint, so the best-scoring spot can still fail Orca's G-code
    conflict check. Callers retry the next candidate; candidates are kept at
    least `spread` mm apart so a retry actually moves the tower.
    """
    def overlaps(x, y):
        for (x0, x1), (y0, y1), _z in part_bounds:
            if x < x1 + margin and x + tower > x0 - margin and y < y1 + margin and y + tower > y0 - margin:
                return True
        return False

    def clearance(x, y):
        cx, cy = x + tower / 2, y + tower / 2
        gaps = []
        for (x0, x1), (y0, y1), _z in part_bounds:
            dx = 0 if x0 <= cx <= x1 else min(abs(cx - x0), abs(cx - x1))
            dy = 0 if y0 <= cy <= y1 else min(abs(cy - y0), abs(cy - y1))
            gaps.append((dx * dx + dy * dy) ** 0.5)
        return min(gaps) if gaps else bed

    step = 5
    # Orca grows the tower past its nominal width (brim plus purge depth); a
    # tower flush with the bed edge slices to G-code in the unprintable area.
    edge = int(TOWER_EDGE_MM)
    top = bed - tower - edge
    scored = sorted(((clearance(x, y), x, y)
                     for y in range(edge, int(top) + 1, step)
                     for x in range(edge, int(top) + 1, step) if not overlaps(x, y)),
                    key=lambda c: (-c[0], c[2], c[1]))
    if not scored:
        raise RuntimeError(f'no prime tower position clears every part on the {bed:g} mm bed')
    picked = []
    for _score, x, y in scored:
        if all(abs(x - px) >= spread or abs(y - py) >= spread for px, py in picked):
            picked.append((x, y))
            if len(picked) == limit:
                break
    return picked


def prime_tower_xy(part_bounds, bed=BED_MM, tower=TOWER_MM, margin=TOWER_MARGIN_MM):
    """Best axis-aligned tower origin (the old fixed (15, 150) landed inside a stencil)."""
    return prime_tower_candidates(part_bounds, bed=bed, tower=tower, margin=margin, limit=1)[0]


def _identity_for_key(source, key):
    from .source_colors import component_parts
    with zipfile.ZipFile(source) as archive:
        leaf = next(p for p in component_parts(archive) if p['key'] == key)
    return leaf['model_path'], leaf['object_id']
