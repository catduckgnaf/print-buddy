"""Plan one-bed merging of every object in a multi-plate 3MF. Disk only.

The planner never slices and never contacts the printer. It answers one
question: can every source object share one AD5X bed with safe spacing, and
if not, why. A split is always reported with a reason.
"""
import re
import zipfile
import xml.etree.ElementTree as ET

MAX_MERGED_S = 12 * 3600


class SplitNeeded(RuntimeError):
    """A merged slice turned out unsuitable; carry the reason to the caller."""

EDGE_MARGIN_MM = 8.0
SPACING_MM = 10.0
TOWER_MM = 45.0
TOWER_CLEARANCE_MM = 8.0
TOWER_SLACK_MM = 5.0
IFS_SLOTS = 4

SEPARATE_RE = re.compile(
    r"(print(?:ed)?\s+(?:\w+\s+){0,3}(?:separately|individually|one\s+(?:plate\s+)?at\s+a\s+time|one\s+by\s+one)"
    r"|(?:separate|individual)\s+(?:print|job|plate)s?"
    r"|do\s+not\s+(?:print|merge|combine)\s+(?:\w+\s+){0,3}together"
    r"|don'?t\s+(?:print|merge|combine)\s+(?:\w+\s+){0,3}together"
    r"|one\s+plate\s+at\s+a\s+time)", re.I)


def author_text(source, job=None):
    """Free text an author or the job may use to ask for separate printing."""
    chunks = []
    with zipfile.ZipFile(source) as archive:
        if '3D/3dmodel.model' in archive.namelist():
            root = ET.fromstring(archive.read('3D/3dmodel.model'))
            for node in root.iter():
                if node.tag.split('}')[-1] == 'metadata' and node.get('name') in (
                        'Description', 'Title', 'Designer', 'CopyRight', 'License', 'Notes', 'Summary'):
                    chunks.append(node.text or '')
    for key in ('description', 'notes', 'summary'):
        if isinstance((job or {}).get(key), str):
            chunks.append(job[key])
    return '\n'.join(chunks)


def separate_hint(source, job=None):
    match = SEPARATE_RE.search(author_text(source, job))
    return match.group(0) if match else None


def pack(extents, bed, spacing=SPACING_MM, edge=EDGE_MARGIN_MM, reserve_y=0.0):
    """Shelf packing of axis-aligned (w, d) footprints. Orientation is kept.

    Returns {key: (x, y)} lower-left corners, or None when it does not fit.
    Both row directions are tried; the first that fits wins. reserve_y keeps a
    strip along the high Y edge free (prime tower).
    """
    width = bed - 2 * edge
    depth = bed - 2 * edge - reserve_y
    if not extents:
        return {}
    for swap in (False, True):
        items = sorted(extents.items(), key=lambda kv: -(kv[1][0] if swap else kv[1][1]))
        placed, x, y, row = {}, 0.0, 0.0, 0.0
        ok = True
        for key, (w, d) in items:
            a, b = (d, w) if swap else (w, d)       # a along the row, b across rows
            lim_a, lim_b = (depth, width) if swap else (width, depth)
            if a > lim_a + 1e-9 or b > lim_b + 1e-9:
                ok = False
                break
            if x + a > lim_a + 1e-9:
                x, y, row = 0.0, y + row + spacing, 0.0
            if y + b > lim_b + 1e-9:
                ok = False
                break
            px, py = (y, x) if swap else (x, y)
            placed[key] = (edge + px, edge + py)
            x += a + spacing
            row = max(row, b)
        if ok:
            return placed
    return None


def full_size_split_possible(source, manifest, bed=220, edge=EDGE_MARGIN_MM):
    """Whether source-assigned plate groups fit individually at authored size.

    This is an offline geometry check for the explicit full-size split option.
    It does not imply Orca acceptance; every derived plate is still sliced and
    validated by the normal offline G-code gates.
    """
    from . import color_geometry
    try:
        with zipfile.ZipFile(source) as archive:
            settings = ET.fromstring(archive.read('Metadata/model_settings.config'))
            groups = []
            for plate in settings.iter('plate'):
                ids = [m.get('value') for instance in plate.findall('model_instance')
                       for m in instance.findall('metadata') if m.get('key') == 'object_id']
                if not ids:
                    return False
                groups.append(ids)
            if len(groups) < 2:
                return False
            for ids in groups:
                boxes = color_geometry._world_bounds(archive, set(ids))
                bounds = [(min(box[a][0] for box in boxes), max(box[a][1] for box in boxes))
                          for a in range(3)]
                usable = float(bed) - 2 * float(edge)
                if (max(bounds[a][1] - bounds[a][0] for a in (0, 1)) > usable
                        or bounds[2][1] - bounds[2][0] > float(bed)):
                    return False
    except (RuntimeError, KeyError, zipfile.BadZipFile, ET.ParseError, ValueError):
        return False
    return True


