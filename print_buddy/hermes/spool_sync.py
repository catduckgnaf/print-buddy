"""Spoolman -> printer one-way spool sync and the /spool command logic.

Spoolman is the source of truth. The AD5X screen is only *told* what Spoolman
says, through the Z-Mod `CHANGE_ZCOLOR SLOT= TYPE= HEX=` macro. Nothing here
reads the screen back into Spoolman.

Usage accounting: Moonraker charges extrusion to its active Spoolman spool.
`suspend_usage()` clears that so an unidentified mid-print swap charges no one
until a human says which spool is loaded; `resume_usage()` re-points it.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .. import printers
from . import _config

HARDWARE_STATE = _config.state_file("PRINTER_HARDWARE_STATE", "printer_hardware.json")
PENDING_SCREEN = _config.state_file("SCREEN_SYNC_PENDING", "screen_sync_pending.json")
MOONRAKER = _config.moonraker_url()
SPOOLMAN = _config.service_url("spoolman_url")
SHELF = "Shelf"
SLOTS = (1, 2, 3, 4)

Client = Callable[[str, str, Any], Any]


class SpoolError(RuntimeError):
    """A refused /spool action. Nothing was changed when this is raised before a write."""


# ---------------------------------------------------------------- transports

def _http(base: str, method: str, path: str, body: Any = None, timeout: float = 8) -> Any:
    if not base:
        raise SpoolError("the service for this request is not configured "
                         "(services.moonraker_url / services.spoolman_url in config/local.yaml or config/local.toml)")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if method == "POST" and data is None:
        req.data = b"{}"
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode() or "{}"
    return json.loads(raw)


def spoolman(method: str, path: str, body: Any = None) -> Any:
    return _http(SPOOLMAN, method, path, body)


def moonraker(method: str, path: str, body: Any = None) -> Any:
    return _http(MOONRAKER, method, path, body, timeout=15)


# ---------------------------------------------------------------- state file

def load_state(path: Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or HARDWARE_STATE).read_text())


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    target = Path(path or HARDWARE_STATE)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, target)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- mapping

def screen_hex(value: Any) -> str | None:
    text = str(value or "").strip().lstrip("#").upper()
    text = str(value or "").strip().lstrip("#").upper()
    if "," in text:
        return None
    return text if re.fullmatch(r"[0-9A-F]{6}", text) else None


def screen_command(slot: int, material: str, hex_code: str) -> str:
    """CHANGE_ZCOLOR line for the printer screen; the printer's adapter builds it."""
    return printers.current().screen_command(slot, material, hex_code)


# ---------------------------------------------------------------- printer side

def printer_state(mr: Client = moonraker) -> str:
    try:
        res = mr("GET", "/printer/objects/query?print_stats=state", None)
        return str(res["result"]["status"]["print_stats"]["state"])
    except Exception:
        return "unknown"


def push_screen(slot: int, material: str, hex_code: str, *, mr: Client = moonraker,
                pending_path: Path | None = None) -> str:
    """Tell the screen what Spoolman says. Deferred while printing; flushed when idle.

    Returns 'pushed', 'deferred', 'unsupported' (the printer has no screen), or raises SpoolError for unmappable data.
    """
    if not printers.current().multi_slot:
        return "unsupported"  # stock Klipper has no screen to tell
    command = screen_command(slot, material, hex_code)
    pending = Path(pending_path or PENDING_SCREEN)
    if printer_state(mr) in ("printing", "unknown"):
        queued = _read_json(pending)
        queued[str(slot)] = {"command": command, "queued_at": time.time()}
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps(queued, indent=2) + "\n")
        return "deferred"
    res = mr("POST", "/printer/gcode/script?script=" + urllib.parse.quote(command), None)
    if res.get("result") != "ok":
        raise SpoolError(f"printer refused {command}: {res}")
    queued = _read_json(pending)
    if queued.pop(str(slot), None) is not None:
        pending.write_text(json.dumps(queued, indent=2) + "\n")
    return "pushed"


