# Print Buddy YAML Configuration

`config/home.yaml` is the checked-in default config. Override it on one installation with the gitignored `config/local.yaml`, or select a single YAML or legacy TOML file with `PRINT_BUDDY_CONFIG=/path/to/settings.yaml`. Use YAML for new configurations. Existing `config/home.toml` and `config/local.toml` remain supported during migration: `home.yaml` wins when both default files exist, and `local.yaml` wins over `local.toml`. An explicitly selected `PRINT_BUDDY_CONFIG` file replaces automatic local-file selection; it does not layer both local files.

Settings are merged key by key in this order: printer model defaults, home configuration, selected local configuration, then environment overrides (`PRINT_BUDDY__SECTION__KEY` or supported legacy environment names). Existing explicit runtime arguments and persisted job state continue to take precedence at their call sites. Settings are loaded once per process, so restart the relevant process after changing configuration. YAML does not support secrets: keep credentials in existing environment or secret files. Runtime state remains in the existing state files, never YAML.

The checked-in `config/home.yaml`, the README's [All settings table](../README.md#all-settings), and the selected printer model's defaults form the supported settings inventory. Model IDs are `flashforge.ad5x`, `sovol.sv06` and `klipper.generic`. Optional `printer.nozzle_type` values are limited to the selected model's supported set: `brass`, `hardened_steel`, `stainless_steel`, `ruby`, `tungsten_carbide` or `diamond`. `nozzle_temp_offsets` accepts those known names with values from −10 to +15 °C. `visual_watch.sensitivity` is an integer from 1 to 5; `visual_watch.enabled` is a YAML boolean and defaults to `true` in `home.yaml`, preserving the behavior of existing TOML configurations, which had no toggle and always ran camera checks.

Types, supported ranges, printer capabilities, nozzle limits and operational guards are validated before use. Unknown keys in local overrides fail with an error that names the section and key. Safety invariants are not configuration settings: model-supported nozzle/slot limits, protected G-code checks, slice validation, and operator confirmations remain enforced by code and cannot be disabled or relaxed through YAML. Monitoring stays enabled by default for backward compatibility and can be explicitly disabled; changing settings does not start a print or contact a printer during configuration validation.

Example:

```yaml
printer:
  model: flashforge.ad5x
visual_watch:
  enabled: true
  sensitivity: 3
```

During migration, convert a TOML document by preserving its section names and keys as YAML mappings, then set `PRINT_BUDDY_CONFIG` to that YAML file or use `config/local.yaml`. Compare the effective values before removing the old TOML file. Do not copy secrets into either file.
