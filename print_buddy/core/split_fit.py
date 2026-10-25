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

One generated feature IS part of this geometry check when the caller
supplies the job's brim policy (#221 stage 3): the brim budget computed by
``orca_adapter.required_feature_edge`` (the explicit brim width plus the
resolved travel sweep) is added to the bed-edge clearance, so the usable
area shrinks by that budget exactly once and a part that fits only without
its brim no longer counts as fitting — its blocking reason names the brim.
With no brim policy supplied, the budget is zero and verdicts are exactly
as before. The remaining generated features (skirt, supports, prime tower
and purge structures) are slice-dependent: their extents stay with the
slicer capacity checks and the G-code out-of-bounds guard downstream, and
this check makes no claim about them. A plan returned here is therefore an
offer to slice at 100%, never a print-ready assurance, and separate plates
are never offered as a remedy for a part that does not fit a plate on its
own.

A part that fits a plate only when turned in the bed plane gets a plate of
its own, and the plan records the turn as ``yaw_by_object`` (object id to
degrees). The exporter can apply one rigid turn to a whole derived plate, so
a turned part is never packed with other parts; slicing applies exactly the
recorded turn (see ``model_job._slice_full_size_split``) and refuses a plan
that records a turn for a shared plate instead of slicing it as authored.

Fit is evaluated from the part's actual mesh vertices, not its bounding
rectangle (#221, following #76): at each checked yaw the envelope is the
axis-aligned envelope of the rotated mesh vertices (the true in-plane mesh
extrema), so a non-rectangular part is judged by the size it really occupies
when turned. For a rectangular part this is identical to the rectangle
check. When the selected printer model declares a printable-area exclusion,
a part counts as fitting only if a placement of that envelope exists inside
the usable area that avoids the exclusion; the plan records that placement
as ``placement_by_object`` and the part gets a plate of its own, because the
split exporter applies one recorded placement to a whole derived plate (see
``yaw_by_object``). Slicing applies exactly the recorded placement to that
plate alone and refuses a placement recorded for a shared plate, an unknown
object or an out-of-range position instead of slicing the plate centered
into the exclusion.
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


def _declared_exclusions():
    """Bed exclusion rectangles (x0, y0, x1, y1) declared by the current printer model.

    Read from the model adapter's sourced facts (``bed_exclude_area``, a
    polygon in bed coordinates); the rectangle used is the polygon's bounding
    rectangle, which is conservative. Models that declare none — and any
    lookup problem — mean no exclusions.
    """
    try:
        from .. import printers
        key = settings.current()['printer'].get('model')
        model = printers.MODELS.get(key) if key else None
        facts = getattr(getattr(model, 'adapter', None), 'facts', None) or {}
        polygon = list(getattr(facts.get('bed_exclude_area'), 'value', None) or ())
        if not polygon:
            return []
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        return [(min(xs), min(ys), max(xs), max(ys))]
    except Exception:
        return []


def _placement(envelope, bed_x, bed_y, edge, exclusions):
    """A lower-left bed position for one envelope avoiding every exclusion, or None.

    The envelope (w, d) must sit inside the usable area (bed minus the edge
    clearance, applied once). Candidate positions come from the usable-area
    edges and from each exclusion's edges, which is exact for placing one
    rectangle against axis-aligned rectangles: if any valid position exists,
    one exists at a candidate.
    """
    w, d = float(envelope[0]), float(envelope[1])
    max_x, max_y = bed_x - edge - w, bed_y - edge - d
    if max_x < edge - 1e-9 or max_y < edge - 1e-9:
        return None
    cand_x, cand_y = {edge, max_x}, {edge, max_y}
    for x0, y0, x1, y1 in exclusions:
        cand_x.update(v for v in (x1, x0 - w) if edge - 1e-9 <= v <= max_x + 1e-9)
        cand_y.update(v for v in (y1, y0 - d) if edge - 1e-9 <= v <= max_y + 1e-9)

    def clamped(values, high):
        return sorted({min(max(v, edge), high) for v in values})

    for y in clamped(cand_y, max_y):
        for x in clamped(cand_x, max_x):
            if all(x + w <= x0 + 1e-9 or x >= x1 - 1e-9 or y + d <= y0 + 1e-9 or y >= y1 - 1e-9
                   for x0, y0, x1, y1 in exclusions):
                return (round(x, 3), round(y, 3))
    return None


def mesh_yaw_candidates(hull_xy, usable_x, usable_y):
    """Checked yaws for one mesh footprint, best first: (ratio, degrees, (w, d)).

    ``hull_xy`` is the convex hull of the part's mesh vertices in the bed
    plane (a rotated point set's envelope is set by its hull vertices). Each
    envelope is computed from the actual vertices — the mesh's true in-plane
    extrema — not from rotating its bounding rectangle. The sweep is yaw
    0–90 degrees in 1-degree steps, the same dense-sweep approach as the
    offline analysis on #76: numerical evidence, not a continuous-angle proof.
    Ordering minimizes the worst usable-area ratio, smallest yaw on ties.
    """
    candidates = []
    for degrees in range(0, 91):
        rad = math.radians(degrees)
        c, s = math.cos(rad), math.sin(rad)
        xs = [x * c - y * s for x, y in hull_xy]
        ys = [x * s + y * c for x, y in hull_xy]
        envelope = (max(xs) - min(xs), max(ys) - min(ys))
        ratio = max(envelope[0] / usable_x, envelope[1] / usable_y)
        candidates.append((round(ratio, 9), float(degrees), envelope))
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates


def _feature_edge_mm(brim_policy=None, state=None):
    """Brim/feature edge budget in mm for a supplied brim policy, else 0.

    The budget is ``orca_adapter.required_feature_edge`` (explicit brim
    width plus the resolved travel sweep) for the job's brim policy. No
    policy — neither passed directly nor carried on ``state`` — means no
    budget, so policy-off jobs keep the pre-stage-3 verdicts exactly.
    """
    if brim_policy is None and not (state and state.get('brim_policy')):
        return 0.0
    from .orca_adapter import required_feature_edge
    return float(required_feature_edge(state or {}, brim_policy))


def per_part_fit(source, bed=None, height=None, exclusions=None, brim_policy=None, state=None):
    """Evaluate every authored object of a 3MF at 100% scale, one row per object.

    Each row reports the authored extent, the usable XY area (bed minus the
    edge clearance, applied once), the Z limit, the best dimension-preserving
    yaw for the part's actual mesh footprint (see :func:`mesh_yaw_candidates`),
    and whether the part fits a plate on its own at full size in any checked
    yaw. When the printer model declares bed exclusions (``exclusions`` may
    override them, as (x0, y0, x1, y1) rectangles in bed coordinates), the row
    also reports an avoiding ``placement_mm``; a part whose footprint fits
    only where every placement overlaps an exclusion does not count as
    fitting, and its blocking reason names the exclusion. When the caller
    supplies the job's brim policy (``brim_policy``, with the printer
    ``state`` it was resolved against), the brim/feature budget from
    :func:`_feature_edge_mm` shrinks the usable area exactly once, the row
    reports it as ``feature_edge_mm``, placements keep the brimmed footprint
    clear of exclusions as well as the bed edge, and a part that fits only
    without its brim does not count as fitting — its blocking reason names
    the brim budget. Parts are evaluated as authored: grouping, part colors
    and relationships are read, never altered, and a continuous part is never
    silently split. ``fits_full_size`` is False for a part that no
    separate-plate assignment can cure.
    """
    from . import color_geometry
    from . import plate_merge
    from .orca_adapter import _hull
    from .source_colors import inventory

    bed_x, bed_y, height_limit = _bed_xy_height(bed, height)
    edge = float(plate_merge.EDGE_MARGIN_MM)
    feature = _feature_edge_mm(brim_policy, state)
    # The brim/feature budget is added to the edge clearance once: the usable
    # area is bed - 2 * (edge + feature) per axis, never shrunk twice.
    usable = (bed_x - 2 * (edge + feature), bed_y - 2 * (edge + feature))
    usable_no_brim = (bed_x - 2 * edge, bed_y - 2 * edge)
    if exclusions is None:
        exclusions = _declared_exclusions()
    exclusions = [tuple(float(v) for v in rect) for rect in exclusions]
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
            points = color_geometry._world_points(archive, {oid})
            extent = [round(max(p[a] for p in points) - min(p[a] for p in points), 3)
                      for a in range(3)]
            hull = _hull([(p[0], p[1]) for p in points])
            candidates = mesh_yaw_candidates(hull, usable[0], usable[1])
            _ratio, best_deg, best_envelope = candidates[0]
            fits_authored = (extent[0] <= usable[0] + 1e-9 and extent[1] <= usable[1] + 1e-9
                             and extent[2] <= height_limit + 1e-9)
            chosen, placement = None, None
            fits_without_brim = False
            if extent[2] <= height_limit + 1e-9:
                for _r, degrees, envelope in candidates:
                    if envelope[0] > usable[0] + 1e-9 or envelope[1] > usable[1] + 1e-9:
                        continue
                    if exclusions:
                        if feature:
                            # Place the brimmed footprint (envelope grown by
                            # the budget on every side) against the original
                            # edge clearance, so the brim itself also avoids
                            # the exclusion and the bed edge; the recorded
                            # placement is the part's own lower-left corner.
                            grown = (envelope[0] + 2 * feature, envelope[1] + 2 * feature)
                            spot = _placement(grown, bed_x, bed_y, edge, exclusions)
                            if spot is None:
                                continue
                            placement = (round(spot[0] + feature, 3), round(spot[1] + feature, 3))
                        else:
                            spot = _placement(envelope, bed_x, bed_y, edge, exclusions)
                            if spot is None:
                                continue
                            placement = spot
                    chosen = (degrees, envelope)
                    break
                if feature:
                    # Shadow verdict at the no-brim usable area, used only to
                    # name the brim as the blocker when it alone is decisive.
                    for _r, _degrees, envelope in candidates:
                        if (envelope[0] <= usable_no_brim[0] + 1e-9
                                and envelope[1] <= usable_no_brim[1] + 1e-9
                                and (not exclusions
                                     or _placement(envelope, bed_x, bed_y, edge, exclusions) is not None)):
                            fits_without_brim = True
                            break
            fits = chosen is not None
            yaw, envelope = chosen if chosen else (best_deg, best_envelope)
            reason = None
            if not fits:
                if extent[2] > height_limit + 1e-9:
                    reason = (f'height {extent[2]:g} mm exceeds the {height_limit:g} mm '
                              'print height')
                elif feature and fits_without_brim:
                    reason = (f'footprint {extent[0]:g} x {extent[1]:g} mm fits the usable '
                              f'{usable_no_brim[0]:g} x {usable_no_brim[1]:g} mm bed without a brim, '
                              f'but not with the {feature:g} mm brim/feature edge budget applied '
                              f'once (usable {usable[0]:g} x {usable[1]:g} mm with the brim)')
                elif exclusions and any(env[0] <= usable[0] + 1e-9 and env[1] <= usable[1] + 1e-9
                                        for _r, _d, env in candidates):
                    x0, y0, x1, y1 = exclusions[0]
                    reason = (f'footprint {extent[0]:g} x {extent[1]:g} mm fits the usable '
                              f'{usable[0]:g} x {usable[1]:g} mm bed only where it would overlap '
                              f'the declared bed exclusion ({x0:g}, {y0:g}) to ({x1:g}, {y1:g}) mm; '
                              'no placement at a checked yaw avoids it')
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
                         'feature_edge_mm': round(feature, 3),
                         'fits_full_size': bool(fits),
                         'placement_mm': list(placement) if placement else None,
                         'exclusions_mm': [[round(v, 3) for v in rect] for rect in exclusions],
                         'blocking_reason': reason})
    return rows


