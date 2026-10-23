#!/usr/bin/env python3
"""Rebuild templates/orca/bambulab_a1 from OrcaSlicer's Bambu Lab A1 vendor profiles. Maintainer use only.

    python3 scripts/bambu-a1-templates.py [--tag v2.4.2] [--check]

Downloads resources/profiles/BBL at the pinned OrcaSlicer tag (network), resolves each profile's `inherits`
chain and `include` G-code templates into one flat JSON, applies the Print Buddy overrides below, and writes
machine.json, process.json and filament.json. --check compares instead of writing and exits 1 on a difference.
Tests never run this; they pin the result (tests/printers/test_bambulab_a1.py).
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "print_buddy" / "templates" / "orca" / "bambulab_a1"
TAGS = {"v2.4.2": "8500fcdccaa10b5099ac20d252af3a7c560046f1"}
PROFILES = {"machine": "Bambu Lab A1 0.4 nozzle", "process": "0.20mm Standard @BBL A1",
            "filament": "Generic PLA @BBL A1"}


def overrides(name, data):
    """Print Buddy's only changes to the vendor values; docs/BAMBU-A1.md explains each."""
    if name == "machine":
        return {"printer_settings_id": data["name"], "z_hop_types": ["Normal Lift"]}
    if name == "process":
        return {"print_settings_id": data["name"], "enable_arc_fitting": "0", "enable_prime_tower": "0",
                "brim_type": "outer_only"}
    return {"filament_settings_id": [data["name"]], "filament_colour": ["#FFFFFF"],
            "filament_z_hop_types": ["Normal Lift"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v2.4.2", choices=sorted(TAGS))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    base = f"https://raw.githubusercontent.com/SoftFever/OrcaSlicer/{TAGS[a.tag]}/resources/profiles/"

    def get(path):
        with urllib.request.urlopen(base + urllib.parse.quote(path), timeout=30) as response:
            return json.loads(response.read())

    index = get("BBL.json")
    paths = {e["name"]: e["sub_path"] for key in ("machine_list", "process_list", "filament_list")
             for e in index[key]}

    def resolve(name):
        data = get("BBL/" + paths[name])
        out = resolve(data["inherits"]) if data.get("inherits") else {}
        for include in data.get("include", []):
            out.update({k: v for k, v in get("BBL/" + paths[include]).items()
                        if k not in ("type", "name", "instantiation", "from")})
        out.update(data)
        out.pop("inherits", None)
        out.pop("include", None)
        return out

    changed = []
    for name, profile in PROFILES.items():
        data = resolve(profile)
        data.update(overrides(name, data))
        head = [k for k in ("type", "name", "from", "instantiation") if k in data]
        text = json.dumps({**{k: data[k] for k in head}, **{k: data[k] for k in sorted(data) if k not in head}},
                          indent=2, ensure_ascii=False) + "\n"
        target = OUT / f"{name}.json"
        if a.check:
            if not target.is_file() or target.read_text() != text:
                changed.append(str(target))
        else:
            target.write_text(text)
    if changed:
        print("differs from OrcaSlicer " + a.tag + ": " + ", ".join(changed))
        return 1
    print(("matches" if a.check else "wrote") + f" OrcaSlicer {a.tag} ({TAGS[a.tag]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