def flush_pending_screen(*, mr: Client = moonraker, pending_path: Path | None = None) -> list[int]:
    """Send screen updates that were deferred during a print. Safe to call often."""
    pending = Path(pending_path or PENDING_SCREEN)
    queued = _read_json(pending)
    if not queued or printer_state(mr) in ("printing", "unknown"):
        return []
    done = []
    for slot, item in sorted(queued.items()):
        res = mr("POST", "/printer/gcode/script?script=" + urllib.parse.quote(item["command"]), None)
        if res.get("result") == "ok":
            done.append(int(slot))
    remaining = {k: v for k, v in queued.items() if int(k) not in done}
    pending.write_text(json.dumps(remaining, indent=2) + "\n")
    return done


def active_usage_spool(mr: Client = moonraker) -> int | None:
    return (mr("GET", "/server/spoolman/spool_id", None).get("result") or {}).get("spool_id")


def suspend_usage(mr: Client = moonraker) -> int | None:
    """Stop Moonraker charging any spool. Returns the spool that was being charged."""
    prior = active_usage_spool(mr)
    mr("POST", "/server/spoolman/spool_id", {})
    if active_usage_spool(mr) is not None:
        raise SpoolError("Moonraker still reports an active spool after clearing it")
    return prior


def resume_usage(spool_id: int, mr: Client = moonraker) -> None:
    mr("POST", "/server/spoolman/spool_id", {"spool_id": int(spool_id)})
    back = active_usage_spool(mr)
    if back != int(spool_id):
        raise SpoolError(f"Moonraker active spool readback {back!r} != #{spool_id}")


# ---------------------------------------------------------------- slot binding

def _slot_record(slot: int, spool: dict[str, Any], old: dict[str, Any] | None, note: str) -> dict[str, Any]:
    filament = spool.get("filament") or {}
    remaining = spool.get("remaining_weight")
    raw_multi = filament.get("multi_color_hexes")
    multi_color = isinstance(raw_multi, str) and "," in raw_multi
    same_spool = (old or {}).get("spoolman_id") == spool.get("id")
    raw_name = str(filament.get("name") or ((old or {}).get("color") if same_spool else None) or "unknown").strip()
    material = str(filament.get("material") or ((old or {}).get("material") if same_spool else None) or "unknown").strip()
    # A trailing material token, or a name that is only that token, is not a color.
    # "Pink PLA" + PLA -> Pink; "PLA" + PLA stays one PLA, not "PLA PLA".
    if material and raw_name.casefold() == material.casefold():
        color = ""
    elif material:
        color = re.sub(rf"\s+{re.escape(material)}$", "", raw_name, flags=re.IGNORECASE).strip()
    else:
        color = raw_name
    display_name = " ".join(x for x in (color, material) if x)
    # An exact material name has no color token. Do not store the material as the color.
    stored_color = color.lower() if color else ((old or {}).get("color") if same_spool else "") or ""
    # A null/invalid Spoolman color is not permission to reuse cached color: that
    # can silently assign another spool's swatch to the physical slot.
    hex_code = "" if multi_color else screen_hex(filament.get("color_hex") or filament.get("multi_color_hexes"))
    if hex_code is None:
        # Intake/sync may encounter incomplete catalog entries; keep the spool
        # identity but never inherit a stale screen swatch. Start preflight must
        # block until a valid live color can be synchronized.
        hex_code = ""
    return {
        "slot": slot,
        "material": material,
        "color": stored_color,
        "hex": hex_code,
        "spoolman_id": int(spool["id"]),
        "name": display_name or f"Spool #{spool['id']}",
        "remaining_grams": round(float(remaining), 1) if isinstance(remaining, (int, float)) else None,
        "quantity_status": "spoolman",
        "weight_confidence": "spoolman",
        "physical_color_verified": not multi_color and bool(hex_code),
        "multi_color": multi_color,
        "representative_swatch": False,
        "physical_loading_verified": True,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "verification_note": note,
    }


