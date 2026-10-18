"""MakerWorld profile compatibility and selection helpers."""

BED_MM = 220.0

# MakerWorld product names mapped to Bambu nominal build volumes (XYZ mm).
VOLUMES = {
    "A1 mini": (180.0, 180.0, 180.0),
    "A1": (256.0, 256.0, 256.0), "P1S": (256.0, 256.0, 256.0),
    "P1P": (256.0, 256.0, 256.0), "X1 Carbon": (256.0, 256.0, 256.0),
    "X1": (256.0, 256.0, 256.0), "X1E": (256.0, 256.0, 256.0),
    "P2S": (256.0, 256.0, 256.0), "H2D": (350.0, 320.0, 325.0),
}


def _compatible(row):
    values = [row.get("compatibility") or {}] + list(row.get("other_compatibility") or [])
    seen = set()
    for value in values:
        name = str(value.get("devProductName") or "").strip()
        nozzle = value.get("nozzleDiameter")
        key = (name, str(nozzle))
        if name and key not in seen:
            seen.add(key)
            yield {"printer": name, "nozzle_mm": nozzle, "volume_mm": VOLUMES.get(name)}


def annotate(rows):
    """Add a ranked, relevant Bambu profile recommendation to each MakerWorld source."""
    for row in rows:
        candidates = list(_compatible(row))
        for candidate in candidates:
            dims = candidate["volume_mm"]
            candidate["bed_fit"] = "fits" if dims and all(x <= BED_MM for x in dims) else "may need scaling"
            candidate["rank"] = (
                0 if candidate["printer"] == "A1 mini" else 1,
                0 if str(candidate["nozzle_mm"]) == "0.4" else 1,
                1 if len(row.get("plates") or []) > 1 else 0,
                candidate["printer"],
            )
        candidates.sort(key=lambda x: x["rank"])
        row["bambu_profiles"] = candidates
        row["recommended_profile"] = candidates[0] if candidates else None
        # Source API geometry is often omitted (including the known 902337 profile).
        # Never infer actual 220 mm fit from a Bambu model's larger nominal volume.
        row["bed_fit_220"] = "may need scaling"
    return rows


def selection_summary(row):
    profile = row.get("recommended_profile") or {}
    printer = profile.get("printer") or row.get("site_printer") or "unknown Bambu printer"
    fit = row.get("bed_fit_220", "may need scaling")
    # Keep the authored profile visible as provenance, but omit the repetitive printer/bed warning.
    return f"{row.get('title') or 'Untitled profile'} | {printer} | {len(row.get('plates') or [])} plate(s)"


def choose(rows, profile_id=None):
    """Choose exact URL instance, or a clear ranking winner; return None if ambiguous."""
    if profile_id is not None:
        matches = [row for row in rows if str(row.get("instance_id")) == str(profile_id)]
        if len(matches) != 1:
            raise ValueError(f"MakerWorld profileId {profile_id} matched {len(matches)} profiles")
        return matches[0]
    if not rows:
        return None
    ranked = sorted(rows, key=lambda r: (
        (r.get("recommended_profile") or {}).get("rank", (99, 99, 99, "")),
        str(r.get("instance_id", "")),
    ))
    if len(ranked) == 1:
        return ranked[0]
    first = (ranked[0].get("recommended_profile") or {}).get("rank")
    second = (ranked[1].get("recommended_profile") or {}).get("rank")
    # A recommendation is clear only when the supported printer/nozzle ranking differs.
    return ranked[0] if first is not None and second is not None and first[:2] < second[:2] else None
