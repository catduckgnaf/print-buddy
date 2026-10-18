"""Offline Orca adapter. Geometry conversion never imports project machine settings."""
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import xml.etree.ElementTree as ET
import zipfile
import slice_guard as sg
from slice_guard import pre_slice, post_slice

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates/orca'
# Bed edge clearance. Multiple copies keep the historical 8 mm; a lone part only needs
# room for the purge/skirt path (brim and skirt are off in the AD5X process template).
MULTI_COPY_EDGE_MM = 3.0
SINGLE_COPY_EDGE_MM = 1.0
NS = {'c': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_geometry(source, target, scale=1.0, rotation=None):
    """Flatten 3MF build/component transforms exactly; preserve every triangle/order.

    No mesh repair, merging or per-part rearrangement. An optional operator-selected
    rigid rotation, then uniform scale, is applied before rigid centering on AD5X bed.
    STL float32 rounding is recorded by hashes. Non-mm and nonprintable builds refuse.
    """
    scale = float(scale) if scale is not None else 1.0
    if not scale > 0:
        raise ValueError('scale must be greater than 0')
    _check_rotation(rotation)
    if has_cutters(source):
        # Flattening to STL would either print the cutter as a solid (Orca -101
        # conflict) or drop it and fill the hole. Keep it as a negative volume.
        if Path(target).suffix.lower() != '.3mf':
            raise RuntimeError('source has negative/modifier volumes; export to .3mf, not STL')
        from color_geometry import export_volume_plate
        return export_volume_plate(source, target, scale=scale, rotation=rotation)
    return _place_triangles(_3mf_triangles(source), target, scale, rotation)


def has_cutters(source):
    source = Path(source)
    if source.suffix.lower() != '.3mf':
        return False
    from source_colors import cutter_ids
    with zipfile.ZipFile(source) as archive:
        return bool(cutter_ids(archive))


_TRIANGLE_CACHE: dict = {}


def _cache_key(source):
    st = Path(source).stat()
    return (str(Path(source).resolve()), st.st_mtime_ns, st.st_size)


def _3mf_triangles(source):
    """Flattened build triangles of a 3MF, parsed once per process per file version.

    Fit checks read the same dense mesh many times (capacity, scale ladder, rotations).
    Parsing is ~20 s for 683k triangles, so it is cached on (path, mtime, size). The list
    is shared: callers must not mutate it.
    """
    key = _cache_key(source)
    hit = _TRIANGLE_CACHE.get(key)
    if hit is None:
        _TRIANGLE_CACHE.clear()  # one model per worker; never hold two dense meshes
        hit = _TRIANGLE_CACHE[key] = _parse_3mf_triangles(source)
    return hit


def _parse_3mf_triangles(source):
    with zipfile.ZipFile(source) as archive:
        models = {}
        def model(name):
            name = name.lstrip('/')
            if name not in models:
                root = ET.fromstring(archive.read(name))
                if root.get('unit', 'millimeter') != 'millimeter':
                    raise RuntimeError('only millimeter 3MF geometry supported')
                models[name] = (root, {o.get('id'): o for o in root.findall('c:resources/c:object', NS)})
            return models[name]
        def apply(point, t):
            # Same float operation order as sum(p[j] * t[j*3+i]) + t[9+i]; output is bit-identical.
            x, y, z = point
            return (0 + x * t[0] + y * t[3] + z * t[6] + t[9],
                    0 + x * t[1] + y * t[4] + z * t[7] + t[10],
                    0 + x * t[2] + y * t[5] + z * t[8] + t[11])
        def transform(node):
            values = list(map(float, node.get('transform', ' '.join(map(str, IDENTITY))).split()))
            if len(values) != 12:
                raise RuntimeError('invalid 3MF transform')
            return values
        def triangles(name, oid, chain, active):
            key = (name, oid)
            if key in active:
                raise RuntimeError('cyclic 3MF component reference')
            obj = model(name)[1][oid]
            mesh = obj.find('c:mesh', NS)
            if mesh is not None:
                vertices = [tuple(float(v.get(k)) for k in ('x', 'y', 'z')) for v in mesh.findall('c:vertices/c:vertex', NS)]
                for t in chain:  # transform each shared vertex once, not once per triangle reference
                    vertices = [apply(p, t) for p in vertices]
                for tri in mesh.findall('c:triangles/c:triangle', NS):
                    yield [vertices[int(tri.get(index))] for index in ('v1', 'v2', 'v3')]
            for component in obj.findall('c:components/c:component', NS):
                external = next((v for k, v in component.attrib.items() if k.endswith('}path')), name)
                yield from triangles(external.lstrip('/'), component.get('objectid'), [transform(component)] + chain, active | {key})
        from source_colors import cutter_ids
        cutters = cutter_ids(archive)
        root, objects = model('3D/3dmodel.model')
        result = []
        for item in root.findall('c:build/c:item', NS):
            if item.get('printable', '1') != '1':
                raise RuntimeError('nonprintable build item requires explicit selection')
            oid = item.get('objectid')
            if cutters and any(k[0] == oid for k in cutters):
                # Footprint/fit only: printed volumes, never negative or modifier volumes.
                top = objects[oid]
                for component in top.findall('c:components/c:component', NS):
                    if (oid, component.get('objectid')) in cutters:
                        continue
                    external = next((v for k, v in component.attrib.items() if k.endswith('}path')), '3D/3dmodel.model')
                    result.extend(triangles(external.lstrip('/'), component.get('objectid'),
                                            [transform(component), transform(item)], {('3D/3dmodel.model', oid)}))
                continue
            result.extend(triangles('3D/3dmodel.model', oid, [transform(item)], set()))
    if not result:
        raise RuntimeError('3MF contains no printable triangles')
    return result


def _check_rotation(rotation):
    if rotation is None:
        return None
    values = [float(v) for v in rotation]
    if len(values) != 9:
        raise ValueError('rotation must be a 3x3 row-major matrix')
    # Only rigid rotations: orthonormal rows and determinant +1 (no mirroring or scaling).
    rows = [values[0:3], values[3:6], values[6:9]]
    for i in range(3):
        for j in range(3):
            dot = sum(rows[i][k] * rows[j][k] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > 1e-6:
                raise ValueError('rotation must be orthonormal')
    det = (rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
           - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
           + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0]))
    if abs(det - 1.0) > 1e-6:
        raise ValueError('rotation must not mirror the model')
    return values


def _rotate(point, m):
    x, y, z = point
    return (m[0] * x + m[1] * y + m[2] * z, m[3] * x + m[4] * y + m[5] * z, m[6] * x + m[7] * y + m[8] * z)


def _place_triangles(result, target, scale=1.0, rotation=None):
    """Rotate (rigid), uniformly scale, then center on the AD5X bed with the lowest vertex on Z0."""
    scale = float(scale) if scale is not None else 1.0
    if not scale > 0:
        raise ValueError('scale must be greater than 0')
    rotation = _check_rotation(rotation)
    if rotation is not None:
        result = [[_rotate(p, rotation) for p in tri] for tri in result]
    if scale != 1.0:
        result = [[(p[0] * scale, p[1] * scale, p[2] * scale) for p in tri] for tri in result]
    # One rigid translation only: center XY on AD5X and put the lowest vertex on Z0.
    bounds = [(min(p[a] for t in result for p in t), max(p[a] for t in result for p in t)) for a in range(3)]
    delta = [110 - sum(bounds[a]) / 2 for a in (0, 1)] + [-bounds[2][0]]
    placed_bounds = [(bounds[a][0] + delta[a], bounds[a][1] + delta[a]) for a in range(3)]
    with Path(target).open('wb') as output:
        output.write(b'3MF transformed triangles, rigid centered translation'.ljust(80, b'\0'))
        output.write(struct.pack('<I', len(result)))
        for triangle in result:
            output.write(struct.pack('<12fH', 0, 0, 0, *(p[a] + delta[a] for p in triangle for a in range(3)), 0))
    res = {'triangles': len(result), 'build_bounds_mm': bounds, 'translation_mm': delta,
           'placed_bounds_mm': placed_bounds,
           'converted_sha256': digest(target), 'policy': 'all triangles; component/build transforms; rigid translation only; float32 STL'}
    if scale != 1.0:
        res['uniform_scale'] = str(scale)
        res['scale_policy'] = 'uniform scale applied to source vertices before rigid bed centering'
    if rotation is not None:
        res['rotation_matrix'] = rotation
        res['policy'] += '; operator-selected rigid rotation applied before scale'
    return res


