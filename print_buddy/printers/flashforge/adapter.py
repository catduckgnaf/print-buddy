"""Flashforge on ZMod: the AD5X adapter wraps the ZMod/IFS code paths
(printers.flashforge.zmod); the single-extruder adapter below shares only the
ZMod start code and Moonraker transport, with every IFS behaviour off."""
import re

from ..base import MultiColorUnsupported, PrinterAdapter, basic_status


class ZmodAdapter(PrinterAdapter):
    multi_slot = True
    has_native_screen = True

    @property
    def slot_count(self):
        return int(self.config["printer"]["ifs_slots"])

    @property
    def native(self):
        from . import zmod
        return zmod

    def machine_start_gcode(self, template_start, mesh="auto"):
        # Exactly what orca_adapter built inline before the adapter existed.
        start = re.sub(r"\bMESH=\S+", "MESH=" + mesh, template_start)
        return ("M190 S[bed_temperature_initial_layer_single]\n"
                "M104 S[nozzle_temperature_initial_layer] T0\n" + start)

    def machine_end_gcode(self, template_end):
        return template_end

    def start_plan(self, bed_temp, nozzle_temp, *, mesh="auto"):
        return [f"M190 S{bed_temp:g}", f"M104 S{nozzle_temp:g} T0",
                f"START_PRINT BED_TEMP={bed_temp:g} EXTRUDER_TEMP={nozzle_temp:g} MESH={mesh}"]

    def moonraker_start_commands(self, remote_filename):
        return [{"method": "POST", "path": "/printer/print/start", "body": {"filename": remote_filename}}]

    def normalize_tool_mapping(self, mapping, state):
        return self.native.normalize_mapping(mapping, state)

    def readiness_problems(self, state, status, selection=None, **kw):
        from ...core import model_job
        return list(model_job.check_filament_readiness(state, status, selection, **kw))

    def screen_command(self, slot, material, hex_code):
        return self.native.screen.screen_command(slot, material, hex_code)

    def stock_api_url(self, host):
        return f"http://{host}:{self.config['services']['stock_api_port']}/detail"

    def moonraker_objects(self):
        return ["webhooks", "print_stats", "virtual_sdcard", "extruder", "heater_bed", "zmod_color", "zmod_ifs",
                "save_variables"]

    def normalize_status(self, raw):
        out = basic_status(raw)
        color = (raw or {}).get("zmod_color")
        slots = color.get("slots") if isinstance(color, dict) else None
        out["slots"] = slots if isinstance(slots, list) else []
        return out


class ZmodSingleExtruderAdapter(ZmodAdapter):
    """A ZMod printer with one extruder and no IFS (AD5M, AD5M Pro).

    Inherits the ZMod start/end G-code, start plan and Moonraker start command
    from ZmodAdapter. Everything IFS is off: one slot, multi-colour refused,
    no native-mode machinery (no zmod_color/zmod_ifs telemetry, no screen
    colour sync, no stock /detail API), and readiness is the plain
    print_stats/webhooks check the stock Klipper adapter uses. The PRINT_BUDDY
    spool-match macro stays AD5X-only; nothing here claims it.
    """

    multi_slot = False
    has_native_screen = False

    @property
    def slot_count(self):
        return 1

    @property
    def native(self):
        raise MultiColorUnsupported(f"{self.label} has no ZMod/native support")

    def normalize_tool_mapping(self, mapping, state):
        tools = {str(k) for k in (mapping or {"0": 1})}
        if tools != {"0"}:
            raise MultiColorUnsupported(
                f"{self.label} has a single extruder; this job uses tools {sorted(tools)}. "
                "Slice it single-color or use a multi-slot printer.")
        return {"0": 1}

    def readiness_problems(self, state, status, selection=None, **kw):
        status = status if isinstance(status, dict) else {}
        problems = []
        pstate = (status.get("print_stats") or {}).get("state")
        if pstate is None:
            problems.append("print_stats state is unavailable")
        elif pstate in ("printing", "paused"):
            problems.append(f"printer is busy ({pstate})")
        webhooks = (status.get("webhooks") or {}).get("state")
        if webhooks not in (None, "ready"):
            problems.append(f"Klipper is not ready ({webhooks})")
        return problems

    def screen_command(self, slot, material, hex_code):
        return None

    def stock_api_url(self, host):
        return None

    def moonraker_objects(self):
        return ["webhooks", "print_stats", "virtual_sdcard", "extruder", "heater_bed"]

    def normalize_status(self, raw):
        return basic_status(raw)