def bind_slot(slot: int, spool_id: int, *, client: Client = spoolman, mr: Client = moonraker,
              state_path: Path | None = None, pending_path: Path | None = None,
              prior_disposition: str = "shelf", note: str = "Bound from Discord /spool",
              push_screen_update: bool = True) -> dict[str, Any]:
    """Make `spool_id` the spool in `slot`, everywhere, with Spoolman winning.

    prior_disposition: 'shelf' puts the replaced spool on the shelf; 'keep' leaves
    its Spoolman record alone (the caller already handled it, e.g. depleted).
    """
    slot = int(slot)
    if slot not in SLOTS:
        raise SpoolError(f"slot {slot} is not 1-4")
    spool = client("GET", f"/api/v1/spool/{int(spool_id)}", None)
    if not isinstance(spool, dict) or spool.get("id") is None:
        raise SpoolError(f"Spoolman has no spool #{spool_id}")
    if spool.get("archived"):
        raise SpoolError(f"spool #{spool_id} is archived (used up); pick a live one")
    state = load_state(state_path)
    slots = state.setdefault("ifs_slots", {})
    for key, rec in slots.items():
        if str(key) != str(slot) and (rec or {}).get("spoolman_id") == int(spool_id):
            raise SpoolError(f"spool #{spool_id} is already mapped to slot {key}. Move that slot first. Nothing changed")
    old = slots.get(str(slot)) or {}
    prior = old.get("spoolman_id")
    client("PATCH", f"/api/v1/spool/{int(spool_id)}", {"location": f"IFS Slot {slot}"})
    if prior and int(prior) != int(spool_id) and prior_disposition == "shelf":
        prior_rec = client("GET", f"/api/v1/spool/{int(prior)}", None)
        if isinstance(prior_rec, dict) and not prior_rec.get("archived") and \
                str(prior_rec.get("location") or "") in ("", f"IFS Slot {slot}"):
            client("PATCH", f"/api/v1/spool/{int(prior)}", {"location": SHELF})
    record = _slot_record(slot, spool, old, note)
    slots[str(slot)] = record
    if (state.get("spool") or {}).get("spoolman_id") == prior and prior is not None:
        # The live hardware check compares this name with Spoolman: carry the new spool's facts,
        # not just its id, or a swapped spool reads as "Spoolman #7 is 'Coffee PLA+', state says 'Pink PLA'".
        filament = spool.get("filament") or {}
        old_spool = state["spool"]
        state["spool"] = {**old_spool, "spoolman_id": int(spool_id),
                          "name": filament.get("name") or old_spool.get("name"),
                          "material": filament.get("material") or old_spool.get("material"),
                          "density": filament.get("density") or old_spool.get("density"),
                          "diameter_mm": filament.get("diameter") or old_spool.get("diameter_mm")}
    save_state(state, state_path)
    usage = "unchanged"
    try:
        if prior is not None and active_usage_spool(mr) == prior and int(prior) != int(spool_id):
            resume_usage(int(spool_id), mr)
            usage = f"now charged to #{spool_id}"
    except Exception as exc:
        usage = f"NOT updated ({exc})"
    if push_screen_update:
        try:
            screen = push_screen(slot, record["material"], record["hex"], mr=mr, pending_path=pending_path)
        except Exception as exc:
            screen = f"not updated ({exc})"
    else:
        screen = "not requested"
    return {"slot": slot, "spool_id": int(spool_id), "prior_spool_id": prior, "record": record,
            "screen": screen, "usage": usage}


def bind_text(result: dict[str, Any]) -> str:
    r = result["record"]
    grams = f", {r['remaining_grams']:g} g left" if r.get("remaining_grams") is not None else ""
    prior = result.get("prior_spool_id")
    moved = (f" Spool #{prior} went back to the shelf." if prior and prior != result["spool_id"] else "")
    screen = {"pushed": "Printer screen updated.",
              "deferred": "Printer screen will update when this print ends."}.get(result["screen"],
                                                                                   f"Printer screen {result['screen']}.")
    usage = "" if result["usage"] == "unchanged" else f" Filament usage {result['usage']}."
    return f"Slot {result['slot']} → spool #{result['spool_id']} ({r['name']}{grams}).{moved} {screen}{usage}"


def sync_all_screens(*, mr: Client = moonraker, state_path: Path | None = None,
                     pending_path: Path | None = None) -> list[str]:
    state = load_state(state_path)
    out = []
    for slot in SLOTS:
        rec = (state.get("ifs_slots") or {}).get(str(slot)) or {}
        if not rec.get("spoolman_id"):
            out.append(f"Slot {slot}: no spool mapped, screen left alone")
            continue
        try:
            out.append(f"Slot {slot}: {push_screen(slot, rec.get('material') or '', rec.get('hex') or '', mr=mr, pending_path=pending_path)}")
        except Exception as exc:
            out.append(f"Slot {slot}: {exc}")
    return out


