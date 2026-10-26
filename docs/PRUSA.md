# Prusa printers (PrusaLink LAN; MK4S, CORE One, XL, MINI+)

[Documentation home](README.md) · [Printer profiles](PRINTER-PROFILES.md) · Issue [#242](https://github.com/catduckgnaf/print-buddy/issues/242)

Print Buddy supports Prusa's current Buddy-firmware printers through **PrusaLink**, the HTTP API that runs on the printer itself — no PrusaConnect cloud account, no OctoPrint in between. Nothing here has been tested on a Prusa printer yet: slicing, profile generation and the LAN client are covered by offline tests with fake transports, and live support is explicitly unclaimed until a hardware test exists.

| Model | Key | Bed (mm) | Height | Notes |
|---|---|---|---|---|
| MK4S | `prusa.mk4s` | 250 × 210 | 220 | Single tool |
| CORE One | `prusa.coreone` | 250 × 220 | 270 | Enclosed CoreXY; chamber not driven |
| XL (5-tool) | `prusa.xl` | 360 × 360 | 360 | Five toolheads; Print Buddy slices **single-tool (tool 0) jobs only** |
| MINI+ | `prusa.miniplus` | 180 × 180 | 180 | Runs Orca's MINI profiles (`printer_model` is `Prusa MINI`) |

Select one with `printer.model: prusa.mk4s` (etc.). The MK3.9S/MK3.5S upgrade paths and the CORE One L are follow-up profiles on #242: same vendor and client, added once their Orca identities are pinned.

## Set up the profiles

Print Buddy ships no Prusa slicer profiles (OrcaSlicer's Prusa profiles are AGPL-3.0). Generate them from your own OrcaSlicer 2.4.2 installation:

```bash
python3 scripts/prusa-templates.py --printer mk4s --resources <OrcaSlicer resources folder>
```

The resources folder holds `profiles/Prusa.json` and `profiles/Prusa/`. The command resolves the profiles' `inherits`/`include` chains and refuses unless they hash to the checked identity recorded in `print_buddy/printers/prusa/facts.py` (OrcaSlicer 2.4.2, Prusa vendor profiles `02.04.00.03`), then writes them into `<state>/orca-profiles/prusa_<model>/`, never into the checkout. Prusa's machine profiles store start/end G-code as a list of lines; the generated templates join them into the string form every other vendor uses (the stored upstream copies keep the vendor's form, so the identity check is unaffected). Missing, edited or unrecognised profiles fail closed, exactly as for Bambu Lab.

## PrusaLink (opt-in)

Off by default. To enable status — and, separately, printing — set the printer's address:

```yaml
prusa:
  link_host: 192.168.1.70        # the printer's LAN address (plain host, no scheme or port)
  api_key_env: PRUSA_LINK_API_KEY  # the default; names an environment variable
```

Put the PrusaLink API key (shown on the printer under Settings → Network → PrusaLink) in the environment variable that `api_key_env` names. The key is never a config value and never logged; the log redactor covers `*_KEY` names. The client sends it as the `X-Api-Key` header and answers a Digest challenge as user `maker` with the same key, the two forms PrusaLink accepts.

With the host set, the health check reads one status snapshot (state, job, progress, temperatures). Printing additionally requires opting in, like Bambu Lab:

```yaml
delivery:
  methods: [printer, discord]
```

The print path then runs the usual sequence: readiness from a live snapshot → offline G-code verification (right model, single tool, temperatures within the model's published limits, no foreign start code) → launch lease → bed-clear approval inside the lease → a second snapshot → upload (`PUT /api/v1/files/<storage>/<file>`, USB storage preferred, with the size read back and required to match before anything starts) → start (`POST` on the uploaded file) → confirmation from a fresh snapshot. An unconfirmed start is recorded as uncertain and is never resubmitted. Pause/resume/stop map to `PUT /api/v1/job/<id>/pause`, `PUT .../resume` and `DELETE /api/v1/job/<id>`.

Both `.gcode` and the binary `.bgcode` form are accepted file types; what OrcaSlicer produces here is `.gcode`. `services.moonraker_url` and `services.octoprint_url` must stay empty for a Prusa model; settings refuse to load otherwise.

In the combined Docker container the supervisor honours that (#256): for a Prusa model it does not start the Moonraker listener at all, and the healthcheck does not require one, so the container starts, stays up and reports healthy with just the bot (with a token) and the bundled Spoolman — see [Which processes run](DOCKER.md#which-processes-run).

## What is not supported

- PrusaConnect cloud (any model) — LAN only, the same decision as Bambu Lab in #187.
- Multi-tool / MMU slicing, including on the XL: jobs are single-tool; a `T1`+ tool change in a file is refused by the guard.
- Input Shaper tuning, chamber control, camera streaming, firmware updates.
- Any claim of a successful print on real hardware.
