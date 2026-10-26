# OctoPrint and Marlin support

Print Buddy supports Marlin printers through OctoPrint. Select the `octoprint.marlin` printer model in the existing printer configuration and set `services.octoprint_url` to the OctoPrint server URL. Configure the OctoPrint API key using the existing secret/configuration mechanism; do not place credentials in shared configuration or logs.

The adapter reads OctoPrint printer and job status, checks that the printer is operational and not busy before submission, uploads G-code, and starts it through OctoPrint. Marlin heat commands are sent before file start. The G-code must contain slicer-generated bed and nozzle heating commands and slicer-owned shutdown commands (`M104 S0` and `M140 S0`). Print Buddy does not append end G-code.

Marlin support is via OctoPrint, not a direct serial or standalone Marlin transport. Klipper/ZMod and Flashforge continue to use their existing adapters. Operations not supported by OctoPrint, including Moonraker object queries and Klipper mesh preflight, are not assumed available. No physical printer test is part of this integration; automated tests mock the OctoPrint API.

## Completion posts and timelapse

There is no OctoPrint listener, so a print Print Buddy launches is followed by a launched-print monitor (the same pattern as the Bambu and stock Flashforge families). When the print ends, the monitor makes the completion post. If OctoPrint's own timelapse feature is enabled and it rendered a movie for the job, the monitor downloads that movie, sizes it to the chat platform's upload limit, and attaches it to the completion post. A rendered movie that cannot be downloaded or sized is explained in the completion post itself; if OctoPrint lists no movie for the job, the completion posts as plain text and the reason is in the log. The monitor runs inside the process that launched the print and is not restarted if that process restarts mid-print; prints started outside Print Buddy are not monitored.
