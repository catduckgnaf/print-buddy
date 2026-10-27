# OctoPrint and Marlin support

Print Buddy supports Marlin printers through OctoPrint. Select the `octoprint.marlin` printer model in the existing printer configuration and set `services.octoprint_url` to the OctoPrint server URL. Configure the OctoPrint API key using the existing secret/configuration mechanism; do not place credentials in shared configuration or logs.

The adapter reads OctoPrint printer and job status, checks that the printer is operational and not busy before submission, uploads G-code, and starts it through OctoPrint. Marlin heat commands are sent before file start. The G-code must contain slicer-generated bed and nozzle heating commands and slicer-owned shutdown commands (`M104 S0` and `M140 S0`). Print Buddy does not append end G-code.

Marlin support is via OctoPrint, not a direct serial or standalone Marlin transport. Klipper/ZMod and Flashforge continue to use their existing adapters. Operations not supported by OctoPrint, including Moonraker object queries and Klipper mesh preflight, are not assumed available. No physical printer test is part of this integration; automated tests mock the OctoPrint API.

## Ender presets

`octoprint.marlin` is the generic profile, with placeholder dimensions to override in local config. Four Creality Ender models ship as presets of the same support — same adapter, same OctoPrint route, but the model's real dimensions and templates instead of placeholders:

| Key | Model | Bed (mm) | Height (mm) |
|---|---|---:|---:|
| `octoprint.ender3` | Creality Ender-3 | 220 x 220 | 250 |
| `octoprint.ender3pro` | Creality Ender-3 Pro | 220 x 220 | 250 |
| `octoprint.ender3v2` | Creality Ender-3 V2 | 220 x 220 | 250 |
| `octoprint.ender3v3se` | Creality Ender-3 V3 SE | 220 x 220 | 250 |

Dimensions are the pinned OrcaSlicer profiles' printable area/height (OrcaSlicer v2.5.0-alpha, Creality vendor profiles `02.03.02.87`); the templates are Print Buddy's own Marlin set with those facts substituted — Orca profile content is AGPL-3.0 and is not republished. Upstream ships only a 0.4 mm nozzle machine profile for the Ender-3 V2, so that preset accepts only 0.4 mm. The Ender-3 V3 SE belongs here despite its name: its stock firmware is Marlin-based (the pinned profile declares `gcode_flavor: marlin2`) and it has no Moonraker endpoint — the Klipper Enders (Ender-3 V3, K1 family) are in [Creality printers](CREALITY.md). Select a preset with `PRINT_BUDDY__PRINTER__VENDOR=octoprint` and `PRINT_BUDDY__PRINTER__MODEL=ender3` (etc.).

## Completion posts and timelapse

There is no OctoPrint listener, so a print Print Buddy launches is followed by a launched-print monitor (the same pattern as the Bambu and stock Flashforge families). When the print ends, the monitor makes the completion post. If OctoPrint's own timelapse feature is enabled and it rendered a movie for the job, the monitor downloads that movie, sizes it to the chat platform's upload limit, and attaches it to the completion post. A rendered movie that cannot be downloaded or sized is explained in the completion post itself; if OctoPrint lists no movie for the job, the completion posts as plain text and the reason is in the log. The monitor runs inside the process that launched the print and is not restarted if that process restarts mid-print; prints started outside Print Buddy are not monitored.
