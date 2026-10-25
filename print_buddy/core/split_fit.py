"""Offline full-size packing plan for splitting a 3MF into printable plates.

Margin semantics (see #76): two different clearances are used here, and each
is applied exactly once.

* ``edge`` (``layout.merge_edge_margin_mm``) is bed-edge clearance. It shrinks
  the usable area once per axis: ``usable = bed - 2 * edge``. A part placed on
  a plate of its own is checked against that usable area only.
* ``spacing`` (``layout.merge_spacing_mm``) is an object-to-object packing
  gap. It is added only between objects that share a plate; it never changes
  an individual part's footprint or the machine's printable area, so reducing
  it cannot make an individually oversized part fit.

Generated features (brim, skirt, supports, prime tower) are not part of this
geometry check: their extents depend on the slice and are accounted for by the
slicer capacity checks and the G-code out-of-bounds guard downstream. A plan
returned here is therefore an offer to slice at 100%, never a print-ready
assurance, and separate plates are never offered as a remedy for a part that
does not fit a plate on its own.
"""
import math
import zipfile

from .. import settings


def _bed_xy_height(bed, height):
    """Normalize bed/height arguments to (bed_x, bed_y, height_limit).

    ``bed`` may be a scalar (square bed, the legacy calling convention), an
    (x, y) pair, or an (x, y, z) triple. The Z limit is the printer's
    ``max_print_height_mm`` — never the XY bed size — unless the caller
    passes an explicit ``height`` or a 3-element bed.
    """
    printer = settings.current()['printer']
    if bed is None:
        bed_xy = [float(v) for v in printer['bed_mm'][:2]]
        bed_z = float(printer['bed_mm'][2]) if len(printer['bed_mm']) > 2 else None
    elif isinstance(bed, (list, tuple)):
        bed_xy = [float(v) for v in bed[:2]]
        bed_z = float(bed[2]) if len(bed) > 2 else None
    else:
        bed_xy = [float(bed), float(bed)]
        bed_z = None
    if height is not None:
        limit = float(height)
    elif bed_z is not None:
        limit = bed_z
    else:
        limit = float(printer.get('max_print_height_mm') or bed_xy[0])
    return bed_xy[0], bed_xy[1], limit


def yaw_envelope(width, depth, degrees):
    """XY envelope (w, d) of a width x depth rectangle yawed by ``degrees``.

    Dimension-preserving: yaw rotates the part in the bed plane, so its size
    and height are unchanged; only the axis-aligned envelope grows/shrinks.
    """
    rad = math.radians(float(degrees))
    c, s = math.cos(rad), math.sin(rad)
    return (width * c + depth * s, width * s + depth * c)


def best_yaw(width, depth, usable_x, usable_y):
    """Best in-plane yaw for one rectangular footprint against a usable area.

    Sweeps yaw 0-90 degrees in 1-degree steps (the same dense-sweep approach
    as the offline analysis on #76; a sweep is numerical evidence, not a
    continuous-angle proof). Returns (degrees, (w, d)) minimizing the worst
    usable-area ratio, preferring the smallest rotation on ties.
    """
    best = None
    for degrees in range(0, 91):
        envelope = yaw_envelope(width, depth, degrees)
        ratio = max(envelope[0] / usable_x, envelope[1] / usable_y)
        key = (round(ratio, 9), degrees)
        if best is None or key < best[0]:
            best = (key, float(degrees), envelope)
    return best[1], best[2]


