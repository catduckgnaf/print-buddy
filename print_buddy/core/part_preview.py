"""Offline 3MF painted-region facts and lightweight highlighted previews."""
from __future__ import annotations

from collections import Counter
import hashlib
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageDraw
import numpy as np


def _hex_rgba(color):
    value = color.lstrip('#')
    if len(value) != 6:
        return (235, 70, 160, 255)
    return tuple(bytes.fromhex(value)) + (255,)


def inspect(source, manifest, output_dir, size=512):
    """Return deterministic per-question region descriptions and cached PNG paths."""
    source = Path(source)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        root = ET.fromstring(archive.read('3D/3dmodel.model'))
        ns = {'m': root.tag.split('}')[0][1:]} if root.tag.startswith('{') else {}
        objects = {obj.get('id'): obj for obj in root.findall('.//m:object', ns)}
        object_meta = {}
        settings_name = 'Metadata/model_settings.config'
        if settings_name in archive.namelist():
            settings = ET.fromstring(archive.read(settings_name))
            for obj in settings.findall('object'):
                meta = {m.get('key'): m.get('value') for m in obj.findall('metadata')}
                object_meta[obj.get('id')] = meta
                for part in obj.findall('part'):
                    pm = {m.get('key'): m.get('value') for m in part.findall('metadata')}
                    object_meta[part.get('id')] = pm
        plate_by_object = {}
        if settings_name in archive.namelist():
            settings = ET.fromstring(archive.read(settings_name))
            for plate_no, plate in enumerate(settings.findall('plate'), 1):
                for instance in plate.findall('model_instance'):
                    md = {m.get('key'): m.get('value') for m in instance.findall('metadata')}
                    plate_by_object[md.get('object_id')] = plate_no
        build_items = [node for node in root.iter() if node.tag.endswith('item')]
        build_xforms = {node.get('objectid'): _transform(node.get('transform')) for node in build_items}

        region_data = {}
        all_vertices = []
        build_ids = {node.get('objectid') for node in build_items}
        for oid, obj in objects.items():
            # Restrict the preview to directly printable objects referenced by the build.
            if oid not in build_ids:
                continue
            verts = obj.find('.//m:vertices', ns)
            tris = obj.find('.//m:triangles', ns)
            if verts is None or tris is None:
                continue
            coordinates = np.asarray([[float(v.get('x')), float(v.get('y')), float(v.get('z'))]
                                      for v in verts], dtype=float)
            triangles, codes = [], []
            for triangle in tris:
                try:
                    triangles.append([int(triangle.get(k)) for k in ('v1', 'v2', 'v3')])
                    codes.append(triangle.get('paint_color', ''))
                except (TypeError, ValueError):
                    continue
            faces = np.asarray(triangles, dtype=int)
            if not len(faces):
                continue
            # Apply build transform only for top-level printable objects.
            transform = build_xforms.get(oid, np.eye(4))
            world = coordinates @ transform[:3, :3].T + transform[:3, 3]
            all_vertices.append(world)
            meta = object_meta.get(oid, {})
            name = meta.get('name') or obj.get('name') or f'Object {oid}'
            region_data[oid] = {'name': name, 'vertices': world, 'faces': faces, 'codes': codes,
                                'plate': plate_by_object.get(oid)}

        if not all_vertices:
            raise ValueError('3MF has no directly renderable triangle mesh')
        all_points = np.concatenate(all_vertices)
        global_lo, global_hi = all_points.min(axis=0), all_points.max(axis=0)
        centers = np.concatenate([d['vertices'][d['faces']].mean(axis=1) for d in region_data.values()])
        normals = {}
        for oid, data in region_data.items():
            triangles = data['vertices'][data['faces']]
            n = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
            lengths = np.linalg.norm(n, axis=1)
            data['normals'] = n / np.maximum(lengths[:, None], 1e-12)
            data['areas'] = lengths / 2

        filaments = {str(f['source_extruder']): f for f in manifest.get('filaments', [])}
        color_rows = {}
        for oid, data in region_data.items():
            for code in set(data['codes']):
                if not code:
                    continue
                color_rows.setdefault(code, []).append((oid, data))
        output = []
        for code, regions in sorted(color_rows.items(), key=lambda item: int(item[0], 16) if all(c in '0123456789abcdefABCDEF' for c in item[0]) else item[0]):
            ext = int(code, 16) & 0xff
            filament = filaments.get(str(ext)) or filaments.get(str(max(1, ext)))
            color = (filament or {}).get('color') or '#FF4FA3'
            label = _color_name(color)
            selected = []
            facts = []
            for oid, data in regions:
                mask = np.asarray([item == code for item in data['codes']])
                pts = data['vertices'][data['faces'][mask]].reshape(-1, 3)
                if not len(pts):
                    continue
                lo, hi = pts.min(axis=0), pts.max(axis=0)
                obj_mask = np.ones(len(data['codes']), dtype=bool)
                areas = data['areas']
                share = float(areas[mask].sum() / max(areas.sum(), 1e-9))
                title = data['name']
                shown = _display(title)
                if title.lower().startswith('cuerpo') and title[-1:].isdigit():
                    title = title[:-1] + ' ' + title[-1:]
                piece = 'separate piece' if data.get('plate') and len(regions) == 1 else 'part of'
                plate = f"plate {data['plate']}" if data.get('plate') else 'same plate'
                normal = _normal_description(data['normals'][mask])
                facts.append({'object_id': oid, 'name': shown, 'source_name': data['name'],
                              'share': share, 'bounds_mm': [round(float(x), 1) for x in hi - lo],
                              'plate': data.get('plate'), 'orientation': normal, 'piece': piece})
                selected.append((data, mask))
            digest = hashlib.sha256((manifest.get('source_sha256', '') + ':' + code).encode()).hexdigest()[:16]
            preview = output_dir / f'color-{digest}.png'
            _render(all_points, centers, region_data, selected, preview, size, _hex_rgba(color))
            summary_parts = []
            for row in facts:
                share_text = 'all of' if row['share'] > .97 else f"{row['share']:.0%} of"
                plate_text = f"plate {row['plate']}" if row['plate'] else 'plate unknown'
                piece_text = 'separate piece' if row['piece'] == 'separate piece' else 'part'
                dims = ' x '.join(f'{dimension:g}' for dimension in row['bounds_mm'])
                summary_parts.append(f"{label} on {share_text} {row['name']} ({row['orientation']}, {dims} mm, {piece_text}, {plate_text})")
            summary = '; '.join(summary_parts)
            output.append({'key': f'filament:{ext}', 'color': color, 'label': label, 'facts': facts,
                           'question': f'{label}: {summary}. Which loaded color/material?',
                           'preview': str(preview)})
        return output


