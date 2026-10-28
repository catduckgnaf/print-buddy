# Print Failure Triage and Reslicing

Depth for the differential-diagnosis workflow in SKILL.md. Use when a user reports a printer "not working" and the failure is print-quality or adhesion rather than a serial/firmware fault.

## Deriving a new profile from a known-good G-code file

Do not hand-write a slicer config for a printer you have no saved profile for. PrusaSlicer embeds its complete configuration in every G-code file it produces, so a file that **printed successfully on this machine** is an authoritative, already-validated baseline. Extract it and modify only the parameters your diagnosis implicates.

```bash
# 1. Extract the embedded config from a file known to have printed successfully
grep -a "^; prusaslicer_config = begin" -A100000 working_ref.gcode \
  | grep -a "^; " | sed 's/^; //' | grep -v "prusaslicer_config" > baseline.ini
wc -l baseline.ini   # expect a few hundred lines; a near-empty file means the marker was missing

# 2. Copy and mutate. set_kv edits in place, appends only if the key is absent,
#    so a typo cannot silently become a no-op you never notice.
cp baseline.ini tuned.ini
set_kv() {
  grep -q "^$1 = " tuned.ini && sed -i "s|^$1 = .*|$1 = $2|" tuned.ini || echo "$1 = $2" >> tuned.ini
}
set_kv first_layer_temperature 220
set_kv brim_width 6
# ... etc

# 3. Echo the changed keys back before slicing. Never slice from an unverified ini.
grep -E "^(first_layer_temperature|temperature|brim_width|retract_lift|first_layer_speed) = " tuned.ini

# 4. Slice, then verify the output actually contains what you asked for
prusa-slicer --load tuned.ini --export-gcode --output out.gcode model.stl
grep -oa "^;TYPE:.*" out.gcode | sort -u          # confirm Skirt/Brim present
grep -a "estimated printing time" out.gcode
```

**Verify the sliced output, not just the ini.** Grepping the G-code body for `TYPE:Brim` returns zero even when a brim exists, because PrusaSlicer emits brim extrusions under the shared `;TYPE:Skirt/Brim` marker. Check the distinct `;TYPE:` set and the extrusion-line count within that block against the known-good reference instead of grepping for a literal `Brim` token and concluding the setting did not apply.

**Klipper mesh verification:** Ensure the current start G-code loads the intended profile with `BED_MESH_PROFILE LOAD=default` when that is not already handled by an installed start macro. Validate the selected G-code with `python3 -m print_handy.core.model_job verify-gcode`; do not insert Marlin `M420` or `M851` commands into a Klipper job.

## Mid-air extrusion curling vs. nozzle tightness

Nozzle tightness inside the heater block determines thread sealing against the heatbreak; it has zero physical effect on the internal bore geometry or extrusion path.

When filament curls violently upward or loops in circles immediately upon exiting the nozzle into open air (before touching the bed):
1. **Asymmetrical orifice drag:** A 0.4mm nozzle depends on uniform fluid friction across the entire circular perimeter. If a microscopic speck of carbonized plastic, dust, or a brass burr clings to one internal edge of the hole, plastic passing that edge moves slower than plastic on the opposite unobstructed side. The resulting velocity differential bends the molten strand directly toward the obstructed edge.
2. **Exterior nozzle wetting:** Molten silk/specialty PLA has high surface tension. If the flat annular face or outer cone of the brass nozzle is coated in burnt, sticky residue, the emerging plastic wets and adheres to the dirty brass surface rather than releasing cleanly, pulling the extrudate upward into a curl.

**Resolution:**
- Heat the hotend to 190°C–200°C.
- Push a 0.4mm acupuncture needle straight up into the orifice from below. Gently stroke vertically to break up internal char.
- Wipe the nozzle tip and exterior flats clean with a brass wire brush or folded paper towel.
- Purge 20mm of filament in free air (`G1 E20 F120`) and confirm the strand drops straight down as a vertical plumb line before starting a print.

## Nozzle replacement and Z-probe offset safety gate

Every replacement nozzle has manufacturing dimensional variations. Even 0.05mm to 0.10mm variation changes the nozzle tip height relative to the inductive probe:
- **Hot-tightening requirement:** Always perform the final torque on the nozzle at 240°C–250°C while firmly bracing the heater block with pliers. Aluminum expands faster than brass when heated; cold-tightened nozzles develop a gap at operating temperatures, leaking plastic backward through the threads.
- **Klipper Z-offset reset:** Never start a print job using an assumed offset immediately following a nozzle swap. Mark the stored hardware state unverified with `python3 -m print_handy.core.printer_state set --nozzle <diameter> --nozzle-type <type>`, then run the heated `PROBE_CALIBRATE` paper-test workflow. Finish with `ACCEPT`, `SAVE_CONFIG`, and `python3 -m print_handy.core.printer_state set --sync-z`; do not use Marlin `M851` or `M500`.

