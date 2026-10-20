# Home Assistant Panic & Printer Controls

This guide provides direct, no-LLM printer controls for the FlashForge AD5X running ZMod Klipper from a Home Assistant dashboard without running an extra long-running daemon.

> **Network Path Notice:**
> Home Assistant's network path to the printer Moonraker endpoint at `192.168.45.50:7125` must be confirmed by the networking and Home Assistant owners before enabling these commands.

---

## 1. Force Restart (Instant Panic Button)

The panic restart ladder performs an immediate emergency stop (M112) followed by a Klipper firmware restart.

### Home Assistant `rest_command` Configuration

Add the following to your `configuration.yaml` (or `rest_commands.yaml`):

```yaml
rest_command:
  printer_emergency_stop:
    url: "http://192.168.45.50:7125/printer/emergency_stop"
    method: POST
    timeout: 10

  printer_firmware_restart:
    url: "http://192.168.45.50:7125/printer/firmware_restart"
    method: POST
    timeout: 15
```

### Home Assistant Script

Create a script to run the ladder in order (e.g. in `scripts.yaml`):

```yaml
script:
  printer_force_restart:
    alias: "Printer Force Restart"
    icon: "mdi:restart-alert"
    sequence:
      - action: rest_command.printer_emergency_stop
      - delay:
          seconds: 2
      - action: rest_command.printer_firmware_restart
```

---

## 2. Guarded Purge

Purging extrudes filament already loaded into the toolhead.

### Why Purge Must Call the CLI

Guarded purge requires several critical safety checks:
1. **Concurrency Lock:** Acquiring Print Buddy's `_CONTROL_LOCK` to ensure no conflicting print or maintenance operations run simultaneously.
2. **State Gate:** Verifying printer state is safe (`standby`, `complete`, `cancelled`, or `error`) and Klipper is `ready` (refusing while printing or paused).
3. **Head Sensor Check:** Verifying `filament_switch_sensor head_switch_sensor` reports `filament_detected == True`.
4. **Thermal Safety:** Clamping extrusion volume (<= 150 mm) and temperature (180–260°C), feeding in 10 mm increments, and **guaranteeing heater target reset to 0 in a finally block** with post-run readback confirmation.

Because Home Assistant `rest_command` alone cannot atomically acquire the Python process lock or guarantee post-failure exception recovery, **guarded purge should be invoked through the CLI wrapper**:

```yaml
shell_command:
  printer_purge: "/home/dysprosium/print-buddy/bin/pb-purge --mm 60 --temp 210"
```

### Direct Moonraker Script (Alternative)

If Home Assistant cannot access the CLI and must call Moonraker directly via REST, you can expose `/printer/gcode/script` with the self-resetting G-code sequence:

```yaml
rest_command:
  printer_purge_unlocked:
    url: "http://192.168.45.50:7125/printer/gcode/script"
    method: POST
    content_type: "application/json"
    payload: >-
      {"script": "M104 S210\nTEMPERATURE_WAIT SENSOR=extruder MINIMUM=205\nM83\nG1 E10 F150\nG1 E10 F150\nG1 E10 F150\nG1 E10 F150\nG1 E10 F150\nG1 E10 F150\nM104 S0"}
```

*Note: The direct Moonraker script bypasses Print Buddy's `_CONTROL_LOCK` and the physical head sensor check. Use the CLI wrapper whenever possible.*

---

## 3. Printer Status

For reading state, klippy status, temperatures, and head sensor in Home Assistant, you can query Moonraker objects via a REST sensor in `configuration.yaml`:

```yaml
sensor:
  - platform: rest
    name: "Printer Objects"
    resource: "http://192.168.45.50:7125/printer/objects/query?print_stats&webhooks&extruder&heater_bed&filament_switch_sensor%20head_switch_sensor"
    method: GET
    scan_interval: 10
    value_template: "{{ value_json.result.status.webhooks.state | default('unknown') }}"
    json_attributes_path: "$.result.status"
    json_attributes:
      - print_stats
      - webhooks
      - extruder
      - heater_bed
      - "filament_switch_sensor head_switch_sensor"
```