def _transform(raw):
    matrix = np.eye(4)
    if raw:
        values = [float(value) for value in raw.split()]
        if len(values) == 12:
            matrix[:3, :3] = np.array(values[:9]).reshape(3, 3)
            matrix[:3, 3] = values[9:]
    return matrix


def _display(name):
    try:
        from .part_translator import display_name
        return display_name({'name': name})
    except Exception:
        return name


def _color_name(value):
    names = {'#FF80C0': 'Pink', '#FF0000': 'Red', '#FFFFFF': 'White'}
    return names.get(str(value).upper(), str(value).upper())


def _normal_description(normals):
    if not len(normals):
        return 'surfaces'
    mean = np.mean(normals, axis=0)
    axis = int(np.argmax(np.abs(mean)))
    if abs(mean[axis]) < .42:
        return 'mixed-facing surfaces'
    return ('front-facing' if mean[axis] < 0 else 'back-facing') if axis == 1 else ('top-facing' if mean[axis] > 0 else 'underside-facing') if axis == 2 else ('left-facing' if mean[axis] < 0 else 'right-facing')


def _render(points, centers, data, selected, path, size, highlight):
    """PIL painter rasterizer, orthographic front-three-quarter view."""
    image = Image.new('RGB', (size, size), (248, 249, 251))
    draw = ImageDraw.Draw(image, 'RGBA')
    angles = np.deg2rad([24, 0, 28])
    rx = np.array([[1, 0, 0], [0, math.cos(angles[0]), -math.sin(angles[0])], [0, math.sin(angles[0]), math.cos(angles[0])]])
    rz = np.array([[math.cos(angles[2]), -math.sin(angles[2]), 0], [math.sin(angles[2]), math.cos(angles[2]), 0], [0, 0, 1]])
    rot = rz @ rx
    vertices = np.concatenate([entry['vertices'] for entry in data.values()])
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    extents = np.maximum(hi - lo, 1e-9)
    front = int(np.argmax(extents))
    side = (front + 1) % 3
    up = (front + 2) % 3
    def orient(array):
        out = np.array(array, copy=True)
        out[..., front] = -out[..., front]
        return out
    bounds = orient(vertices.reshape(-1, 3))
    projection_axes = [front, up, side]
    projected_bounds = bounds[:, projection_axes]
    lo2, hi2 = projected_bounds[:, :2].min(axis=0), projected_bounds[:, :2].max(axis=0)
    span = max(float((hi2 - lo2).max()), 1e-6)
    canvas = int(size)
    margin = canvas * .08
    scale = (canvas - margin * 2) / span
    xoff = (canvas - (hi2[0] - lo2[0]) * scale) / 2 - lo2[0] * scale
    yoff = (canvas - (hi2[1] - lo2[1]) * scale) / 2 + hi2[1] * scale
    polygons = []
    for entry in data.values():
        verts = orient(entry['vertices'])
        faces = entry['faces']
        selected_mask = np.zeros(len(faces), dtype=bool)
        for selected_entry, mask in selected:
            if entry is selected_entry:
                selected_mask = mask
                break
        # Project in bulk; Python draws only polygons PIL can potentially intersect.
        tri = verts[faces]
        xy = tri[:, :, projection_axes[:2]]
        screen_x = xy[:, :, 0] * scale + xoff
        screen_y = -xy[:, :, 1] * scale + yoff
        depth = tri[:, :, projection_axes[2]].mean(axis=1)
        visible = ((screen_x.max(axis=1) >= 0) & (screen_x.min(axis=1) < canvas) &
                   (screen_y.max(axis=1) >= 0) & (screen_y.min(axis=1) < canvas))
        for i in np.flatnonzero(visible):
            polygon = [(int(screen_x[i, j]), int(screen_y[i, j])) for j in range(3)]
            polygons.append((float(depth[i]), polygon, bool(selected_mask[i])))
    for _, polygon, is_high in sorted(polygons, key=lambda item: item[0], reverse=True):
        draw.polygon(polygon, fill=highlight if is_high else (190, 198, 207, 255), outline=(115, 125, 138, 100))
    image.save(path, format='PNG')
