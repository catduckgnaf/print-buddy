"""Write the corpus models. Run `python3 tests/corpus/make_models.py` to regenerate every model.3mf.

The shapes are generated here, not copied from anyone, so each one is CC0 and safe to commit.
Output is deterministic (fixed zip timestamps, sorted entries): rerunning leaves git clean.
Only the standard library is used.
"""
import json
import math
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
STAMP = (2026, 1, 1, 0, 0, 0)


def box(w, d, h):
    """Closed box with its corner at the origin."""
    v = [(x, y, z) for z in (0, h) for y in (0, d) for x in (0, w)]
    f = [(0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6), (0, 1, 5), (0, 5, 4),
         (2, 6, 7), (2, 7, 3), (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5)]
    return v, f


def cylinder(radius, height, sides=48):
    """Closed cylinder standing on z=0, centered on x=y=radius."""
    v, f = [], []
    for z in (0, height):
        v += [(radius + radius * math.cos(2 * math.pi * i / sides),
               radius + radius * math.sin(2 * math.pi * i / sides), z) for i in range(sides)]
    bottom, top = len(v), len(v) + 1
    v += [(radius, radius, 0), (radius, radius, height)]
    for i in range(sides):
        j = (i + 1) % sides
        f += [(bottom, j, i), (top, sides + i, sides + j), (i, j, sides + j), (i, sides + j, sides + i)]
    return v, f


def extrude_y(profile, triangles, depth):
    """Prism along +Y from an XZ profile (counter clockwise seen from -Y) and its triangle list."""
    n = len(profile)
    v = [(x, 0, z) for x, z in profile] + [(x, depth, z) for x, z in profile]
    f = [(a, b, c) for a, b, c in triangles] + [(n + a, n + c, n + b) for a, b, c in triangles]
    for i in range(n):
        j = (i + 1) % n
        f += [(i, n + j, j), (i, n + i, n + j)]
    return v, f


def t_shape(bar_w, stem_w, height, bar_t, depth):
    """A T: a thin bar on top of a narrow stem. The bar overhangs the stem on both sides."""
    s0, s1 = (bar_w - stem_w) / 2, (bar_w + stem_w) / 2
    profile = [(s0, 0), (s1, 0), (s1, height - bar_t), (bar_w, height - bar_t),
               (bar_w, height), (0, height), (0, height - bar_t), (s0, height - bar_t)]
    triangles = [(0, 1, 2), (0, 2, 7), (5, 6, 7), (5, 7, 2), (5, 2, 3), (5, 3, 4)]
    return extrude_y(profile, triangles, depth)