def split_plan_100(source, bed=None, height=None, exclusions=None, brim_policy=None, state=None):
    """Return the fewest greedy full-size plates, or None if any object cannot fit.

    Source plate assignments are respected: objects from distinct authored plates
    are never combined. Every object is first evaluated on its own with
    :func:`per_part_fit` (per-part mesh footprint at dimension-preserving yaws,
    and the printer's real Z limit): a part that fits no plate alone has no
    split plan, because separate plates cannot cure an individually oversized
    part. An object that fits only at a turned yaw is planned alone on its own
    plate and the turn is recorded in ``yaw_by_object``; objects that fit as
    authored keep their authored orientation and are packed together as
    before. When the bed has declared exclusions, every fitting object carries
    an avoiding placement from :func:`per_part_fit`: it is planned alone on
    its own plate and the placement is recorded in ``placement_by_object``,
    so slicing can land that plate exactly there (#221 stage 2). A part with
    no avoiding placement does not fit (its blocking reason names the
    exclusion), so no plan is offered for it. When the caller supplies the
    job's brim policy (``brim_policy`` / ``state``, #221 stage 3), the
    brim/feature budget is threaded into :func:`per_part_fit` — a part that
    fits only without its brim has no plan — and packing checks each plate
    with footprints grown by the budget on every side, so shared plates keep
    the brimmed parts clear of the bed edge and of each other; the budget is
    applied exactly once in each check, never stacked. Geometry checks and
    packing use the printer's edge and spacing margins (see the module
    docstring) and do not slice or contact the printer.
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
    report = per_part_fit(source, bed=(bed_x, bed_y), height=height, exclusions=exclusions,
                          brim_policy=brim_policy, state=state)
    feature = _feature_edge_mm(brim_policy, state)
    if any(not row['fits_full_size'] for row in report):
        return None
    yaw_by_object = {row['object_id']: row['best_yaw_deg'] for row in report
                     if not row['fits_authored'] and row['best_yaw_deg'] > 0}
    # On an exclusion bed every fitting row carries the avoiding placement
    # per_part_fit proved; a row without one would already have failed
    # fits_full_size above, so a missing placement here is impossible.
    placement_by_object = {row['object_id']: row['placement_mm'] for row in report
                           if row.get('placement_mm')}
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
            # Packing footprints carry the brim/feature budget grown on every
            # side (zero when no brim policy was supplied, so packing is then
            # exactly as before); pack() applies the bed-edge margin itself.
            extents = {oid: (box[0][1] - box[0][0] + 2 * feature, box[1][1] - box[1][0] + 2 * feature)
                       for oid, box in boxes.items()}
            if any(oid not in yaw_by_object and oid not in placement_by_object
                   and plate_merge.pack({oid: extent}, bed) is None
                   for oid, extent in extents.items()):
                return None
            bins = []  # (objects dict, closed to further packing)
            for oid in sorted(extents, key=lambda key: -(extents[key][0] * extents[key][1])):
                if oid in yaw_by_object or oid in placement_by_object:
                    # A turned or placed part is always alone: the exporter
                    # turns / places a whole derived plate rigidly, so it
                    # cannot share one.
                    bins.append(({oid: extents[oid]}, True))
                    continue
                for bin_objects, closed in bins:
                    if closed:
                        continue
                    candidate = {**bin_objects, oid: extents[oid]}
                    if plate_merge.pack(candidate, bed) is not None:
                        bin_objects[oid] = extents[oid]
                        break
                else:
                    bins.append(({oid: extents[oid]}, False))
            for bin_objects, _closed in bins:
                result.append([key for oid in bin_objects for key in objects[oid]])
    if len(result) <= 1:
        return None
    plan = {'plates': result}
    if yaw_by_object:
        plan['yaw_by_object'] = yaw_by_object
    if placement_by_object:
        plan['placement_by_object'] = placement_by_object
    return plan