def read_stl_triangles(path):
    """Read binary or ASCII STL triangles as [[(x, y, z)] * 3]."""
    data = Path(path).read_bytes()
    if len(data) >= 84:
        count = struct.unpack('<I', data[80:84])[0]
        if len(data) == 84 + count * 50:
            return [[struct.unpack('<3f', data[84 + i * 50 + k:84 + i * 50 + k + 12]) for k in (12, 24, 36)]
                    for i in range(count)]
    text = data.decode('utf-8', errors='ignore')
    points = [tuple(map(float, m.groups())) for m in re.finditer(
        r'vertex\s+(\S+)\s+(\S+)\s+(\S+)', text)]
    if not points or len(points) % 3:
        raise RuntimeError(f'{path} is not a readable STL')
    return [points[i:i + 3] for i in range(0, len(points), 3)]


def source_triangles(source):
    """All printable triangles of a 3MF (build transforms applied) or STL, in source coordinates.

    Cached per process; the returned list is shared and must not be mutated.
    """
    source = Path(source)
    if source.suffix.lower() == '.3mf':
        return _3mf_triangles(source)
    key = ('stl',) + _cache_key(source)
    hit = _TRIANGLE_CACHE.get(key)
    if hit is None:
        _TRIANGLE_CACHE.clear()
        hit = _TRIANGLE_CACHE[key] = read_stl_triangles(source)
    return hit


_FOOTPRINT_CACHE: dict = {}


def _footprint(source, rotation=None):
    """(XY convex hull, z_min, z_max) of the model after an optional rigid rotation.

    Orca's arrange only sees the XY hull, so the fit probe needs nothing else. Cached on
    file version + rotation so repeated scale probes skip the dense mesh entirely.
    """
    source = Path(source)
    key = (_cache_key(source), tuple(rotation) if rotation is not None else None)
    hit = _FOOTPRINT_CACHE.get(key)
    if hit is None:
        if len(_FOOTPRINT_CACHE) > 16:
            _FOOTPRINT_CACHE.clear()
        points = _unique_points(source_triangles(source))
        if not points:
            raise RuntimeError(f'Orca fit probe cannot determine capacity for {source}: projected geometry is empty')
        if rotation is None:
            xy = [(p[0], p[1]) for p in points]
            zs = [p[2] for p in points]
        else:
            m = rotation
            xy = [(m[0] * x + m[1] * y + m[2] * z, m[3] * x + m[4] * y + m[5] * z) for x, y, z in points]
            zs = [m[6] * x + m[7] * y + m[8] * z for x, y, z in points]
        hit = _FOOTPRINT_CACHE[key] = (_hull(xy), min(zs), max(zs))
    return hit


def place_stl(source, target, scale=1.0, rotation=None):
    """Write a rotated/scaled/bed-centered STL from a 3MF or STL source."""
    source = Path(source)
    if source.suffix.lower() == '.3mf':
        return export_geometry(source, target, scale=scale, rotation=rotation)
    return _place_triangles(read_stl_triangles(source), target, scale, rotation)


PROCESS_KEYS = ('layer_height', 'initial_layer_print_height', 'wall_loops', 'sparse_infill_density',
                'sparse_infill_pattern', 'brim_type', 'brim_width', 'brim_object_gap', 'enable_support',
                'support_type', 'support_on_build_plate_only', 'top_shell_layers', 'bottom_shell_layers',
                'top_shell_thickness', 'bottom_shell_thickness', 'gap_fill_target', 'filter_out_gap_fill')


RANGE_ERROR = re.compile(r'^(\w+): (\S+) not in range \[([-0-9.eE+]+),([-0-9.eE+]+)\]', re.M)


def _clamp(value, low, high):
    def one(v):
        try:
            x = float(v)
        except ValueError:
            return v
        if low <= x <= high:
            return v
        x = min(max(x, low), high)
        return str(int(x)) if x.is_integer() else repr(x)
    if isinstance(value, list):
        return [one(v) for v in value]
    return ','.join(one(v) for v in str(value).split(','))


IMPORTED_AUTO_SENTINELS = {
    'raft_first_layer_expansion': '-1',
    'tree_support_wall_count': '-1',
}


def _rewrite_project_settings(path, settings, name):
    tmp = Path(path).with_suffix('.sanitizing')
    with zipfile.ZipFile(path) as archive, zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as out:
        for info in archive.infolist():
            out.writestr(info, json.dumps(settings, indent=4) if info.filename == name else archive.read(info))
    tmp.replace(path)


def sanitize_project_settings(path, log_text=''):
    """Normalize only the known Bambu auto sentinels rejected by Orca.

    The source of record is never passed here: slice_model creates a private 3MF
    copy first. Returns {key: [old, new]} for audit provenance. Orca reports only
    its first invalid imported setting, so normalize either known sentinel on that
    private copy before the normal slice attempt. log_text is ignored; other
    negative settings stay untouched.
    """
    del log_text
    name = 'Metadata/project_settings.config'
    if Path(path).suffix.lower() != '.3mf':
        return {}
    with zipfile.ZipFile(path) as archive:
        if name not in archive.namelist():
            return {}
        settings = json.loads(archive.read(name))
    changed = {}
    for key, sentinel in IMPORTED_AUTO_SENTINELS.items():
        if key not in settings:
            continue
        value = settings[key]
        if isinstance(value, list):
            normalized = ['0' if str(v) == sentinel else v for v in value]
        elif isinstance(value, (str, int, float)) and str(value) == sentinel:
            normalized = '0'
        else:
            continue
        if normalized != value:
            settings[key] = normalized
            changed[key] = [value, '0']
    if not changed:
        return {}
    _rewrite_project_settings(path, settings, name)
    return changed


def clamp_rejected_settings(path, log_text):
    """Clamp only keys Orca names in a range error, to Orca's stated bounds.

    This is the post-failure recovery. It does not pre-normalize imported
    sentinels and it does not touch keys absent from the log.
    """
    bad = {m.group(1): (float(m.group(3)), float(m.group(4))) for m in RANGE_ERROR.finditer(log_text or '')}
    if not bad or Path(path).suffix.lower() != '.3mf':
        return {}
    name = 'Metadata/project_settings.config'
    with zipfile.ZipFile(path) as archive:
        if name not in archive.namelist():
            return {}
        settings = json.loads(archive.read(name))
    changed = {}
    for key, (low, high) in bad.items():
        if key in settings:
            new = _clamp(settings[key], low, high)
            if new != settings[key]:
                changed[key] = [settings[key], new]
                settings[key] = new
    if not changed:
        return {}
    _rewrite_project_settings(path, settings, name)
    return changed


def finalize_zmod(path, color, material):
    """Single logical tool equivalent of official zmod-preprocess color/MD5 steps.

    Source: ghzserg/zmod_preprocess zmod-preprocess.py, color insertion then
    first-line MD5 over all remaining bytes. Does not select a physical slot.
    """
    from multicolor_contract import finalize
    return finalize(path, (color, material))


