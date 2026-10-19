#!/usr/bin/env python3
"""Installed nozzle + loaded spool: single source of truth and live cross-check.

State file: <state_dir>/printer_hardware.json (settings paths.hermes_home)
Live checks: Klipper (via Moonraker) nozzle_diameter + probe z_offset, Moonraker
active Spoolman spool, Spoolman spool record.

probe.z_offset, the screenless saved gcode_offsets.z, and the native screen
zProbeOffset are separate stores. None is copied into another, and none is
marked verified just because a config number was readable.

  python3 -m print_buddy.core.printer_state check          -> prints one summary line, exit 0 OK / 2 mismatch
  python3 -m print_buddy.core.printer_state show           -> prints the state JSON
  python3 -m print_buddy.core.printer_state set --spool 7  -> operator-instructed change; also sets Moonraker active spool
  python3 -m print_buddy.core.printer_state set --nozzle 0.4 --nozzle-type "brass" (syncs printer.cfg, restarts Klipper, marks z_offset unverified)
  python3 -m print_buddy.core.printer_state set --z-offset N -> record a measured user offset; does not write Klipper
  python3 -m print_buddy.core.printer_state set --sync-z   -> record live probe.z_offset as the probe store only
"""
import argparse, datetime, json, os, re, sys, urllib.request

from .. import printers, settings

STATE = str(settings.state_dir() / "printer_hardware.json")


_FAMILY_BASES = ("PETG", "PLA", "ABS", "ASA", "TPU")


def material_family(material):
    """Slicing family for a material label: PLA+, PLA Pro, Matte PLA, Silk PLA -> PLA.

    Carbon fiber stays distinct (PLA-CF). Unknown materials compare by their
    normalized label, so PETG never matches PLA.
    """
    m = re.sub(r"[\s_+\-]+", "", str(material or "").upper())
    for base in _FAMILY_BASES:
        if base in m:
            return f"{base}-CF" if "CF" in m.replace(base, "", 1) else base
    return m


def same_material(a, b):
    """True when two material labels slice as the same family."""
    fa, fb = material_family(a), material_family(b)
    return bool(fa) and fa == fb


def load():
    with open(STATE) as f:
        return json.load(f)


def save(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2)
        f.write("\n")
    os.replace(tmp, STATE)


