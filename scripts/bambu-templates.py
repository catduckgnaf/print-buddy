#!/usr/bin/env python3
"""Rebuild a Bambu Lab printer's Orca templates from OrcaSlicer's vendor profiles. Maintainer use only.

    python3 scripts/bambu-templates.py [--printer a1] [--check]

Reads the release and Print Buddy overrides from the vendor profile (print_buddy/printers/bambulab/vendor.py)
and the Orca profile names and template folder from the printer profile (bambulab/<printer>.py). Downloads
resources/profiles/BBL at that release (network), resolves each profile's `inherits` chain and `include`
G-code templates into one flat JSON, applies the overrides, and writes machine.json, process.json and
filament.json. --check compares instead of writing and exits 1 on a difference. Tests never run this; they pin
the result (tests/printers/test_bambulab_a1.py).
"""
import argparse
import importlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--printer", default="a1", help="printer profile module under print_buddy/printers/bambulab")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    profile = importlib.import_module(f"print_buddy.printers.bambulab.{a.printer}").PROFILE
    vendor = profile.vendor
    tag, commit = vendor.orca_release
    base = f"https://raw.githubusercontent.com/SoftFever/OrcaSlicer/{commit}/resources/profiles/"
    out_dir = ROOT / "print_buddy" / "templates" / "orca" / profile.templates

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

    ids = {"machine": "printer_settings_id", "process": "print_settings_id", "filament": "filament_settings_id"}
    changed = []
    for kind, name in profile.orca_profiles.items():
        data = resolve(name)
        data.update(vendor.orca_overrides[kind])
        data[ids[kind]] = [data["name"]] if kind == "filament" else data["name"]
        head = [k for k in ("type", "name", "from", "instantiation") if k in data]
        text = json.dumps({**{k: data[k] for k in head}, **{k: data[k] for k in sorted(data) if k not in head}},
                          indent=2, ensure_ascii=False) + "\n"
        target = out_dir / f"{kind}.json"
        if a.check:
            if not target.is_file() or target.read_text() != text:
                changed.append(str(target))
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
    if changed:
        print(f"differs from OrcaSlicer {tag}: " + ", ".join(changed))
        return 1
    print(("matches" if a.check else "wrote") + f" {profile.printer_model} from OrcaSlicer {tag} ({commit})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
