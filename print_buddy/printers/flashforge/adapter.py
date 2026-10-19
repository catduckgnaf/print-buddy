"""Flashforge AD5X on ZMod: wraps the ZMod/IFS code paths (printers.flashforge.zmod)."""
import re

from ..base import PrinterAdapter, basic_status


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
