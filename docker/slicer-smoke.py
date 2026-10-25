"""Offline in-image smoke: require the selected bundled Orca and slice a cube.

Run via the image entrypoint with a writable /data tmpfs and --network none.
No printer or Discord access. Fail if a selected binary or source identity is absent.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, "/app")
from print_buddy import settings
from print_buddy.core import slice_guard


def main():
    channel = os.environ["PRINT_BUDDY_ORCA_CHANNEL"]
    assert channel in {"stable", "alpha"}
    binary = Path(f"/opt/orca-{channel}/bin/orca-slicer")
    assert binary.is_file() and os.access(binary, os.X_OK), binary
    revision = Path(f"/orca-{channel}-source-revision").read_text().strip()
    assert len(revision) == 40
    closure = subprocess.run(["ldd", str(binary)], capture_output=True, text=True, check=True)
    assert "not found" not in closure.stdout, closure.stdout
    subprocess.run([str(binary), "--help"], check=True, timeout=120)
    config = settings.current()
    with tempfile.TemporaryDirectory(dir="/data/cache") as tmp:
        work = Path(tmp)
        # Deterministic, locally generated closed cube; no model downloads.
        vertices = [(x, y, z) for x in (0, 20) for y in (0, 20) for z in (0, 20)]
        faces = [(0, 2, 3), (0, 3, 1), (4, 5, 7), (4, 7, 6),
                 (0, 1, 5), (0, 5, 4), (2, 6, 7), (2, 7, 3),
                 (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5)]
        lines = ["solid cube"]
        for face in faces:
            lines += ["facet normal 0 0 0", "outer loop"]
            lines += ["vertex " + " ".join(map(str, vertices[i])) for i in face]
            lines += ["endloop", "endfacet"]
        model = work / "cube.stl"
        model.write_text("\n".join(lines + ["endsolid cube"]) + "\n")
        templates = config["orca"]["templates"]
        command = [str(binary), "--load-settings",
                   f"{templates / 'machine.json'};{templates / 'process.json'}",
                   "--load-filaments", str(templates / "filament.json"),
                   "--arrange", "1", "--orient", "0", "--ensure-on-bed",
                   "--allow-newer-file", "--slice", "0", "--outputdir", str(work), str(model)]
        subprocess.run(command, check=True, timeout=900)
        gcode = work / "plate_1.gcode"
        assert gcode.is_file() and gcode.stat().st_size > 0
        result_json = work / "result.json"
        result = slice_guard.post_slice(
            gcode, tool_slots={0: 1},
            result_json=result_json if result_json.exists() else None,
        ).as_dict()
        assert result["status"] != "blocked", result
        print(json.dumps({"channel": channel, "revision": revision,
                          "gcode_bytes": gcode.stat().st_size, "guard": result}))


if __name__ == "__main__":
    main()