def plan(source, manifest, plates, slots, state, bed=None, spacing=SPACING_MM, job=None):
    """Return a merge plan or a split decision with a human reason.

    manifest: source_colors.inventory(source); plates: model_job.plate_manifest(source)['plates'];
    slots: {part_key: slot}. Result keys: mode ('merge'|'split'), reason, shifts, ...
    """
    from . import color_geometry
    bed = int(bed or state['bed_mm'][0])
    out = {'mode': 'split', 'reason': None, 'plates_in': len(plates),
           'objects_in': sorted({p['object_id'] for p in manifest['parts']}, key=str),
           'parts_in': sorted(p['key'] for p in manifest['parts']), 'bed_mm': bed, 'spacing_mm': spacing}
    hint = separate_hint(source, job)
    if hint:
        out['reason'] = f'author notes ask for separate printing ("{hint}")'
        return out
    used = sorted(set(slots.values()))
    if len(used) > IFS_SLOTS:
        out['reason'] = f'needs {len(used)} filament slots; one IFS job has {IFS_SLOTS}'
        return out
    materials = {(state.get('ifs_slots') or {}).get(str(s), {}).get('material') for s in used}
    if len(used) > 1 and len(materials) > 1:
        out['reason'] = 'mixed materials across slots cannot share one IFS job'
        return out
    object_ids = sorted({p['object_id'] for p in manifest['parts']}, key=int)
    try:
        with zipfile.ZipFile(source) as archive:
            boxes = {oid: color_geometry._world_bounds(archive, {oid})[0] for oid in object_ids}
    except RuntimeError as exc:
        # The merge exporter cannot place this geometry; say why instead of failing the slice.
        out['reason'] = f'the merge exporter cannot place this geometry ({exc})'
        return out
    extents, tall = {}, []
    for oid, box in boxes.items():
        extents[oid] = (box[0][1] - box[0][0], box[1][1] - box[1][0])
        if box[2][1] - box[2][0] > float(state['max_print_height_mm']):
            tall.append(oid)
    if tall:
        out['reason'] = f'object(s) {",".join(tall)} exceed the printer height'
        return out
    reserve = (TOWER_MM + TOWER_CLEARANCE_MM + TOWER_SLACK_MM + EDGE_MARGIN_MM) if len(used) > 1 else 0.0
    placed = pack(extents, bed, spacing, reserve_y=reserve)
    tower_xy = None
    if placed is None and reserve:
        # The reserved strip is a fast path, not the rule. Pack without it and
        # accept only when the exporter's own tower search clears every part.
        loose = pack(extents, bed, spacing)
        if loose is not None:
            loose_bounds = [((px, px + extents[oid][0]), (py, py + extents[oid][1]), (0.0, 0.0))
                            for oid, (px, py) in loose.items()]
            try:
                tower_xy = color_geometry.prime_tower_xy(loose_bounds, bed=bed)
            except RuntimeError:
                tower_xy = None
            else:
                placed = loose
    if placed is None:
        out['reason'] = (f'{len(extents)} parts do not fit one {bed}x{bed} mm bed with {spacing:g} mm spacing'
                         + (' and a prime tower' if reserve else ''))
        return out
    shifts, bounds = {}, {}
    for oid, (px, py) in placed.items():
        box = boxes[oid]
        shifts[oid] = [px - box[0][0], py - box[1][0], -box[2][0]]
        bounds[oid] = [(px, px + extents[oid][0]), (py, py + extents[oid][1]),
                       (0.0, box[2][1] - box[2][0])]
    out.update({'mode': 'merge', 'shifts': shifts, 'placed_bounds_mm': bounds, 'slots': used,
                'objects_out': sorted(shifts, key=str)})
    if tower_xy is not None:
        out['prime_tower_xy_mm'] = list(tower_xy)
    return out