def slice_model(source, folder, state, brim=None, first_layer=False, color_decisions=None, preserve_layout=False, filament_slot=None, item_shifts=None, copies=None, scale=None, rotation=None, supports=None, object_ids=None):
    source, folder = Path(source), Path(folder)
    if scale is not None:
        scale = float(scale)
        if not scale > 0:
            raise ValueError('scale must be greater than 0')
    rotation = _check_rotation(rotation)
    if rotation is not None and (preserve_layout or item_shifts or
                                 (color_decisions and color_decisions.get('mode') == 'per_part')):
        raise ValueError('rotation is only supported for whole-model single-color slicing')
    folder.mkdir(parents=True, exist_ok=True)
    machine, process, filament = [json.loads((TEMPLATES / f'{name}.json').read_text()) for name in ('machine', 'process', 'filament')]
    if float(state['nozzle']['diameter_mm']) != 0.4:
        raise RuntimeError('resolved AD5X profile requires installed 0.4 mm nozzle')
    author = {}
    geometry = {'policy': 'original STL unchanged', 'source_sha256': digest(source)}
    from source_colors import inventory, validate_decisions
    from model_job import resolve_filament_selection
    color_decisions = (validate_decisions(inventory(source), color_decisions, state, resolve_filament_selection)
                       if color_decisions else None)
    mapping = None
    if color_decisions and color_decisions.get('mode') == 'per_part':
        from color_geometry import export_color_geometry
        input_path = folder / 'geometry.3mf'
        mapping, geometry = export_color_geometry(source, input_path, color_decisions, item_shifts=item_shifts,
                                                  object_ids=object_ids, scale=scale)
        with zipfile.ZipFile(source) as archive:
            if 'Metadata/project_settings.config' in archive.namelist():
                author = json.loads(archive.read('Metadata/project_settings.config'))
    elif source.suffix.lower() == '.3mf' and not preserve_layout:
        with zipfile.ZipFile(source) as archive:
            if 'Metadata/project_settings.config' in archive.namelist():
                author = json.loads(archive.read('Metadata/project_settings.config'))
        input_path = folder / ('geometry.3mf' if has_cutters(source) else 'geometry.stl')
        geometry.update(export_geometry(source, input_path, scale=scale or 1.0, rotation=rotation))
        if scale is not None:
            geometry['scale_policy'] = 'uniform scale applied to transformed source vertices before bed centering'
    elif rotation is not None or (source.suffix.lower() == '.stl' and scale is not None):
        # Direct STL with an operator-selected orientation or scale: transform vertices
        # before slicing so every slicer receives identical resolved geometry.
        input_path = folder / 'geometry.stl'
        geometry.update(place_stl(source, input_path, scale=scale or 1.0, rotation=rotation))
    else:
        if source.suffix.lower() == '.3mf':
            with zipfile.ZipFile(source) as archive:
                if 'Metadata/project_settings.config' in archive.namelist():
                    author = json.loads(archive.read('Metadata/project_settings.config'))
        input_path = source
        geometry = {'policy': 'derived plate; documented translation preserved; no arrange', 'source_sha256': digest(source)}
    # Preserve author structural intent, not P1S motion/material calibration.
    process.update({k: author[k] for k in PROCESS_KEYS if k in author})
    process.update({'filter_out_gap_fill': '0', 'gap_fill_target': author.get('gap_fill_target', 'everywhere'),
                    'enable_support': author.get('enable_support', '0'), 'brim_width': str(brim) if brim is not None else author.get('brim_width', '0')})
    if supports is not None:
        process.update({'enable_support': '1' if supports else '0'})
        if supports:
            process.setdefault('support_type', 'tree(auto)')
    if first_layer:
        process.update({'layer_height': '0.2', 'initial_layer_print_height': '0.2', 'wall_loops': '2',
                        'brim_width': '0', 'brim_type': 'no_brim', 'initial_layer_speed': '20',
                        'initial_layer_infill_speed': '20', 'enable_support': '0'})
    baseline = state.get('calibration_baseline') or {}
    mesh = baseline.get('native_mesh', 'auto')
    if not isinstance(mesh, str) or not re.fullmatch(r'[A-Za-z0-9_]+', mesh):
        raise RuntimeError('invalid calibration baseline mesh')
    machine['machine_start_gcode'] = re.sub(r'\bMESH=\S+', 'MESH=' + mesh, machine['machine_start_gcode'])
    machine['machine_start_gcode'] = ("M190 S[bed_temperature_initial_layer_single]\n"
                                     "M104 S[nozzle_temperature_initial_layer] T0\n" +
                                     machine['machine_start_gcode'])
    machine['default_print_profile'] = process['name']
    slots = state.get('ifs_slots') or {}
    if filament_slot is not None:
        slot = slots.get(str(filament_slot)) or slots.get(filament_slot)
        if not isinstance(slot, dict):
            raise RuntimeError(f'derived plate slot {filament_slot} is not in the saved IFS map')
        if not slot.get('spoolman_id') or not slot.get('material') or not slot.get('physical_color_verified'):
            raise RuntimeError('IFS slot color/material mapping is unverified')
        if slot.get('spoolman_id') != state['spool'].get('spoolman_id'):
            # The selected slot, not whichever spool happened to be active last,
            # defines this job's material; launch syncs the active spool to it.
            # Validated against Spoolman below before it is trusted.
            state = {**state, 'spool': {**state['spool'], 'spoolman_id': slot['spoolman_id'],
                                        'name': slot.get('name'), 'material': slot['material']}}
            import urllib.request
            spool_url = f"{state['spoolman_url']}/api/v1/spool/{slot['spoolman_id']}"
            with urllib.request.urlopen(spool_url, timeout=6) as response:
                spool = json.load(response)
            from printer_state import same_material
            if spool.get('archived') or not same_material(spool.get('filament', {}).get('material'), slot['material']):
                raise RuntimeError(f'IFS slot {filament_slot} maps to missing, archived, or mismatched Spoolman spool')
        color = slot.get('hex')
    else:
        matching = [s for s in slots.values() if s.get('spoolman_id') == state['spool'].get('spoolman_id')]
        color = state['spool'].get('color_code')
        if slots:
            if len(matching) != 1:
                raise RuntimeError('selected spool must resolve to exactly one IFS slot')
            slot = matching[0]
            from printer_state import same_material
            if not same_material(slot.get('material'), state['spool']['material']) or not slot.get('physical_color_verified'):
                raise RuntimeError('IFS slot color/material mapping is unverified')
            color = slot.get('hex')
    if color is not None:
        if not isinstance(color, str) or not re.fullmatch(r'#?[0-9A-Fa-f]{6}', color):
            raise RuntimeError('filament color must be an explicit six-digit RGB value')
        color = '#' + color.lstrip('#').upper()
    filament.update({'filament_type': [state['spool']['material']], 'filament_density': [str(state['spool']['density'])],
                     'filament_colour': [color or filament['filament_colour'][0]],
                     'nozzle_temperature': [str(state['temps_c']['nozzle'])],
                     'nozzle_temperature_initial_layer': [str(state['temps_c']['nozzle'])]})
    for key in ('cool_plate_temp', 'eng_plate_temp', 'hot_plate_temp', 'textured_plate_temp'):
        filament[key] = filament[key + '_initial_layer'] = [str(state['temps_c']['bed'])]
    configs = []
    for name, data in zip(('machine', 'process', 'filament'), (machine, process, filament)):
        path = folder / f'{name}.json'
        path.write_text(json.dumps(data, indent=2) + '\n')
        configs.append(path)
    filament_paths = [configs[2]]
    if mapping:
        import copy
        machine.update({'single_extruder_multi_material': '1', 'change_filament_gcode': ''})
        tower_x, tower_y = geometry['prime_tower_xy_mm']
        process.update({'enable_prime_tower': '1', 'prime_tower_width': '45',
                        'wipe_tower_x': str(tower_x), 'wipe_tower_y': str(tower_y),
                        'purge_in_prime_tower': '0'})
        configs[0].write_text(json.dumps(machine, indent=2) + '\n')
        configs[1].write_text(json.dumps(process, indent=2) + '\n')
        filament_paths = []
        for tool, physical_slot in mapping.items():
            slot = state['ifs_slots'][str(physical_slot)]
            from printer_state import same_material
            if not same_material(slot['material'], state['spool']['material']):
                raise RuntimeError('mixed material requires independently calibrated per-slot temperatures/density')
            data = copy.deepcopy(filament)
            data.update({'name': f"Hermes slot {physical_slot} {slot['material']}",
                         'filament_settings_id': [f"Hermes slot {physical_slot} {slot['material']}"],
                         'filament_colour': ['#' + slot['hex'].lstrip('#').upper()],
                         'filament_is_support': ['0']})
            path = folder / f'filament_tool_{tool}.json'
            path.write_text(json.dumps(data, indent=2) + '\n')
            filament_paths.append(path)
        configs.extend(filament_paths)
    prepositioned_scale = (scale is not None or rotation is not None) and input_path != source and not preserve_layout
    if copies and int(copies) > 1 and not (preserve_layout or item_shifts or mapping):
        # Clone placement must be explicit: slicer auto-arrange can overlap clones on
        # transformed STL input, producing a self-conflicting G-code path.
        points = _unique_points(source_triangles(input_path))
        if not points:
            raise RuntimeError(f'cannot arrange {copies} copies: transformed geometry is empty')
        bounds = [(min(p[a] for p in points), max(p[a] for p in points)) for a in range(3)]
        width, depth = bounds[0][1] - bounds[0][0], bounds[1][1] - bounds[1][0]
        bed_x, bed_y = state.get('bed_mm', [220, 220])
        count = int(copies)
        cols = max(1, int((float(bed_x) + 10) // (width + 10)))
        rows = (count + cols - 1) // cols
        if rows * (depth + 10) > float(bed_y) + 10:
            raise RuntimeError(f'{count} copies of {width:g}x{depth:g} mm do not fit the printer bed')
        shifts = []
        for index in range(count):
            col, row = index % cols, index // cols
            shifts.append((col * (width + 10), row * (depth + 10)))
        clones = folder / 'clones.stl'
        triangles = source_triangles(input_path)
        duplicated = [[(point[0] + dx, point[1] + dy, point[2]) for point in triangle]
                      for dx, dy in shifts for triangle in triangles]
        geometry.update(_place_triangles(duplicated, clones))
        input_path = clones
        copies = None
    output = folder / 'plate_1.gcode'
    prepositioned_scale = (scale is not None or rotation is not None) and input_path != source and not preserve_layout
    command = ['flatpak', 'run', 'com.orcaslicer.OrcaSlicer', '--load-settings', f'{configs[0]};{configs[1]}',
               '--load-filaments', ';'.join(map(str, filament_paths)),
               # Mapped (multicolor) geometry is already placed and the prime tower
               # computed around it; Orca's default auto-arrange would move parts
               # into the tower lane (-101 G-code conflict), so disable it explicitly.
               *(['--arrange', '0', '--orient', '0'] if (preserve_layout or item_shifts or prepositioned_scale or mapping) else ['--arrange', '1', '--orient', '0', '--ensure-on-bed']),
               *(['--clone-objects', str(copies)] if (copies and int(copies) > 1) else []),
               '--allow-newer-file', '--slice', '0', '--outputdir', str(folder), str(input_path)]
    if scale is not None and not mapping:
        if input_path.suffix.lower() == '.3mf':
            raise ValueError('uniform scale must be applied to exported geometry before slicing a 3MF')
        # Normal 3MF intake (and any rotated input) was already scaled during export.
        # Orca's CLI scale is retained only for direct STL input, where no pre-export occurs.
        if input_path == source:
            command[-1:-1] = ['--scale', str(scale)]
    sanitized = {}
    # Keep the untouched base templates for protected-setting comparison; gate the
    # final effective configs immediately before invoking Orca.
    base_profile = {**json.loads((TEMPLATES / 'machine.json').read_text()),
                    **json.loads((TEMPLATES / 'process.json').read_text()),
                    **json.loads((TEMPLATES / 'filament.json').read_text())}
    effective_profile = {**machine, **process, **filament}
    placed_bounds = geometry.get('placed_bounds_mm')
    if placed_bounds and len(placed_bounds) >= 2:
        bounds_xy = (placed_bounds[0][0], placed_bounds[1][0], placed_bounds[0][1], placed_bounds[1][1])
    else:
        bounds_xy = None
    bed = tuple(state.get('bed_mm', [220, 220]))
    try:
        printable = machine.get('printable_area')
        if printable:
            points = [tuple(map(float, point.split('x'))) for point in printable]
            bed = (max(p[0] for p in points) - min(p[0] for p in points),
                   max(p[1] for p in points) - min(p[1] for p in points))
    except (TypeError, ValueError):
        pass
    selected_slot = filament_slot or 1
    tool_slots = {int(tool): int(slot) for tool, slot in mapping.items()} if mapping else {0: int(selected_slot)}
    # Protected-key differences here include adapter-sanctioned profile assembly
    # (for example the resolved start-G-code template), not untrusted overrides.
    # Only block on geometric/tooling findings that this adapter can establish.
    gate = pre_slice(bounds=bounds_xy, bed=bed, profile=effective_profile,
                     before_profile=None, filaments=len(filament_paths),
                     ifs_slots=4, tool_slots=tool_slots)
    if gate.status == 'blocked':
        raise RuntimeError('Pre-slice guard blocked: ' + '; '.join(gate.blocked))
    # Unknown placement is advisory, never a false block.
    if bounds_xy is None:
        gate.warn('Placed mesh bounds are unavailable; adapter did not block on geometry bounds.')
    if input_path == source and source.suffix.lower() == '.3mf':
        # Never mutate the source of record; Orca reads a private copy we may sanitize.
        private = folder / ('orca_input' + source.suffix)
        private.write_bytes(source.read_bytes())
        input_path = private
        command[-1] = str(private)
    if input_path.suffix.lower() == '.3mf':
        # Bambu's -1 auto sentinels are invalid in Orca 2.4. Normalize only these
        # two known settings on the private preparation copy; preserve source bytes.
        sanitized.update(sanitize_project_settings(input_path))
    # Never accept stale output if a failed slicer leaves the preceding artifact behind.
    output.unlink(missing_ok=True)
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    (folder / 'orca.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        # Bounded recovery clamps only keys named in Orca's range error.
        # Already-normalized sentinels are not rewritten by this path.
        fixed = clamp_rejected_settings(input_path, result.stdout + result.stderr)
        if fixed:
            sanitized.update(fixed)
            result = subprocess.run(command, capture_output=True, text=True, timeout=600)
            (folder / 'orca.log').write_text(result.stdout + result.stderr)
    if mapping and result.returncode and _orca_conflict(folder):
        # Tower placement clears mesh bounds, but tree supports and brims can
        # still reach it. Retry the precomputed alternate tower origins only;
        # never relax Orca's conflict check.
        tried = [list(geometry['prime_tower_xy_mm'])]
        for tower_x, tower_y in geometry.get('prime_tower_candidates_mm', [])[1:]:
            process.update({'wipe_tower_x': str(tower_x), 'wipe_tower_y': str(tower_y)})
            configs[1].write_text(json.dumps(process, indent=2) + '\n')
            output.unlink(missing_ok=True)
            (folder / 'result.json').unlink(missing_ok=True)
            result = subprocess.run(command, capture_output=True, text=True, timeout=600)
            (folder / 'orca.log').write_text(result.stdout + result.stderr)
            tried.append([tower_x, tower_y])
            if not (result.returncode and _orca_conflict(folder)):
                break
        geometry['prime_tower_xy_mm'] = tried[-1]
        geometry['prime_tower_attempts_mm'] = tried
    slicer = 'OrcaSlicer'
    fallback = None
    if result.returncode or not output.is_file() or output.stat().st_size == 0:
        # Only an actual Orca execution failure reaches this branch. All Print Bitch
        # validation and placement refusals above remain fail-closed and never invoke Bambu.
        details = _orca_failure_details(folder)
        log_text = (result.stdout + '\n' + result.stderr).strip()
        if re.search(r'G-code conflicts detected', log_text, re.I):
            # A conflict is a slicer failure, not a Print Bitch refusal. Bambu gets
            # one isolated attempt after Orca's own retry/candidate logic is exhausted.
            orca_failure = ('Orca detected G-code conflicts: inspect the model for '
                            'overlapping/intersecting parts, separate or reposition them, then retry; '
                            'Bambu Studio is now the fallback attempt')
        else:
            orca_failure = (f'Orca slicing failed ({result.returncode}) or no G-code output{details}'
                            if details else
                            f'Orca slicing failed ({result.returncode}) or no G-code output')
        bambu_dir = folder / 'bambu'
        bambu_dir.mkdir(exist_ok=True)
        bambu_machine = bambu_dir / 'machine.json'
        bambu_process = bambu_dir / 'process.json'
        bambu_filaments = []
        # Bambu receives the already resolved production profiles. Do not use the
        # spike profile or its T[next_extruder] shortcut; this preserves the exact
        # production machine start/end and change-filament G-code values.
        bambu_machine.write_text(json.dumps(machine, indent=2) + '\n')
        # Bambu Studio reads Orca's percentage line widths as absolute millimeters.
        # Orca percentages are relative to the machine nozzle, not line_width.
        bambu_profile = dict(process)
        percent_width_keys = [
            key for key, raw_value in bambu_profile.items()
            if key.endswith('_line_width') and str(raw_value).strip().endswith('%')
        ]
        if percent_width_keys:
            try:
                nozzle_values = machine['nozzle_diameter']
                nozzle_diameter = float(nozzle_values[0] if isinstance(nozzle_values, list) else nozzle_values)
                for key in percent_width_keys:
                    value = str(bambu_profile[key]).strip()
                    bambu_profile[key] = f'{nozzle_diameter * float(value[:-1]) / 100:g}'
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                raise RuntimeError(
                    f'cannot convert Orca percentage line widths for Bambu fallback: {exc}'
                ) from exc
        bambu_process.write_text(json.dumps(bambu_profile, indent=2) + '\n')
        for index, source_filament in enumerate(filament_paths):
            path = bambu_dir / f'filament_tool_{index}.json'
            path.write_bytes(source_filament.read_bytes())
            bambu_filaments.append(path)
        output.unlink(missing_ok=True)
        bambu_command = [
            'flatpak', 'run', '--unshare=network', '--command=bambu-studio',
            'com.bambulab.BambuStudio', '--datadir', str(bambu_dir / 'datadir'),
            '--load-settings', f'{bambu_machine};{bambu_process}',
            '--load-filaments', ';'.join(map(str, bambu_filaments)),
            *(['--arrange', '0', '--orient', '0'] if (preserve_layout or item_shifts or prepositioned_scale or mapping)
              else ['--arrange', '1', '--orient', '0', '--ensure-on-bed']),
            *(['--clone-objects', str(copies)] if (copies and int(copies) > 1) else []),
            '--allow-newer-file', '--slice', '0', '--outputdir', str(folder), str(input_path),
        ]
        try:
            bambu_result = subprocess.run(bambu_command, capture_output=True, text=True, timeout=600)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise RuntimeError(f'{orca_failure}; Bambu Studio fallback failed to start: {exc}') from exc
        (folder / 'bambu.log').write_text(bambu_result.stdout + bambu_result.stderr)
        if bambu_result.returncode or not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(
                f'{orca_failure}; Bambu Studio fallback failed ({bambu_result.returncode}) or produced no G-code; '
                f'see {folder / "orca.log"} and {folder / "bambu.log"}'
            )
        configs.extend([bambu_machine, bambu_process, *bambu_filaments])
        command = bambu_command
        slicer = 'Bambu Studio'
        fallback = {'from': 'OrcaSlicer', 'reason': orca_failure, 'orca_log': str(folder / 'orca.log'),
                    'bambu_log': str(folder / 'bambu.log')}
    text = output.read_text()
    generator = re.search(r'^; generated by ((?:OrcaSlicer|BambuStudio).+)$', text, re.M)
    if generator is None:
        raise RuntimeError(f'output is not generated by {slicer}')
    if mapping:
        from multicolor_contract import finalize
        finalize(output, None, state, mapping)
    else:
        finalize_zmod(output, filament['filament_colour'][0], state['spool']['material'])
    result_path = folder / 'result.json'
    post_gate = post_slice(output, result_json=None if fallback else (result_path if result_path.is_file() else None),
                           bed=bed, ifs_slots=4, tool_slots=tool_slots)
    baseline_gate = (sg.enforce_approved_baseline(output)
                     if output.stat().st_size > 1000 else sg.Result())
    if baseline_gate.status == 'blocked':
        raise RuntimeError('Post-slice protected-settings guard blocked: ' + '; '.join(baseline_gate.blocked))
    if baseline_gate.warnings:
        post_gate.warn(*baseline_gate.warnings)
    if post_gate.status == 'blocked':
        raise RuntimeError('Post-slice guard blocked: ' + '; '.join(post_gate.blocked))
    warnings = gate.warnings + post_gate.warnings + baseline_gate.warnings
    return output, {'tool_mapping': mapping, 'source_sha256': digest(source), 'gcode_sha256': digest(output),
                    'config_sha256': {str(p): digest(p) for p in configs}, 'geometry': geometry,
                    'slice_guard': {'status': 'warnings' if warnings else 'ok', 'warnings': warnings},
                    "slicer_command": command, "generator": generator.group(1), "slicer": slicer,
                    'fallback': fallback,
                    'author_process': {k: author[k] for k in PROCESS_KEYS if k in author},
                    'sanitized_author_settings': sanitized,
                    'offline_geometry_and_slicer': True}, configs


def _orca_conflict(folder: Path) -> bool:
    """True when Orca's result.json reports its G-code path conflict (-101)."""
    try:
        payload = json.loads((folder / 'result.json').read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return 'G-code conflicts detected' in str(payload.get('error_string', ''))


def _orca_failure_details(folder: Path) -> str:
    """Summarize result.json errors and named objects in Orca's debug log."""
    details = ''
    try:
        payload = json.loads((folder / 'result.json').read_text())
    except (OSError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict):
        error = payload.get('error_string')
        code = payload.get('return_code')
        if code is not None or error:
            details = f"; Orca return_code {code}: {error}"

    if _orca_conflict(folder):
        # Orca writes its debug log as 00000.log; orca.log is our CLI capture.
        log_text = ''
        for log in sorted(folder.glob('*.log')):
            try:
                log_text += log.read_text(errors='replace') + '\n'
            except OSError:
                pass
        names = []
        for line in log_text.splitlines():
            match = re.search(r'conflicts? found between\s+(.+?)\s+and\s+(.+?)(?:[.\r\t]|$)', line, re.I)
            if match:
                names.extend((match.group(1).strip(), match.group(2).strip()))
        if names:
            unique_names = list(dict.fromkeys(names))
            details += '; conflicting objects: ' + ' and '.join(unique_names)
    return details


def quantity_buttons(max_copies: int) -> list[int]:
    """Offer 1, 2, and the verified maximum when physically possible."""
    if max_copies <= 1:
        return [1]
    return sorted({1, min(2, max_copies), max_copies})


def _source_plate_count(source) -> int:
    """Count source plates named in a 3MF project; 0 when none are declared."""
    try:
        with zipfile.ZipFile(source) as archive:
            names = set(archive.namelist())
            ids = {int(m.group(1)) for n in names if (m := re.fullmatch(r'Metadata/plate_(\d+)\.(?:png|gcode)', n))}
            if 'Metadata/model_settings.config' in names:
                root = ET.fromstring(archive.read('Metadata/model_settings.config'))
                for plate in root.iter('plate'):
                    for meta in plate.iter('metadata'):
                        if meta.get('key') == 'plater_id' and meta.get('value') is not None:
                            ids.add(int(meta.get('value')))
            return len(ids)
    except (zipfile.BadZipFile, ET.ParseError, ValueError, OSError):
        return 0


def _multi_plate_capacity(source: Path, state: dict, scale: float = 1.0, single_margin: float = 1.0) -> int:
    """Check if all plates in a multi-plate 3MF fit the bed bounds at `scale`."""
    try:
        import model_job as mj
        import color_geometry as cg
        bed = state.get('bed_mm', [220, 220])
        max_h = float(state.get('max_print_height_mm', 220))
        eff_w = float(bed[0]) - 2 * single_margin
        eff_d = float(bed[1]) - 2 * single_margin
        manifest = mj.plate_manifest(source)
        with zipfile.ZipFile(source) as archive:
            for p in manifest.get('plates', []):
                ids = {str(o) for o in p.get('object_ids', [])}
                if not ids:
                    continue
                boxes = cg._world_bounds(archive, ids)
                if not boxes:
                    continue
                min_x = min(b[0][0] for b in boxes)
                max_x = max(b[0][1] for b in boxes)
                min_y = min(b[1][0] for b in boxes)
                max_y = max(b[1][1] for b in boxes)
                min_z = min(b[2][0] for b in boxes)
                max_z = max(b[2][1] for b in boxes)
                dx = (max_x - min_x) * scale
                dy = (max_y - min_y) * scale
                dz = (max_z - min_z) * scale
                if dz > max_h + 0.05:
                    return 0
                fits = (dx <= eff_w and dy <= eff_d) or (dy <= eff_w and dx <= eff_d)
                if not fits:
                    return 0
        return 1
    except Exception:
        return 1


def orca_plate_capacity(source: Path, state: dict, spacing_mm: float = 10.0, edge_margin_mm: float | None = None,
                        scale: float = 1.0, copy_limit: int = 16, allow_rotations: bool = True,
                        rotation=None, supports: bool | None = None) -> int:
    """Return the Orca-confirmed copy count; probe failures raise and are never treated as no-fit.

    Copies keep ``MULTI_COPY_EDGE_MM`` from the bed edge; a lone copy only needs
    ``SINGLE_COPY_EDGE_MM`` (brim/skirt are off by default), so a model that fits once
    but not with multi-copy margins reports 1 instead of a false 0. Height is checked too.
    ``supports`` probes with the same support setting the slice will use (None: the 3MF
    author's setting, else off). Tree supports can double a part's footprint, so a probe
    without them over-reports copies.
    """
    import tempfile
    source = Path(source)
    scale = float(scale)
    if not 0 < scale <= 1:
        raise ValueError('scale must be greater than 0 and no more than 1')
    copy_limit = int(copy_limit)
    if copy_limit < 1:
        raise ValueError('copy_limit must be at least 1')
    bed = state.get('bed_mm', [220, 220])
    bed_x, bed_y = float(bed[0]), float(bed[1])
    max_h = float(state.get('max_print_height_mm', 220))
    multi_margin = MULTI_COPY_EDGE_MM if edge_margin_mm is None else float(edge_margin_mm)
    single_margin = SINGLE_COPY_EDGE_MM if edge_margin_mm is None else float(edge_margin_mm)

    rotation = _check_rotation(rotation)
    if rotation is not None:
        allow_rotations = False  # the chosen yaw is exact; Orca must not turn it again
    if source.suffix.lower() == '.3mf' and rotation is None:
        if _source_plate_count(source) > 1:
            return _multi_plate_capacity(source, state, scale=scale, single_margin=single_margin)
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        # Orca's arrange only sees each object's XY convex hull, and the probe exports a
        # project without slicing. A prism of that hull arranges identically, but loads in
        # seconds instead of minutes for dense meshes (683k triangles took ~2 min per probe).
        # The hull is cached per file + rotation, so scale/rotation retries skip the mesh.
        hull, z_min, z_max = _footprint(source, rotation)
        if len(hull) < 3:
            raise RuntimeError(f'Orca fit probe cannot determine capacity for {source}: degenerate footprint')
        hdr = b'fit probe convex hull prism'.ljust(80, b'\0')
        min_x, max_x = min(p[0] for p in hull), max(p[0] for p in hull)
        min_y, max_y = min(p[1] for p in hull), max(p[1] for p in hull)
        w = max_x - min_x
        d = max_y - min_y
        if (z_max - z_min) * scale > max_h + 0.05:
            return 0  # Orca happily "arranges" a part taller than the gantry; refuse here.

        scaled_w, scaled_d = w * scale, d * scale
        expand_mm = max(0.0, (spacing_mm - 2.0) / 2.0)
        sx = (scaled_w + 2 * expand_mm) / w if w > 0 else 1.0
        sy = (scaled_d + 2 * expand_mm) / d if d > 0 else 1.0
        cx, cy = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0

        z_lo, z_hi = 0.0, (z_max - z_min) * scale  # rest on the bed like _place_triangles
        if z_hi - z_lo < 0.01:
            z_hi = z_lo + 0.01

        def write_stl(path, fx, fy):
            pts = [(cx + (x - cx) * fx, cy + (y - cy) * fy) for x, y in hull]
            n = len(pts)
            tris = []
            for i in range(1, n - 1):  # hull is CCW: bottom faces down, top faces up
                tris.append(((*pts[0], z_lo), (*pts[i + 1], z_lo), (*pts[i], z_lo)))
                tris.append(((*pts[0], z_hi), (*pts[i], z_hi), (*pts[i + 1], z_hi)))
            for i in range(n):
                a, b = pts[i], pts[(i + 1) % n]
                tris.append(((*a, z_lo), (*b, z_lo), (*b, z_hi)))
                tris.append(((*a, z_lo), (*b, z_hi), (*a, z_hi)))
            with open(path, 'wb') as out:
                out.write(hdr)
                out.write(struct.pack('<I', len(tris)))
                for tri in tris:
                    out.write(struct.pack('<12fH', 0, 0, 0, *(c for p in tri for c in p), 0))

        dilated_stl = tmp / 'dilated.stl'
        write_stl(dilated_stl, sx, sy)
        single_stl = tmp / 'single.stl'
        write_stl(single_stl, scale, scale)
        m_base = json.loads(Path(TEMPLATES / 'machine.json').read_text())
        ppath = TEMPLATES / 'process.json'
        fpath = TEMPLATES / 'filament.json'
        if supports is None and source.suffix.lower() == '.3mf':
            try:
                with zipfile.ZipFile(source) as archive:
                    author = json.loads(archive.read('Metadata/project_settings.config'))
                supports = str(author.get('enable_support', '0')) == '1'
            except (KeyError, OSError, ValueError, zipfile.BadZipFile):
                supports = False
        if supports:
            p_tmpl = json.loads(ppath.read_text())
            p_tmpl['enable_support'] = '1'
            p_tmpl.setdefault('support_type', 'tree(auto)')
            ppath = tmp / 'process_supports.json'
            ppath.write_text(json.dumps(p_tmpl, indent=2))

        def machine_for(edge):
            m_tmpl = dict(m_base)
            m_tmpl['printable_area'] = [f"{edge}x{edge}", f"{bed_x - edge}x{edge}",
                                        f"{bed_x - edge}x{bed_y - edge}", f"{edge}x{bed_y - edge}"]
            path = tmp / f'machine_{edge}.json'
            path.write_text(json.dumps(m_tmpl, indent=2))
            return path

        def probe(stl, copies, edge, tag):
            probe_dir = tmp / f'probe_{tag}_{copies}'
            probe_dir.mkdir(exist_ok=True)
            cmd = [
                'flatpak', 'run', 'com.orcaslicer.OrcaSlicer',
                '--load-settings', f'{machine_for(edge)};{ppath}',
                '--load-filaments', str(fpath),
                '--allow-newer-file', '--clone-objects', str(copies),
                '--arrange', '1', *(['--allow-rotations'] if allow_rotations else []), '--orient', '0',
                '--ensure-on-bed',
                '--outputdir', str(probe_dir),
                '--export-3mf', 'probe.3mf',
                str(stl)
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f'Orca fit probe timed out for {copies} copies') from exc
            p3mf = probe_dir / 'probe.3mf'
            if result.returncode != 0:
                raise RuntimeError(
                    f'Orca fit probe failed ({result.returncode}) for {copies} copies: '
                    f'{result.stderr.strip() or result.stdout.strip()}'
                )
            if not p3mf.is_file() or p3mf.stat().st_size == 0:
                raise RuntimeError(f'Orca fit probe produced no valid project for {copies} copies')
            try:
                with zipfile.ZipFile(p3mf) as z:
                    cfg = z.read('Metadata/model_settings.config').decode('utf-8', errors='ignore')
                    root = ET.fromstring(cfg)
            except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
                raise RuntimeError(f'Orca fit probe output is malformed for {copies} copies') from exc
            plate_count = sum(1 for item in root.iter('plate')
                              if any(meta.get('key') == 'plater_id' for meta in item.iter('metadata')))
            if plate_count != 1:
                return False
            try:
                arranged = export_geometry(p3mf, probe_dir / 'arranged.stl')
                bounds = arranged['build_bounds_mm']
                x_bounds, y_bounds = bounds[0], bounds[1]
            except (KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
                raise RuntimeError(f'Orca fit probe cannot inspect arranged bounds for {copies} copies') from exc
            tolerance = 0.1
            return (
                float(x_bounds[0]) >= edge - tolerance and
                float(x_bounds[1]) <= bed_x - edge + tolerance and
                float(y_bounds[0]) >= edge - tolerance and
                float(y_bounds[1]) <= bed_y - edge + tolerance
            )

        eff_edge = max(0.0, multi_margin - expand_mm)
        if copy_limit == 1:
            return 1 if probe(single_stl, 1, single_margin, 'single') else 0
        eff_w = bed_x - 2 * multi_margin
        eff_d = bed_y - 2 * multi_margin
        max_possible = max(1, min(copy_limit, int(
            (eff_w * eff_d) / max(1.0, (scaled_w + spacing_mm) * (scaled_d + spacing_mm)) * 1.5
        ) + 1))
        if not probe(dilated_stl, 1, eff_edge, 'multi'):
            return 1 if probe(single_stl, 1, single_margin, 'single') else 0
        best = 1
        for c in range(2, max_possible + 1):
            if probe(dilated_stl, c, eff_edge, 'multi'):
                best = c
            else:
                break
        return best


def verified_scale_choices(source: Path, state: dict) -> list[float]:
    """Return three verified uniform scales, led by the smallest reduction that fits.

    Fast path: the analytic footprint/height bound for the authored orientation gives a
    0.1% precise candidate that one or two Orca probes confirm (instead of ~8 sequential
    probes). Unreadable geometry falls back to the whole-percent Orca binary search.
    """
    source = Path(source)
    if source.suffix.lower() == '.3mf' and _source_plate_count(source) > 1:
        if orca_plate_capacity(source, state, scale=1.0, copy_limit=1) > 0:
            return [1.0]
        if orca_plate_capacity(source, state, scale=0.5, copy_limit=1) < 1:
            return []
        low, high = 50, 99
        while low < high:
            middle = (low + high + 1) // 2
            if orca_plate_capacity(source, state, scale=middle / 100.0, copy_limit=1) > 0:
                low = middle
            else:
                high = middle - 1
        return _scale_ladder(low / 100.0)
    try:
        tris = source_triangles(source)
    except Exception:
        tris = None
    if tris:
        bound = _orientation_bound(_unique_points(tris), state, IDENTITY_ROT, yaw_search=False)[0]
        if bound >= 1.0 and orca_plate_capacity(source, state, scale=1.0, copy_limit=1) > 0:
            return [1.0]
        maximum = _confirm_scale(lambda s: orca_plate_capacity(source, state, scale=s, copy_limit=1) > 0,
                                 min(bound, 0.999))
        if maximum is not None:
            return _scale_ladder(maximum)
    if orca_plate_capacity(source, state, scale=1.0, copy_limit=1) > 0:
        return [1.0]
    if orca_plate_capacity(source, state, scale=0.5, copy_limit=1) < 1:
        return []

    low, high = 50, 99
    while low < high:
        middle = (low + high + 1) // 2
        if orca_plate_capacity(source, state, scale=middle / 100.0, copy_limit=1) > 0:
            low = middle
        else:
            high = middle - 1
    return _scale_ladder(low / 100.0)


def _scale_ladder(maximum):
    """Minimum shrink, a medium size, and the smallest structurally safe size (50%)."""
    if maximum < 0.52:
        return []
    medium = 0.75 if maximum > 0.75 else round((maximum + 0.5) / 2, 2)
    if medium >= maximum:
        medium = round(maximum - 0.01, 3)
    return [round(maximum, 3), medium, 0.5]


def _confirm_scale(fits, bound, window=0.03):
    """Largest 0.1%-step scale <= the analytic bound that Orca confirms.

    Tries the bound first (usually right), then bisects the window below it
    (~5 probes), then falls back to coarse 1% steps down to 50%. Orca occasionally
    aborts on a specific scale (boost bad_rational); after one retry such a point
    counts as not fitting, which can only lower the reported maximum.
    """
    errors = []

    def safe(scale):
        for _ in range(2):
            try:
                return fits(scale)
            except RuntimeError as exc:
                errors.append(exc)
        return False

    hi = int(bound * 1000)
    if hi < 500:
        return None
    if safe(hi / 1000.0):
        return hi / 1000.0
    lo = max(500, hi - int(window * 1000))
    if not safe(lo / 1000.0):
        step = lo - 10
        while step >= 500:
            if safe(step / 1000.0):
                lo, hi = step, step + 10
                break
            step -= 10
        else:
            if errors and len(errors) >= 4:
                raise errors[-1]  # Orca is broken, not the model: never report "does not fit".
            return None
    while hi - lo > 1:  # invariant: lo fits, hi does not
        middle = (lo + hi) // 2
        if safe(middle / 1000.0):
            lo = middle
        else:
            hi = middle
    return lo / 1000.0


def scale_label(scale):
    """98.6% / 75% style label: one decimal only when the scale is not a whole percent."""
    pct = round(float(scale) * 100, 1)
    return f'{pct:.1f}'.rstrip('0').rstrip('.') + '%'


# ---- Orientation search: offer rotated alternatives whenever a model does not fit as authored.

IDENTITY_ROT = [1, 0, 0, 0, 1, 0, 0, 0, 1]
# Map each model axis to "up" (Z). Upside-down Z is never a fit improvement, so it is omitted.
UP_AXES = {
    '+Y': ('Rotate 90° on X', [1, 0, 0, 0, 0, -1, 0, 1, 0]),
    '-Y': ('Rotate 90° on X', [1, 0, 0, 0, 0, 1, 0, -1, 0]),
    '+X': ('Rotate 90° on Y', [0, 0, -1, 0, 1, 0, 1, 0, 0]),
    '-X': ('Rotate 90° on Y', [0, 0, 1, 0, 1, 0, -1, 0, 0]),
}
SUPPORT_THRESHOLD_NZ = -0.866  # faces within 30° of a horizontal ceiling (process.json threshold 30°)


def _matmul(a, b):
    return [sum(a[r * 3 + k] * b[k * 3 + c] for k in range(3)) for r in range(3) for c in range(3)]


def _yaw(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [c, -s, 0, s, c, 0, 0, 0, 1]


def _unique_points(tris):
    return list({p for tri in tris for p in tri})


def _hull(points):
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _usable(state, single=True):
    bed = state.get('bed_mm', [220, 220])
    margin = SINGLE_COPY_EDGE_MM if single else MULTI_COPY_EDGE_MM
    return (float(bed[0]) - 2 * margin, float(bed[1]) - 2 * margin,
            float(state.get('max_print_height_mm', 220)))


def _orientation_bound(points, state, rotation, yaw_search=True):
    """Largest uniform scale (<=1) at which ``rotation`` (+ best yaw) fits one copy; returns
    (scale, yaw_degrees, dims_mm_at_full_size)."""
    eff_w, eff_d, max_h = _usable(state)
    rotated = [_rotate(p, rotation) for p in points]
    zs = [p[2] for p in rotated]
    height = max(zs) - min(zs)
    hull = _hull([(p[0], p[1]) for p in rotated])
    def footprint(deg):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        xs = [c * x - s * y for x, y in hull]
        ys = [s * x + c * y for x, y in hull]
        return max(xs) - min(xs), max(ys) - min(ys)
    def fit(deg):
        w, d = footprint(deg)
        xy = min(eff_w / w if w else 9, eff_d / d if d else 9)
        # When height binds, every yaw ties on scale: prefer the most XY clearance.
        return (round(min(xy, max_h / height if height else 9), 4), xy)
    best = 0.0
    if yaw_search:
        best = max((step * 1.0 for step in range(180)), key=fit)
        best = max((best + tenth / 10.0 for tenth in range(-10, 11)), key=fit)
    w, d = footprint(best)
    scale = min(eff_w / w if w else 9, eff_d / d if d else 9, max_h / height if height else 9)
    return min(1.0, scale), round(best % 180, 1), [round(w, 1), round(d, 1), round(height, 1)]


_FACE_CACHE: dict = {}


def _faces(tris):
    """Per-triangle (area, unit normal, vertices), computed once per mesh object."""
    hit = _FACE_CACHE.get(id(tris))
    if hit is None or hit[0] is not tris:
        faces = []
        for a, b, c in tris:
            u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
            v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            length = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
            if length:
                faces.append((length / 2, n[0] / length, n[1] / length, n[2] / length, a, b, c))
        _FACE_CACHE.clear()
        hit = _FACE_CACHE[id(tris)] = (tris, faces)
    return hit[1]


def _surface_stats(tris, rotation):
    """(bed contact area, unsupported overhang area) in mm² for an orientation."""
    r6, r7, r8 = (float(v) for v in rotation[6:9])
    faces = _faces(tris)
    floor = min(r6 * p[0] + r7 * p[1] + r8 * p[2] for f in faces for p in f[4:])
    contact = overhang = 0.0
    for area, nx, ny, nz, a, b, c in faces:
        # Rotating the mesh rotates its normals by the same matrix: only rotated nz matters.
        if r6 * nx + r7 * ny + r8 * nz < SUPPORT_THRESHOLD_NZ:
            top = max(r6 * p[0] + r7 * p[1] + r8 * p[2] for p in (a, b, c))
            if top - floor < 0.3:
                contact += area
            else:
                overhang += area
    return contact, overhang


def rotation_alternatives(source: Path, state: dict, authored_max: float = 0.0, limit: int = 2) -> list[dict]:
    """Rotated orientations that print larger than the authored orientation can.

    Each result is Orca-verified for one copy and carries an exact rigid rotation matrix
    (axis change plus the best bed yaw) for slicing, a 0.1% precise maximum scale, the
    resulting size, and whether new overhangs likely need supports.
    """
    import tempfile
    source = Path(source)
    if source.suffix.lower() == '.3mf' and _source_plate_count(source) > 1:
        return []  # multi-plate projects are split/merged by the planner, never re-oriented
    tris = source_triangles(source)
    points = _unique_points(tris)
    _, authored_overhang = _surface_stats(tris, IDENTITY_ROT)
    candidates: list[dict] = []
    # Same model, turned on the bed (yaw only): no new overhangs.
    scale, yaw, dims = _orientation_bound(points, state, IDENTITY_ROT)
    if yaw not in (0.0, 90.0) and scale > authored_max + 0.004:
        candidates.append({'name': f'Turn {round(yaw)}° on the bed', 'axis': '+Z', 'rotation': _yaw(yaw),
                           'bound': scale, 'dims_full_mm': dims, 'supports': False})
    for axis_pair in (('+Y', '-Y'), ('+X', '-X')):
        options = []
        for axis in axis_pair:
            name, up = UP_AXES[axis]
            contact, overhang = _surface_stats(tris, up)
            options.append((contact, -overhang, axis, name, up, overhang))
        contact, _, axis, name, up, overhang = max(options)
        scale, yaw, dims = _orientation_bound(points, state, up)
        if scale <= authored_max + 0.004:
            continue
        needs = overhang > authored_overhang * 1.5 + 100.0
        candidates.append({'name': name, 'axis': axis, 'rotation': _matmul(_yaw(yaw), up), 'bound': scale,
                           'dims_full_mm': dims, 'supports': needs, 'bed_contact_mm2': round(contact),
                           'overhang_mm2': round(overhang)})
    # Opposite-face pairs and X/Y turns of symmetric parts produce the same envelope;
    # verify each distinct envelope once, keeping the steadier (more contact) option.
    unique: list[dict] = []
    for row in sorted(candidates, key=lambda r: (r['supports'], -r.get('bed_contact_mm2', 0))):
        envelope = sorted(row['dims_full_mm'])
        if any(abs(u['bound'] - row['bound']) < 0.002 and
               all(abs(a - b) < 1.0 for a, b in zip(sorted(u['dims_full_mm']), envelope)) for u in unique):
            continue
        unique.append(row)
    candidates = unique
    if not candidates:
        return []
    verified = []
    # Sequential on purpose: concurrent flatpak Orca runs collide (exit 243).
    # The rotation goes straight to the probe, which uses the cached rotated hull
    # instead of writing and re-reading a dense rotated mesh per orientation.
    for row in candidates:
        fits = lambda s, rot=row['rotation'], sup=bool(row['supports']): orca_plate_capacity(
            source, state, scale=s, copy_limit=1, allow_rotations=False, rotation=rot, supports=sup) > 0
        verified.append(_confirm_scale(fits, row['bound']))
    results = []
    for row, scale in zip(candidates, verified):
        if scale is None or scale <= authored_max:
            continue
        row = dict(row, scale=scale, full_size=scale >= 1.0,
                   dims_mm=[round(v * scale, 1) for v in row['dims_full_mm']])
        row['rotation'] = [round(v, 9) for v in row['rotation']]
        contact = row.get('bed_contact_mm2')
        footprint = row['dims_mm'][0] * row['dims_mm'][1]
        # Tall part on a sliver of bed: recommend a brim so it does not topple.
        row['brim'] = contact is not None and (contact < 400 or contact < 0.05 * footprint)
        extras = [x for x, on in (('supports', row['supports']), ('brim', row['brim'])) if on]
        row['label'] = (f"{row['name']}, {'full size' if scale >= 1.0 else scale_label(scale)}"
                        + (f" (needs {' + '.join(extras)})" if extras else ''))
        results.append(row)
    results.sort(key=lambda r: (-r['scale'], r['supports']))
    return results[:limit]


def fit_options(source: Path, state: dict) -> dict:
    """Everything the intake needs after a no-fit, in one worker call.

    ``scales``: verified authored-orientation ladder (may be empty).
    ``rotations``: Orca-verified rotated orientations that print larger than the
    best authored scale (stood upright etc.), each with supports/brim warnings.
    """
    scales = verified_scale_choices(source, state)
    try:
        rotations = rotation_alternatives(source, state, authored_max=scales[0] if scales else 0.0)
    except (RuntimeError, ValueError, OSError) as exc:
        return {'scales': scales, 'rotations': [], 'rotation_error': str(exc)}
    return {'scales': scales, 'rotations': rotations}