def _xml(objects, items):
    """3dmodel.model. objects: [(id, kind, payload)]; items: [(object_id, (x, y))]."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<model unit="millimeter" xml:lang="en-US" xmlns="{NS}">',
           '<metadata name="Title">Corpus model (CC0)</metadata>', '<resources>']
    for oid, kind, payload in objects:
        if kind == "mesh":
            vertices, faces = payload
            out.append(f'<object id="{oid}" type="model"><mesh><vertices>')
            out += [f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in vertices]
            out.append('</vertices><triangles>')
            out += [f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces]
            out.append('</triangles></mesh></object>')
        else:
            out.append(f'<object id="{oid}" type="model"><components>'
                       f'<component objectid="{payload}"/></components></object>')
    out.append('</resources><build>')
    for oid, (x, y) in items:
        out.append(f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 {x} {y} 0"/>')
    out.append('</build></model>')
    return "\n".join(out)


def _settings(parts, plates):
    """Bambu style model_settings.config: parts is [(assembly_id, mesh_id, name, extruder)]."""
    out = ["<config>"]
    for assembly, mesh, name, extruder in parts:
        out.append(f'<object id="{assembly}"><metadata key="name" value="{name}"/>'
                   f'<metadata key="extruder" value="{extruder}"/>'
                   f'<part id="{mesh}" subtype="normal_part"><metadata key="name" value="{name}"/>'
                   f'<metadata key="extruder" value="{extruder}"/></part></object>')
    for number, (name, assemblies) in enumerate(plates, 1):
        out.append(f'<plate><metadata key="plater_id" value="{number}"/>'
                   f'<metadata key="plater_name" value="{name}"/>')
        out += [f'<model_instance><metadata key="object_id" value="{a}"/></model_instance>' for a in assemblies]
        out.append("</plate>")
    out.append("</config>")
    return "\n".join(out)


def write_3mf(path, shapes, plates, palette, support=False):
    """shapes: [(name, extruder, (vertices, faces), (x, y))]; plates: [(plate name, [shape index])]."""
    objects, items, parts = [], [], []
    for index, (name, extruder, mesh, at) in enumerate(shapes):
        mesh_id, assembly = 2 * index + 2, 2 * index + 1
        objects += [(mesh_id, "mesh", mesh), (assembly, "components", mesh_id)]
        items.append((assembly, at))
        parts.append((assembly, mesh_id, name, extruder))
    project = {"filament_colour": [c for c, _ in palette], "filament_type": [m for _, m in palette],
               "enable_support": "1" if support else "0"}
    if support:
        project["support_type"] = "tree(auto)"
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="config" ContentType="text/xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>',
        "3D/3dmodel.model": _xml(objects, items),
        "Metadata/model_settings.config": _settings(
            parts, [(name, [parts[i][0] for i in members]) for name, members in plates]),
        "Metadata/project_settings.config": json.dumps(project, indent=2),
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name])


WHITE, BLACK, RED = ("#FFFFFF", "PLA"), ("#000000", "PLA"), ("#C0392B", "PLA")


def build():
    cases = HERE / "cases"
    # 1) three parts on one plate, one palette color
    write_3mf(cases / "parts-one-plate/model.3mf",
              [("Base", 1, box(70, 50, 6), (60, 60)),
               ("Post", 1, cylinder(10, 30), (70, 130)),
               ("Tab", 1, box(30, 12, 4), (130, 140))],
              [("Plate 1", [0, 1, 2])], [WHITE])
    # 2) two plates, three palette colors
    write_3mf(cases / "plates-multicolor/model.3mf",
              [("Body", 1, box(60, 40, 12), (50, 60)),
               ("Lid", 2, box(60, 40, 4), (50, 60)),
               ("Knob", 3, cylinder(9, 14), (60, 130))],
              [("Body", [0]), ("Lid and knob", [1, 2])], [WHITE, BLACK, RED])
    # 3) a T whose bar overhangs the stem; the project asks for supports
    write_3mf(cases / "needs-supports/model.3mf",
              [("T bracket", 1, t_shape(60, 12, 40, 6, 30), (80, 90))],
              [("Plate 1", [0])], [WHITE], support=True)
    # 4) a plate wider than the 220 mm bed in both directions and taller than the gantry when stood on
    #    its edge: the only way to fit it is to shrink it
    write_3mf(cases / "must-shrink/model.3mf",
              [("Big plate", 1, box(260, 260, 8), (0, 0))],
              [("Plate 1", [0])], [WHITE])
    # 4b) two parts that fit the bed one at a time but not together: the 100% split plan is offered
    write_3mf(cases / "split-plan/model.3mf",
              [("Left half", 1, box(150, 150, 10), (0, 0)),
               ("Right half", 1, box(150, 150, 10), (160, 0))],
              [("Plate 1", [0, 1])], [WHITE])
    # 5) the baseline: one part, one color
    write_3mf(cases / "single-part/model.3mf",
              [("Cube", 1, box(30, 30, 20), (90, 90))],
              [("Plate 1", [0])], [WHITE])


if __name__ == "__main__":
    build()
    print("wrote", len(list((HERE / "cases").glob("*/model.3mf"))), "models", file=sys.stderr)
