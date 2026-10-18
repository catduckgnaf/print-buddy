"""Offline full-size packing plan for splitting a 3MF into printable plates."""
import zipfile


def split_plan_100(source, bed=220):
    """Return the fewest greedy full-size plates, or None if any object cannot fit.

    Source plate assignments are respected: objects from distinct authored plates
    are never combined. Geometry checks and packing use the printer's edge and
    spacing margins and do not slice or contact the printer.
    """
    import color_geometry
    import model_job
    import plate_merge
    from source_colors import inventory

    manifest = inventory(source)
    if not manifest.get('parts'):
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
            height_limit = float(bed)
            if any(box[2][1] - box[2][0] > height_limit for box in boxes.values()):
                return None
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
