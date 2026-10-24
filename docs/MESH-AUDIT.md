# Read-only mesh topology audit

[Project overview](../README.md) · [Documentation home](README.md) · [Contributing](../CONTRIBUTING.md)

Print Buddy includes a conservative, read-only triangle-topology audit in `print_buddy.core.model_job`. It evaluates indexed triangles for STL and 3MF source geometry without repairing, modifying, or slicing the model.

## Command-line usage

Run the audit directly without a printer, slicer, or network connection:

```bash
python3 -m print_buddy.core.model_job audit path/to/model.stl
python3 -m print_buddy.core.model_job audit path/to/project.3mf
```

The command prints a formatted JSON topology report to standard output and leaves the input file unchanged.

## Output metrics

The topology audit produces a versioned v1 report. Existing flat topology keys and the legacy `sha256` field remain intact for compatibility. The artifact also records source identity, bounding dimensions, units, and the printer profile when available.

| Field | Description |
| --- | --- |
| `schema_version` | Integer report schema version (currently `1`). |
| `source_sha256` | SHA-256 hex digest of the audited source file. The legacy `sha256` alias remains available. |
| `dimensions_mm` | `[x, y, z]` printable-geometry bounding-box dimensions in millimeters, rounded to two decimal places like `audit_source` geometry metrics. |
| `units` | Explicit dimensions unit policy, always `"mm"` in schema v1. |
| `printer_model` | Configured printer profile ID used for prepared-job fit probing; standalone audit reports `null` when no profile is configured. |
| `sha256` | Backward-compatible SHA-256 digest of the source file. |
| `triangle_count` | Total number of faces analyzed from the model. |
| `connected_shells` | Number of topologically connected face components. |
| `boundary_edges` | Number of mesh edges referenced by only one face (open holes or edges). |
| `non_manifold_edges` | Number of mesh edges referenced by more than two faces (T-junctions or fan geometry). |
| `singular_vertices` | Count of vertices with non-disk or non-manifold incident edge topology. |
| `winding_inconsistencies` | Number of shared edges with identical face traversal direction (inconsistent surface normals). |
| `degenerate_triangles` | Count of triangles with repeated or collinear vertices producing zero surface area. |
| `watertight` | Boolean indicating whether `boundary_edges == 0` and `non_manifold_edges == 0`. |
| `manifold` | Boolean indicating strict manifoldness (no boundaries, non-manifold edges, singular vertices, degenerate triangles, or winding inconsistencies). |

## Integration with job preparation

When preparing a print job, `audit(path, printer_model=...)`:

1. The mesh audit report is stored under the `mesh_audit` key in the source audit dictionary and persisted in `JOB.json`.
2. If geometry extraction fails (for example, an unreadable file or corrupt archive), the error message is recorded under `mesh_audit_error` without terminating intake processing prematurely.

## Scope and boundaries

The topology audit is strictly read-only and conservative:

- It **does not repair** mesh defects, close open boundaries, or flip inverted normals. Automatic repair could alter mounting dimensions, bolt clearance, or wall thickness.
- It **does not detect** self-intersecting shells, unit scale errors, or slicer toolpath artifacts.
- It is not a guarantee of bed adhesion, slice success, or physical printability. Slicer-backed fit and clearance checks remain necessary prior to printing.