def per_part_fit(source, bed=None, height=None):
    """Evaluate every authored object of a 3MF at 100% scale, one row per object.

    Each row reports the authored extent, the usable XY area (bed minus the
    edge clearance, applied once), the Z limit, the best dimension-preserving
    yaw found by :func:`best_yaw`, and whether the part fits a plate on its
    own at full size in any checked yaw. Parts are evaluated as authored:
    grouping, part colors and relationships are read, never altered, and a
    continuous part is never silently split. ``fits_full_size`` is False for
    a part that no separate-plate assignment can cure.
    """
    from . import color_geometry
    from . import plate_merge
    from .source_colors import inventory

    bed_x, bed_y, height_limit = _bed_xy_height(bed, height)
    edge = float(plate_merge.EDGE_MARGIN_MM)
    usable = (bed_x - 2 * edge, bed_y - 2 * edge)
    manifest = inventory(source)
    names = {}
    keys = {}
    for part in manifest.get('parts') or []:
        oid = str(part['object_id'])
        names.setdefault(oid, part.get('name') or f'Object {oid}')
        keys.setdefault(oid, []).append(part['key'])
    rows = []
    if not keys:
        return rows
    with zipfile.ZipFile(source) as archive:
        for oid in sorted(keys, key=str):
            box = color_geometry._world_bounds(archive, {oid})[0]
            extent = [round(box[a][1] - box[a][0], 3) for a in range(3)]
            yaw, envelope = best_yaw(extent[0], extent[1], usable[0], usable[1])
            fits_authored = (extent[0] <= usable[0] + 1e-9 and extent[1] <= usable[1] + 1e-9
                             and extent[2] <= height_limit + 1e-9)
            fits_yaw = (envelope[0] <= usable[0] + 1e-9 and envelope[1] <= usable[1] + 1e-9
                        and extent[2] <= height_limit + 1e-9)
            reason = None
            if not fits_yaw:
                if extent[2] > height_limit + 1e-9:
                    reason = (f'height {extent[2]:g} mm exceeds the {height_limit:g} mm '
                              'print height')
                else:
                    reason = (f'footprint {extent[0]:g} x {extent[1]:g} mm exceeds the usable '
                              f'{usable[0]:g} x {usable[1]:g} mm bed at every checked yaw '
                              f'(best {envelope[0]:.1f} x {envelope[1]:.1f} mm at {yaw:g} degrees)')
            rows.append({'object_id': oid, 'name': names[oid], 'keys': keys[oid],
                         'extent_mm': extent, 'usable_mm': [round(usable[0], 3), round(usable[1], 3)],
                         'height_limit_mm': height_limit,
                         'best_yaw_deg': yaw,
                         'best_extent_mm': [round(envelope[0], 3), round(envelope[1], 3), extent[2]],
                         'fits_authored': bool(fits_authored),
                         'fits_full_size': bool(fits_yaw),
                         'blocking_reason': reason})
    return rows


def split_plan_100(source, bed=None, height=None):
    """Return the fewest greedy full-size plates, or None if any object cannot fit.

    Source plate assignments are respected: objects from distinct authored plates
    are never combined. Every object is first evaluated on its own with
    :func:`per_part_fit` (per-part XY footprint at dimension-preserving yaws,
    and the printer's real Z limit): a part that fits no plate alone has no
    split plan, because separate plates cannot cure an individually oversized
    part. Geometry checks and packing use the printer's edge and spacing
    margins (see the module docstring) and do not slice or contact the printer.
    """
    from . import color_geometry
    from . import model_job
    from . import plate_merge
    from .source_colors import inventory

    bed_x, bed_y, _ = _bed_xy_height(bed, height)
    bed = min(bed_x, bed_y)
    manifest = inventory(source)
    if not manifest.get('parts'):
        return None
    report = per_part_fit(source, bed=(bed_x, bed_y), height=height)
    if any(not row['fits_full_size'] for row in report):
        return None
    try:
        authored = model_job.plate_manifest(source)['plates']
    except (RuntimeError, zipfile.BadZipFile):
        authored = []
    object_to_plate = {str(object_id): plate['id'] for plate in authored
                       for object_id in plate['object_ids']}
    by_object = {}
    for part in manifest['parts']:
        by_object.setdefault(str(part['object_id']), []).append(part['key'])
    groups = {}
    for object_id, keys in by_object.items():
        groups.setdefault(object_to_plate.get(object_id, 1), {})[object_id] = keys

    result = []
    with zipfile.ZipFile(source) as archive:
        for plate_id in sorted(groups, key=str):
            objects = groups[plate_id]
            boxes = {oid: color_geometry._world_bounds(archive, {oid})[0] for oid in objects}
            extents = {oid: (box[0][1] - box[0][0], box[1][1] - box[1][0])
                       for oid, box in boxes.items()}
            if any(plate_merge.pack({oid: extent}, bed) is None for oid, extent in extents.items()):
                return None
            bins = []
            for oid in sorted(extents, key=lambda key: -(extents[key][0] * extents[key][1])):
                for bin_objects in bins:
                    candidate = {**bin_objects, oid: extents[oid]}
                    if plate_merge.pack(candidate, bed) is not None:
                        bin_objects[oid] = extents[oid]
                        break
                else:
                    bins.append({oid: extents[oid]})
            for bin_objects in bins:
                result.append([key for oid in bin_objects for key in objects[oid]])
    return {'plates': result} if len(result) > 1 else None