# ---------------------------------------------------------------- inventory

def list_text(*, client: Client = spoolman, state_path: Path | None = None) -> str:
    state = load_state(state_path)
    spools = client("GET", "/api/v1/spool?allow_archived=false", None) or []
    by_id = {s.get("id"): s for s in spools if isinstance(s, dict)}
    lines = ["**Loaded**"]
    loaded = set()
    for slot in SLOTS:
        rec = (state.get("ifs_slots") or {}).get(str(slot)) or {}
        sid = rec.get("spoolman_id")
        live = by_id.get(sid) or {}
        grams = live.get("remaining_weight")
        g = f", {grams:.0f} g" if isinstance(grams, (int, float)) else ""
        lines.append(f"Slot {slot}: #{sid} {rec.get('name') or '?'}{g}" if sid else f"Slot {slot}: empty")
        if sid:
            loaded.add(sid)
    shelf = [s for s in spools if s.get("id") not in loaded]
    lines.append("**Shelf**")
    for s in sorted(shelf, key=lambda s: s.get("id") or 0):
        f = s.get("filament") or {}
        grams = s.get("remaining_weight")
        g = f", {grams:.0f} g" if isinstance(grams, (int, float)) else ""
        lines.append(f"#{s['id']} {f.get('name') or '?'} {f.get('material') or ''}{g}".rstrip())
    if not shelf:
        lines.append("(nothing on the shelf)")
    lines.append("Change: `/spool change <slot> <spool#>` · New: `/spool new brand, material, color, grams[, hex]`")
    return "\n".join(lines)


def parse_new(text: str) -> dict[str, Any]:
    parts = [p.strip() for p in str(text or "").split(",")]
    if len(parts) < 4:
        raise SpoolError("format: /spool new brand, material, color, grams[, hex]  e.g. Sunlu, PLA+, Matte White, 1000, FFFFFF")
    brand, material, color, grams = parts[:4]
    try:
        g = float(re.sub(r"[^0-9.]", "", grams))
    except ValueError:
        g = 0
    if not material or not color or g <= 0:
        raise SpoolError("material, color, and a positive full starting weight in grams are required")
    hx = screen_hex(parts[4]) if len(parts) > 4 else None
    if len(parts) > 4 and parts[4] and hx is None:
        raise SpoolError(f"{parts[4]!r} is not a 6-digit hex color")
    return {"brand": brand or None, "material": material, "color": color, "grams": round(g, 1), "hex": hx}


def create_spool(spec: dict[str, Any], *, client: Client = spoolman) -> dict[str, Any]:
    """Create a spool on the shelf, reusing a matching filament type when one exists."""
    filaments = client("GET", "/api/v1/filament", None) or []
    match = None
    reused = True
    for f in filaments:
        if (str(f.get("material") or "").casefold() == spec["material"].casefold()
                and str(f.get("name") or "").casefold() == spec["color"].casefold()
                and str((f.get("vendor") or {}).get("name") or "").casefold() == str(spec.get("brand") or "").casefold()):
            match = f
            break
    if match is None:
        reused = False
        body = {"name": spec["color"], "material": spec["material"], "diameter": 1.75,
                "density": 1.24, "weight": spec["grams"]}
        if spec.get("hex"):
            body["color_hex"] = spec["hex"]
        if spec.get("brand"):
            vendors = client("GET", "/api/v1/vendor", None) or []
            vendor = next((v for v in vendors if str(v.get("name") or "").casefold() == spec["brand"].casefold()), None)
            if vendor is None:
                vendor = client("POST", "/api/v1/vendor", {"name": spec["brand"]})
            body["vendor_id"] = vendor["id"]
        match = client("POST", "/api/v1/filament", body)
    created = client("POST", "/api/v1/spool", {
        "filament_id": match["id"], "initial_weight": spec["grams"], "remaining_weight": spec["grams"],
        "location": SHELF, "lot_nr": spec.get("lot"), "comment": "added from Discord /spool new",
    })
    return {"spool_id": created["id"], "filament_id": match["id"], "reused_filament": reused}
