"""Offline deterministic checks around Orca slicing; no printer or slicer calls."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Result:
    status: str = "ok"
    warnings: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    @property
    def ok(self): return self.status == "ok"
    def warn(self, text):
        self.warnings.append(text)
        if self.status == "ok": self.status = "warnings"
    def block(self, text): self.blocked.append(text); self.status = "blocked"
    def as_dict(self): return {"status":self.status,"ok":self.ok,"warnings":self.warnings,"blocked":self.blocked}

def pre_slice(*, bounds=None, bed=(220,220), profile=None, required_keys=(), before_profile=None,
              filaments=1, ifs_slots=4, tool_slots=None):
    """bounds is placed XY bbox (xmin,ymin,xmax,ymax); tools map T-index to 1-based IFS slot."""
    r=Result(); profile=profile or {}; tool_slots=tool_slots or {}
    missing=[k for k in required_keys if k not in profile or profile[k] in (None, "", [])]
    if missing: r.block("Required slicer profile settings are missing: "+", ".join(missing)+".")
    if before_profile is not None:
        protected={"machine_start_gcode","machine_end_gcode","post_process","print_host","print_host_webui","host_type","printer_agent","printer_technology"}
        protected.update(k for k in set(before_profile)|set(profile) if k.startswith("printhost_") or (k.endswith("_gcode") and k!="emit_machine_limits_to_gcode"))
        changed=sorted(k for k in protected if before_profile.get(k)!=profile.get(k))
        if changed: r.block("Bot attempted to change protected printer behavior/settings: "+", ".join(changed)+"; edit these only in Orca GUI.")
    if bounds is None:
        r.warn("Placed mesh bounds are unavailable; bed-fit validation is advisory only.")
    if bounds is not None:
        x0,y0,x1,y1=map(float,bounds)
        if x0<0 or y0<0 or x1>bed[0] or y1>bed[1]: r.block(f"Placed model bounds ({x0:g}..{x1:g} x, {y0:g}..{y1:g} mm) exceed the {bed[0]}x{bed[1]} mm bed.")
    if int(filaments)>int(ifs_slots): r.block(f"Profile has {filaments} filaments but only {ifs_slots} IFS slots are available.")
    if int(filaments)>1 and not tool_slots: r.block("Multi-filament job has no explicit T-index to physical IFS-slot mapping.")
    for t,slot in tool_slots.items():
        try: ti,si=int(str(t).lstrip('T')),int(slot)
        except (ValueError,TypeError): r.block(f"Invalid tool-to-slot mapping {t!r} → {slot!r}."); continue
        if ti<0 or si<1 or si>ifs_slots: r.block(f"T{ti} maps to IFS slot {si}; valid slots are 1 through {ifs_slots}.")
    if tool_slots and len(tool_slots)!=int(filaments): r.block("Explicit T-index mapping count does not match the profile filament count.")
    return r

MOVE=re.compile(r"^\s*G[0-3]\b([^;]*)",re.I)
WORD=re.compile(r"\b([XYZE])\s*(-?(?:\d+(?:\.\d*)?|\.\d+))",re.I)
def post_slice(gcode, *, ifs_slots=4, tool_slots=None, bed=(220,220), result_json=None):
    r=Result(); tool_slots=tool_slots or {}
    if isinstance(gcode, Path):
        text=gcode.read_text(errors="replace")
    elif isinstance(gcode, str) and "\\n" not in gcode and len(gcode)<4096 and Path(gcode).is_file():
        text=Path(gcode).read_text(errors="replace")
    else:
        text=str(gcode or "")
    low=text.lower()
    if not text.strip(): r.block("Orca produced no G-code; inspect its return code and error log."); return r
    if "g-code conflicts detected" in low or "slicing result conflict" in low or "gcode path conflicts" in low:
        r.block("Orca reported a G-code conflict; the slice cannot be used. Inspect overlapping geometry/wipe-tower placement (see Orca adapter diagnostic).")
    tools={int(n) for n in re.findall(r"(?im)^\s*T(\d+)\s*(?:;.*)?$",text)}
    for n in sorted(tools):
        if n not in tool_slots: r.block(f"G-code uses T{n}, but no physical IFS slot mapping is recorded.")
        elif not 1<=int(tool_slots[n])<=ifs_slots: r.block(f"T{n} maps outside the available IFS slots.")
    if tools and max(tools)>=ifs_slots: r.block(f"G-code uses tool T{max(tools)} but only {ifs_slots} IFS slots are available.")
    coords=[]; x=y=0.0
    for line in text.splitlines():
        m=MOVE.match(line)
        if not m: continue
        vals={k.upper():float(v) for k,v in WORD.findall(m.group(1))}
        x=vals.get('X',x); y=vals.get('Y',y)
        if 'X' in vals or 'Y' in vals:
            coords.append((x,y))
            if x<0 or y<0 or x>bed[0] or y>bed[1]: r.block(f"G-code move goes off the {bed[0]}x{bed[1]} mm bed at X{x:g} Y{y:g}."); break
    if not re.search(r"(?im)^;\s*(?:estimated printing time|estimated time|printing time)\s*=\s*\S|^;\s*time\s*:\s*\S",text):
        r.warn("G-code header has no estimated print-time metadata; estimate is unavailable offline.")
    if result_json:
        try:
            data=json.loads(Path(result_json).read_text() if isinstance(result_json,(str,Path)) else result_json)
            if int(data.get("return_code",0))!=0 or data.get("error_string","").strip().lower() not in ("","success.","success"):
                msg=str(data.get("error_string") or f"Orca returned code {data.get('return_code')}.")
                if "-101" in msg or "conflict" in msg.lower(): r.block("Orca slice failed with a G-code conflict (-101); inspect the Orca conflict diagnostic.")
                else: r.block("Orca did not complete the slice: "+msg)
        except (OSError,ValueError,TypeError) as e: r.warn(f"Could not parse Orca result metadata: {e}.")
    return r

def classify_orca_failure(text, return_code=None):
    s=(text or "").lower()
    if "conflict" in s or return_code==-101: return "gcode_conflict"
    if "not precalculated placeable areas" in s or return_code==-101: return "orca_geometry_or_conflict"
    if "param values" in s or return_code==-18: return "invalid_3mf_profile_value"
    if return_code in (-50,-24): return "orca_cli_failure"
    return "unknown_orca_failure"


PROTECTED_KEYS = ("machine_start_gcode", "machine_end_gcode", "post_process", "print_host", "print_host_webui", "host_type", "printer_agent", "printer_technology")
BASELINE_PATH = Path(__file__).with_name("protected-settings-baseline.json")

def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def _effective_config(artifact):
    # Orca's embedded config is authoritative; G-code header includes the
    # same key/value settings emitted as comments.
    if isinstance(artifact, dict): return artifact
    text = Path(artifact).read_text(errors="replace") if isinstance(artifact, (str, Path)) and Path(artifact).is_file() else str(artifact or "")
    found = {}
    for line in text.splitlines():
        m = re.match(r"^;\s*([A-Za-z0-9_]+)\s*=\s*(.*)$", line)
        if m and m.group(1) in PROTECTED_KEYS: found[m.group(1)] = m.group(2)
    return found

def _normalize(key, value):
    # The bed mesh name in START_PRINT is chosen per job by orca_adapter from the
    # validated calibration state (MESH_DATA when calibrated, auto otherwise).
    # It is not a hand edited printer setting, so it must not trip the guard.
    if key == "machine_start_gcode" and isinstance(value, str):
        return re.sub(r"\bMESH=[A-Za-z0-9_]+", "MESH=<mesh>", value)
    return value

def _baseline(config):
    import hashlib
    out = {}
    for k in PROTECTED_KEYS:
        if k not in config: continue
        v = _normalize(k, config.get(k))
        out[k] = {"sha256": hashlib.sha256(_canonical(v).encode()).hexdigest(),
                  **({"value": v} if len(_canonical(v)) <= 160 else {})}
    return out

def approve_baseline(config, path=BASELINE_PATH):
    current = _baseline(_effective_config(config))
    previous = json.loads(Path(path).read_text()) if Path(path).exists() else {}
    for key in sorted(set(previous) | set(current)):
        if previous.get(key) != current.get(key): print(f"{key}: {previous.get(key, '<missing>')} -> {current.get(key, '<missing>')}")
    Path(path).write_text(json.dumps(current, indent=2, sort_keys=True) + chr(10))
    return current

def enforce_approved_baseline(artifact, path=BASELINE_PATH):
    r = Result()
    if not Path(path).exists():
        r.warn(f"Protected-settings baseline missing; slicing allowed. Approve with: python3 {Path(__file__).name} approve-baseline")
        return r
    if not isinstance(artifact, (str, Path)) or not Path(artifact).is_file():
        r.warn("Protected-settings artifact unavailable; slicing allowed pending baseline check.")
        return r
    expected = json.loads(Path(path).read_text())
    actual = _effective_config(artifact)
    for key, record in expected.items():
        if key not in actual or _baseline({key: actual[key]}).get(key, {}).get("sha256") != record.get("sha256"):
            r.block(f"Protected printer setting {key} differs from the approved baseline. Re-approve deliberately with: python3 {Path(__file__).name} approve-baseline")
    return r
