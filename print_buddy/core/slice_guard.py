"""Offline deterministic checks around Orca slicing; no printer or slicer calls."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import settings

@dataclass
class Result:
    status: str = "ok"
    warnings: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    effective_settings: dict = field(default_factory=dict)
    @property
    def ok(self): return self.status == "ok"
    def warn(self, text):
        self.warnings.append(text)
        if self.status == "ok": self.status = "warnings"
    def block(self, text): self.blocked.append(text); self.status = "blocked"
    def as_dict(self):
        return {"status": self.status, "ok": self.ok, "warnings": self.warnings,
                "blocked": self.blocked, "effective_settings": self.effective_settings}

def _printer(bed, ifs_slots):
    printer = settings.current()['printer']
    return tuple(bed or printer['bed_mm']), int(ifs_slots or printer['ifs_slots'])

def pre_slice(*, bounds=None, bed=None, profile=None, required_keys=(), before_profile=None,
              filaments=1, ifs_slots=None, tool_slots=None, nozzle_type=None, materials=None,
              nozzle_temp=None, nozzle_temp_is_effective=False):
    """bounds is placed XY bbox (xmin,ymin,xmax,ymax); tools map T-index to 1-based IFS slot."""
    r=Result(); profile=profile or {}; tool_slots=tool_slots or {}; bed,ifs_slots=_printer(bed,ifs_slots)
    if nozzle_type:
        from .nozzle import check_nozzle_material_safety, AbrasiveNozzleError, check_nozzle_temperature_safety, NozzleError
        mats = [materials] if isinstance(materials, str) else (materials or [])
        for mat in mats:
            try:
                check_nozzle_material_safety(nozzle_type, mat)
            except AbrasiveNozzleError as exc:
                r.block(str(exc))
        if nozzle_temp is not None:
            try:
                if nozzle_temp_is_effective:
                    check_nozzle_temperature_safety(nozzle_type, nozzle_temp)
                else:
                    from .nozzle import effective_nozzle_temperature
                    effective_nozzle_temperature(nozzle_type, nozzle_temp)
            except NozzleError as exc:
                r.block(str(exc))
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
        if x0<0 or y0<0 or x1>bed[0] or y1>bed[1]: r.block(f"Placed model bounds ({x0:g}..{x1:g} x, {y0:g}..{y1:g} mm) exceed the {bed[0]:g}x{bed[1]:g} mm bed.")
    if int(filaments)>int(ifs_slots): r.block(f"Profile has {filaments} filaments but only {ifs_slots} IFS slots are available.")
    if int(filaments)>1 and not tool_slots: r.block("Multi-filament job has no explicit T-index to physical IFS-slot mapping.")
    for t,slot in tool_slots.items():
        try: ti,si=int(str(t).lstrip('T')),int(slot)
        except (ValueError,TypeError): r.block(f"Invalid tool-to-slot mapping {t!r} → {slot!r}."); continue
        if ti<0 or si<1 or si>ifs_slots: r.block(f"T{ti} maps to IFS slot {si}; valid slots are 1 through {ifs_slots}.")
    if tool_slots and len(tool_slots)!=int(filaments): r.block("Explicit T-index mapping count does not match the profile filament count.")
    return r

# Prusa style "; estimated printing time (normal mode) = 1h 2m" and Orca/Bambu style
# "; model printing time: 1h 2m; total estimated time: 1h 5m", plus older "; TIME:123".
TIME_HEADER=re.compile(r"(?im)^;\s*(?:estimated printing time(?:\s*\([^)]*\))?|estimated time|printing time)\s*=\s*\S"
                       r"|^;.*\b(?:model printing time|total estimated time)\s*:\s*\S|^;\s*time\s*:\s*\S")
MOVE=re.compile(r"^\s*G[0-3]\b([^;]*)",re.I)
WORD=re.compile(r"\b([XYZE])\s*(-?(?:\d+(?:\.\d*)?|\.\d+))",re.I)
HERMES_SLOT_PATTERN = re.compile(r"^Hermes slot \d+(?:\s+\S.*)?$", re.I)


def is_allowed_filament_id(value, own_ids=None):
    """Check if a filament profile ID is an allowed template ID or Print Buddy generated Hermes slot."""
    if not value or not isinstance(value, str):
        return False
    v = value.strip().strip('"')
    if own_ids and v in own_ids:
        return True
    return bool(HERMES_SLOT_PATTERN.match(v))


def _mm(value):
    return "?" if value is None else f"{value:g}"

def body_motion_problems(body, bed, envelope, height=None):
    """Bounds for G-code whose vendor start/end blocks park the head off the bed (Bambu wiper, purge lane).

    body is the text between Orca's machine start and end markers. Every absolute XY move must stay inside
    envelope (xmin, ymin, xmax, ymax); every extruding move must also stay on the bed and under height.
    Moves made in G91 relative mode are skipped and leave the position unknown until set again.
    """
    problems=[]; x=y=z=None; relative=False
    for line in body.splitlines():
        code=line.split(';',1)[0].strip().upper()
        if code.startswith('G90'): relative=False; continue
        if code.startswith('G91'): relative=True; x=y=z=None; continue
        m=MOVE.match(line)
        if not m or relative: continue
        vals={k.upper():float(v) for k,v in WORD.findall(m.group(1))}
        x=vals.get('X',x); y=vals.get('Y',y); z=vals.get('Z',z)
        if 'X' in vals and not envelope[0]<=x<=envelope[2] or 'Y' in vals and not envelope[1]<=y<=envelope[3]:
            problems.append(f"G-code move leaves the machine envelope at X{_mm(x)} Y{_mm(y)}."); break
        if vals.get('E',0)>0 and (x is not None and not 0<=x<=bed[0] or y is not None and not 0<=y<=bed[1]
                                  or height is not None and z is not None and z>height):
            problems.append(f"G-code extrudes off the {bed[0]:g}x{bed[1]:g} mm bed at X{_mm(x)} Y{_mm(y)} Z{_mm(z)}."); break
    return problems

def post_slice(gcode, *, ifs_slots=None, tool_slots=None, bed=None, result_json=None,
               templates=None, profile_paths=(), envelope=None):
    """Check bounds + effective motion/profile settings and capture provenance.

    envelope (xmin, ymin, xmax, ymax) is for printers whose vendor start/end G-code moves off the bed:
    only the toolpath between Orca's start/end markers is bounds- and tool-checked (body_motion_problems).
    """
    r=Result(); tool_slots=tool_slots or {}; bed,ifs_slots=_printer(bed,ifs_slots)
    if isinstance(gcode, Path):
        text=gcode.read_text(errors="replace")
    elif isinstance(gcode, str) and "\\n" not in gcode and len(gcode)<4096 and Path(gcode).is_file():
        text=Path(gcode).read_text(errors="replace")
    else:
        text=str(gcode or "")
    low=text.lower()
    if not text.strip(): r.block("Orca produced no G-code; inspect its return code and error log."); return r
    # Auto can resolve to Spiral on overhang-crossing travels in Orca; permit only Normal Lift.
    template_root = Path(templates or settings.current()['orca']['templates'])
    own_settings = {}
    for filename in ('machine.json', 'process.json', 'filament.json'):
        path = template_root / filename
        if path.is_file():
            own_settings.update(json.loads(path.read_text()))
    own_filament_ids = set()
    for path in (Path(p) for p in profile_paths):
        if path.is_file():
            data = json.loads(path.read_text())
            values = data.get('filament_settings_id', [])
            own_filament_ids.update(str(value).strip().strip('"') for value in (values if isinstance(values, list) else [values]))
    if not own_filament_ids:
        values = own_settings.get('filament_settings_id', [])
        own_filament_ids.update(str(value).strip().strip('"') for value in (values if isinstance(values, list) else [values]))
    if re.search(r"(?m)^;\s*filament_settings_id\s*=", text, re.I) and not own_filament_ids:
        r.block("Cannot verify filament_settings_id slots: no active template filament IDs are available.")
    for line in text.splitlines():
        match_brim = re.match(r"^;\s*brim_type\s*=\s*(.*)$", line, re.I)
        if match_brim:
            val = match_brim.group(1).strip().strip('"')
            allowed_brim = own_settings.get('brim_type')
            if allowed_brim is not None and val.lower() != str(allowed_brim).strip().lower():
                r.block(f"Foreign effective setting brim_type: {val!r}; expected {allowed_brim!r}.")
        match = re.match(r"^;\s*(filament_z_hop_types|z_hop_types)\s*=\s*(.*)$", line, re.I)
        if match:
            key, value = match.group(1), match.group(2)
            for slot, entry in enumerate(value.split(','), 1):
                raw = entry.strip().strip('"')
                if not raw:
                    continue
                if raw.lower() != 'normal lift':
                    r.block(f"Unsafe effective setting {key} slot {slot}: {raw!r}; only Normal Lift is permitted.")
        match = re.match(r"^;\s*((?:filament|printer|print)_settings_id)\s*=\s*(.*)$", line, re.I)
        if match:
            key = match.group(1).lower()
            entries = match.group(2).split(';') if key == 'filament_settings_id' else [match.group(2)]
            raw_ids = own_filament_ids if key == 'filament_settings_id' else own_settings.get(key, [])
            own_ids = {str(value).strip().strip('"') for value in (raw_ids if isinstance(raw_ids, (list, set, tuple)) else [raw_ids])}
            for slot, entry in enumerate(entries, 1):
                value = entry.strip().strip('"')
                is_allowed = is_allowed_filament_id(value, own_ids) if key == 'filament_settings_id' else (value in own_ids)
                if not value or not is_allowed:
                    r.block(f"Foreign effective setting {match.group(1)} slot {slot}: {value!r}.")
        match = re.match(r"^;\s*enable_arc_fitting\s*=\s*(.*)$", line, re.I)
        if match and match.group(1).strip() == '1':
            r.block("Unsafe effective setting enable_arc_fitting=1.")
    if "g-code conflicts detected" in low or "slicing result conflict" in low or "gcode path conflicts" in low:
        r.block("Orca reported a G-code conflict; the slice cannot be used. Inspect overlapping geometry/wipe-tower placement (see Orca adapter diagnostic).")
    # With an envelope, the vendor start/end blocks are the printer maker's (Bambu uses T1000 and T255 there);
    # tools and bounds are checked on the toolpath between Orca's markers.
    start, end = "; MACHINE_START_GCODE_END", "; MACHINE_END_GCODE_START"
    body = text
    if envelope is not None:
        if start in text and end in text:
            body = text.split(start,1)[1].split(end,1)[0]
        else:
            r.block("G-code has no Orca machine start/end markers; toolpath bounds cannot be checked.")
    tools={int(n) for n in re.findall(r"(?im)^\s*T(\d+)\s*(?:;.*)?$",body)}
    for n in sorted(tools):
        if n not in tool_slots: r.block(f"G-code uses T{n}, but no physical IFS slot mapping is recorded.")
        elif not 1<=int(tool_slots[n])<=ifs_slots: r.block(f"T{n} maps outside the available IFS slots.")
    if tools and max(tools)>=ifs_slots: r.block(f"G-code uses tool T{max(tools)} but only {ifs_slots} IFS slots are available.")
    coords=[]; x=y=0.0
    if envelope is not None and body is not text:
        for problem in body_motion_problems(body, bed, envelope):
            r.block(problem)
    for line in (text.splitlines() if envelope is None else ()):
        m=MOVE.match(line)
        if not m: continue
        vals={k.upper():float(v) for k,v in WORD.findall(m.group(1))}
        x=vals.get('X',x); y=vals.get('Y',y)
        if 'X' in vals or 'Y' in vals:
            coords.append((x,y))
            if x<0 or y<0 or x>bed[0] or y>bed[1]: r.block(f"G-code move goes off the {bed[0]:g}x{bed[1]:g} mm bed at X{x:g} Y{y:g}."); break
    effective = {}
    for line in text.splitlines():
        match = re.match(
            r"^;\s*(filament_z_hop_types|z_hop_types|filament_wipe|"
            r"filament_wipe_distance|filament_settings_id|printer_settings_id|"
            r"print_settings_id|brim_type)\s*=\s*(.*)$", line, re.I)
        if match:
            effective[match.group(1)] = match.group(2).strip()
    slot_details = []
    per_slot = {key: value.split(',') for key, value in effective.items()
                if key in ('filament_z_hop_types', 'filament_wipe', 'filament_wipe_distance')}
    ids = effective.get('filament_settings_id', '').split(';')
    for index in range(max([len(v) for v in per_slot.values()] + [len(ids)])):
        item = {'slot': index + 1}
        for key, values in per_slot.items():
            if index < len(values):
                item[key] = values[index].strip()
        if index < len(ids):
            item['filament_settings_id'] = ids[index].strip().strip('"')
        slot_details.append(item)
    effective['filament_slots'] = slot_details
    r.effective_settings = effective
    if not TIME_HEADER.search(text):
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
BASELINE_PATH = settings.ROOT / "config" / "protected-settings-baseline.json"

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
        r.warn("Protected-settings baseline missing; slicing allowed. Approve with: python3 -m print_buddy.core.approve_baseline approve-baseline <artifact>")
        return r
    if not isinstance(artifact, (str, Path)) or not Path(artifact).is_file():
        r.warn("Protected-settings artifact unavailable; slicing allowed pending baseline check.")
        return r
    expected = json.loads(Path(path).read_text())
    actual = _effective_config(artifact)
    for key, record in expected.items():
        if key not in actual or _baseline({key: actual[key]}).get(key, {}).get("sha256") != record.get("sha256"):
            r.block(f"Protected printer setting {key} differs from the approved baseline. Re-approve deliberately with: python3 -m print_buddy.core.approve_baseline approve-baseline <artifact>")
    return r