def _get(url, data=None, method=None, timeout=6):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def sync_klipper_nozzle(moonraker_url, nozzle_diameter):
    """Update nozzle_diameter in printer.cfg via Moonraker upload API and restart Klipper."""
    cfg_url = f"{moonraker_url}/server/files/config/printer.cfg"
    req = urllib.request.Request(cfg_url)
    with urllib.request.urlopen(req, timeout=10) as r:
        content = r.read().decode("utf-8")

    pattern = r"^(nozzle_diameter\s*:\s*)([0-9.]+)"
    match = re.search(pattern, content, flags=re.MULTILINE)
    if not match:
        raise ValueError("Could not find nozzle_diameter in printer.cfg")

    current_val = float(match.group(2))
    if abs(current_val - nozzle_diameter) < 1e-4:
        return False

    new_content = re.sub(pattern, rf"\g<1>{nozzle_diameter:.3f}", content, count=1, flags=re.MULTILINE)

    boundary = "----KlipperConfigUploadBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="root"\r\n\r\n'
        f"config\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="printer.cfg"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
        f"{new_content}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    upload_url = f"{moonraker_url}/server/files/upload"
    up_req = urllib.request.Request(upload_url, data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}"
    })
    with urllib.request.urlopen(up_req, timeout=15) as r:
        pass

    restart_url = f"{moonraker_url}/printer/restart"
    res_req = urllib.request.Request(restart_url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(res_req, timeout=10) as r:
        pass

    return True


def pressure_advance_problems(st, live_pa):
    """Recorded pressure advance must match Klipper and belong to the installed nozzle."""
    rec = st.get("pressure_advance")
    if not rec:
        return []
    probs = []
    if rec.get("nozzle_installed") != (st.get("nozzle") or {}).get("installed"):
        probs.append(f"Pressure advance {rec.get('value')} was tuned for a different nozzle; retune it")
    try:
        if live_pa is not None and abs(float(live_pa) - float(rec["value"])) > 1e-4:
            probs.append(f"Klipper pressure_advance {live_pa} != recorded {rec['value']}")
    except (KeyError, TypeError, ValueError):
        probs.append("Recorded pressure advance is unreadable")
    return probs


def offset_authority_problems(st, variables, native):
    """Compare like-for-like stores; never substitute probe or another mode's offset."""
    import math
    def numeric(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    authority = st.get("calibration_authority") or {}
    mode = variables.get("display_off")
    if mode == 0:
        expected = (st.get("calibration_baseline") or {}).get("native_zProbeOffset")
        actual = (native.get("leftExtruderOffset") or {}).get("zProbeOffset")
        if authority.get("mode") != "native" or authority.get("operator_confirmed") is not True:
            return ["native calibration authority is not operator confirmed"]
        if not numeric(expected) or not numeric(actual) or abs(expected - actual) > 0.000001:
            return ["native zProbeOffset missing or differs from the operator-confirmed baseline"]
        return []
    if mode == 1:
        expected = st.get("z_offset_mm")
        actual = (variables.get("gcode_offsets") or {}).get("z")
        if (authority.get("mode") != "screenless" or authority.get("operator_confirmed") is not True
                or not st.get("z_offset_verified") or variables.get("load_zoffset") != 1
                or not numeric(expected) or not numeric(actual) or abs(expected - actual) > 0.000001):
            return ["screenless user offset has no verified matching authority; native calibration cannot substitute"]
        return []
    return ["calibration mode is unknown; no offset substitution permitted"]


def check(st=None):
    """Return (ok, problems, facts). Never raises on network errors; reports them."""
    st = st or load()
    probs, facts = [], {}
    native = printers.current().has_native_screen  # offset authority is a ZMod screen concept
    mr, sm = st["moonraker_url"], st["spoolman_url"]
    try:
        s = _get(f"{mr}/printer/objects/query?configfile=settings")["result"]["status"]["configfile"]["settings"]
        facts["klipper_nozzle"] = float(s["extruder"]["nozzle_diameter"])
        facts["klipper_probe_z_offset"] = float(s.get("probe", {}).get("z_offset", "nan"))
        probs.extend(pressure_advance_problems(st, s["extruder"].get("pressure_advance")))
        recorded_probe = (st.get("calibration_baseline") or {}).get("probe_z_offset", st.get("z_offset_mm"))
        if native and abs(facts["klipper_probe_z_offset"] - float(recorded_probe)) > 1e-3:
            probs.append(
                f"Klipper probe.z_offset {facts['klipper_probe_z_offset']} != recorded probe offset {recorded_probe}. "
                "This is the probe trigger, not the user offset; do not copy it into gcode_offsets.z or zProbeOffset"
            )
    except Exception as e:
        probs.append(f"Moonraker unreachable: {e}")
    if "klipper_nozzle" in facts and abs(facts["klipper_nozzle"] - st["nozzle"]["diameter_mm"]) > 1e-3:
        probs.append(f"Klipper nozzle_diameter {facts['klipper_nozzle']} != state {st['nozzle']['diameter_mm']}")
    try:
        facts["moonraker_active_spool"] = _get(f"{mr}/server/spoolman/spool_id")["result"].get("spool_id")
        if facts["moonraker_active_spool"] != st["spool"]["spoolman_id"]:
            facts["active_spool_mismatch"] = f"Moonraker active spool {facts['moonraker_active_spool']} != state #{st['spool']['spoolman_id']}"
    except Exception as e:
        probs.append(f"Moonraker spoolman status failed: {e}")
    try:
        sp = _get(f"{sm}/api/v1/spool/{st['spool']['spoolman_id']}")
        facts["spool_name"] = sp["filament"]["name"]
        facts["spool_material"] = sp["filament"].get("material")
        facts["spool_remaining_g"] = round(sp.get("remaining_weight") or 0)
        if sp.get("archived"):
            probs.append(f"Spoolman spool #{sp['id']} is archived")
        if sp["filament"]["name"] != st["spool"]["name"]:
            probs.append(f"Spoolman #{sp['id']} is '{sp['filament']['name']}', state says '{st['spool']['name']}'")
    except Exception as e:
        probs.append(f"Spoolman lookup failed: {e}")
    try:
        if not native:
            return (not probs), probs, facts
        variables = _get(f"{mr}/printer/objects/query?save_variables")["result"]["status"]["save_variables"]["variables"]
        native = _get(f"{mr}/server/files/config/Adventurer5M.json") if variables.get("display_off") == 0 else {}
        calibration_problems = offset_authority_problems(st, variables, native)
        probs.extend(calibration_problems)
        facts["calibration_valid"] = not calibration_problems
        facts["calibration_owner"] = "native" if variables.get("display_off") == 0 else "screenless" if variables.get("display_off") == 1 else "unknown"
    except Exception as e:
        probs.append(f"Calibration authority read failed: {e}")
    return (not probs), probs, facts


def summary(st, calibration_owner="unknown", calibration_valid=None):
    if not printers.current().has_native_screen:
        return (f"{st['nozzle']['diameter_mm']} mm {st['nozzle']['type']} nozzle, "
                f"Spoolman #{st['spool']['spoolman_id']} {st['spool']['name']} ({st['spool']['material']}), "
                f"{st['temps_c']['nozzle']}/{st['temps_c']['bed']} C")
    if calibration_owner == "native":
        offset = (st.get("calibration_baseline") or {}).get("native_zProbeOffset", "unknown")
        calibration = f"native zProbeOffset {offset} (screenless user offset not applicable)"
    elif calibration_owner == "screenless":
        value = st.get("z_offset_mm")
        verified = st.get("z_offset_verified") is True
        calibration = f"screenless user offset {value} ({'verified' if verified else 'unverified'})"
    else:
        calibration = f"user offset {st.get('z_offset_mm')} ({'unverified' if not st.get('z_offset_verified') else 'verified'}); calibration mode unknown"
    # Only the live checker may report validation. A renderer without its live
    # inputs must not synthesize a failure from absent gcode_offsets/native data.
    if calibration_valid is False:
        calibration += "; strict calibration validation failed"
    return (f"{st['nozzle']['diameter_mm']} mm {st['nozzle']['type']} nozzle, "
            f"probe z_offset {((st.get('calibration_baseline') or {}).get('probe_z_offset', st.get('z_offset_mm')))}, "
            f"{calibration}, "
            f"Spoolman #{st['spool']['spoolman_id']} {st['spool']['name']} ({st['spool']['material']}), "
            f"{st['temps_c']['nozzle']}/{st['temps_c']['bed']} C")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check"); sub.add_parser("show")
    s = sub.add_parser("set")
    s.add_argument("--spool", type=int); s.add_argument("--nozzle", type=float)
    s.add_argument("--nozzle-type"); s.add_argument("--nozzle-temp", type=int); s.add_argument("--bed-temp", type=int)
    s.add_argument("--z-offset", type=float, help="record a measured user offset; does not write Klipper or the native screen")
    s.add_argument("--sync-z", action="store_true", help="record live probe.z_offset as the probe store only; never marks the user offset verified")
    s.add_argument("--pressure-advance", type=float, help="record the pressure advance tuned for the installed nozzle; does not write Klipper")
    s.add_argument("--no-sync-klipper", action="store_true", help="skip syncing nozzle to Klipper printer.cfg")
    a = ap.parse_args()
    st = load()
    if a.cmd == "show":
        print(json.dumps(st, indent=2)); return
    if a.cmd == "check":
        ok, probs, facts = check(st)
        print(("HW OK: " if ok else "HW MISMATCH: ") + summary(st, facts.get("calibration_owner", "unknown"), facts.get("calibration_valid")) +
              (f", {facts.get('spool_remaining_g')} g left" if "spool_remaining_g" in facts else ""))
        for p in probs:
            print("  - " + p)
        sys.exit(0 if ok else 2)
    # set
    if a.spool is not None:
        sp = _get(f"{st['spoolman_url']}/api/v1/spool/{a.spool}")
        f = sp["filament"]
        st["spool"] = {"spoolman_id": a.spool, "name": f["name"], "material": f.get("material"),
                       "diameter_mm": f.get("diameter", 1.75), "density": f.get("density", 1.24)}
        if f.get("settings_extruder_temp"): st["temps_c"]["nozzle"] = f["settings_extruder_temp"]
        if f.get("settings_bed_temp"): st["temps_c"]["bed"] = f["settings_bed_temp"]
        _get(f"{st['moonraker_url']}/server/spoolman/spool_id", {"spool_id": a.spool}, "POST")
    if a.nozzle is not None:
        st["nozzle"] = {"diameter_mm": a.nozzle, "type": a.nozzle_type or "unspecified",
                        "installed": datetime.date.today().isoformat()}
        st["z_offset_verified"] = False
        st["z_offset_mm"] = None
        st["calibration_authority"] = {"mode": None, "operator_confirmed": False, "reason": "Nozzle changed; previous calibration is historical only"}
        st["z_offset_note"] = "Nozzle changed; calibration needs a measured confirmation for the active mode. --sync-z only records the probe trigger."
        if st.get("pressure_advance"):
            st["pressure_advance"]["stale"] = True
        if not a.no_sync_klipper:
            try:
                if sync_klipper_nozzle(st["moonraker_url"], a.nozzle):
                    print(f"Klipper printer.cfg updated to {a.nozzle:.3f} mm and Klipper restarted.")
                else:
                    print(f"Klipper printer.cfg already matches {a.nozzle:.3f} mm.")
            except Exception as e:
                print(f"Warning: Failed to sync nozzle to Klipper printer.cfg: {e}")
    if getattr(a, "sync_z", False):
        try:
            s = _get(f"{st['moonraker_url']}/printer/objects/query?configfile=settings")["result"]["status"]["configfile"]["settings"]
            live_z = float(s.get("probe", {}).get("z_offset", "nan"))
            if live_z == live_z:
                st.setdefault("calibration_baseline", {})["probe_z_offset"] = live_z
                print(f"Recorded live Klipper probe.z_offset ({live_z} mm) as the probe store only. User offset unchanged.")
            else:
                print("Warning: Could not read probe.z_offset from Klipper.")
        except Exception as e:
            print(f"Warning: Failed to read live z_offset from Klipper: {e}")
    if a.z_offset is not None:
        st["z_offset_mm"], st["z_offset_verified"] = a.z_offset, True
        st["z_offset_note"] = (
            f"Operator-supplied measured user offset on {datetime.date.today()} with "
            f"{st['nozzle']['diameter_mm']} {st['nozzle']['type']}. Not copied from probe.z_offset."
        )
    if a.pressure_advance is not None:
        st["pressure_advance"] = {"value": a.pressure_advance, "nozzle_installed": st["nozzle"].get("installed"),
                                  "recorded": datetime.date.today().isoformat()}
    if a.nozzle_temp: st["temps_c"]["nozzle"] = a.nozzle_temp
    if a.bed_temp: st["temps_c"]["bed"] = a.bed_temp
    st["updated"] = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    save(st)
    print("saved: " + summary(st))


if __name__ == "__main__":
    main()