## Source-model recovery

When reslicing, look for the original `.stl`/`.scad`/`.3mf` before assuming you must regenerate geometry. Search the configured archive, local workspace, and Hermes scratch directory for the model stem and for `*.stl` / `*.3mf` before rebuilding from OpenSCAD. Moonraker's `gcodes` root contains printable G-code, not an authoritative source-model archive.

## Silk / specialty PLA reslice profile (Klipper 3D Printer)

Silk PLA contains additives that lower surface energy: it adheres worse than plain PLA and wants more heat. Deltas from a working plain-PLA Klipper 3D Printer profile:

| key | plain PLA | silk PLA | why |
|---|---|---|---|
| `first_layer_temperature` | 205 | 220 | additives need more heat to wet the sheet |
| `temperature` | 205 | 215 | |
| `first_layer_bed_temperature` | 60 | 62 | |
| `brim_width` / `brim_type` | 0-4 | 6 / `outer_only` | secondary insurance on a low-surface-energy material |
| `first_layer_speed` | 20-30 | 15 | dwell time to bond |
| `external_perimeter_speed` | 45 | 25 | |
| `travel_speed` | 100-130 | 100 | reduces shear energy on any collision |
| `retract_lift` | 0 | 0.4 | clears curled ridges; silk die-swells badly |
| `disable_fan_first_layers` | 1 | 3 | cooling the first layers is what breaks the bond |

This table addresses **adhesion** only. It gets a flat part to stick and print a real first layer; it does not stop a corner from lifting twenty minutes in.

## Warping profile (broad flat part that stuck, then lifted a corner)

When the adhesion profile above produces a good first layer and the part still peels at an edge well into the print, the mechanism is thermal contraction, not bond strength. Escalate these keys on top of the silk profile:

| key | adhesion profile | warping profile | why |
|---|---|---|---|
| `bed_temperature` | falls to 60 after layer 1 | **68, same as first layer** | a bed that cools mid-print lets the base contract; hold it hot for the whole job |
| `first_layer_bed_temperature` | 62 | 68 | |
| `max_fan_speed` | 100 | **45** | part cooling is the direct driver of layer-to-layer contraction stress on flat parts |
| `min_fan_speed` | 35 | 25 | |
| `disable_fan_first_layers` | 3 | 5 | |
| `full_fan_speed_layer` | 0 | 8 | ramp cooling in instead of slamming it on |
| `brim_width` | 6 | 12 | more anchor to resist the peeling moment |
| `first_layer_extrusion_width` | 0.45 | 0.5 | more material in contact with the sheet |

Broad thin nameplates and tags are among the worst geometries for warping despite looking trivial: large flat area, low height, so contraction stress concentrates entirely at the perimeter with no vertical mass to resist it. Say so when the user assumes a simple-looking part should be easy.

## Monitoring a long print

Do not blind-poll a 30-plus minute print in a single foreground shell loop; long `sleep`-based watch loops hit the tool's foreground execution ceiling and die mid-print, losing the watch exactly when it matters. Use the existing completion watcher, or poll Moonraker's native `/printer/objects/query?print_stats&virtual_sdcard` endpoint in short bounded batches. Preserve the active filename across the `printing` to `complete` transition, and inspect `/server/gcode_store` for errors between batches. Printer state cannot see adhesion, so the user's eyes remain the sensor; ask what the print is doing rather than inferring physical success from percentages.

## Handoff instructions for physical steps

After uploading the reslice, give the user an ordered physical checklist and start the hotend heating in the same turn so the wait overlaps with reading. Order matters:

1. Heat nozzle to printing temp, then remove any blob with pliers. Never cold.
2. Unload old filament, load new.
3. Purge until the color runs clean — silk pigment streaks badly through residue of the previous color.
4. Wash the PEI sheet with dish soap and hot water, then dry it. For silk and other low-surface-energy filaments do this instead of isopropyl, not after it: IPA redistributes some oils across the sheet rather than removing them, and silk PLA has no margin for a contaminated plate. Plain PLA tolerates an IPA wipe.
5. Check for airflow across the machine — a vent, fan, or open window will lift a corner on a flat part regardless of profile.
6. Start the job and watch the first layer.

Upload with `select=false` and `print=false` when physical prep is required, so a remote start cannot fire before the user has touched the machine.
