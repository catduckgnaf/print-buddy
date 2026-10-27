# AI design with OpenSCAD (`/print-design`, #388)

Describe a part in Discord and Print Buddy designs it for you: a model writes
OpenSCAD, Print Buddy renders it with the OpenSCAD binary already in the
install, measures the result, and shows you a preview with the real
dimensions. You then choose:

- **Slice it** — the STL goes through the normal prepared intake (filament,
  fit, slicing and the usual print confirmation). Design never slices or
  prints anything itself, and nothing reaches the printer without the same
  approvals as a model link.
- **Change it** — your next message in the chat is the change ("make the
  holes 5 mm", "add a lip around the edge"); the design is edited and
  re-rendered. Up to 10 turns per design.
- **Cancel** — the design session ends.

## Turning it on

Design is off by default. Set `[design] enabled = true` (or
`PRINT_BUDDY__DESIGN__ENABLED=true`), then a model:

- **Standalone bot:** the `[design]` settings pick the model. Leave
  `chat_url` / `model` / `api_key_env` empty to reuse the `[llm]` endpoint,
  or point them at a stronger model — design turns are the ones worth
  spending a bigger model on, while everyday chat stays on the small one.
- **Hermes:** the design model is the profile's auxiliary task, not a
  Print Buddy setting. Uncomment the `auxiliary.print_design` block in the
  profile config (the shipped template carries a commented example) to pin
  a provider/model for design; chat stays on the profile model. The
  `[design]` fields are ignored in Hermes mode unless the auxiliary task
  is unavailable, in which case the HTTP settings above are the fallback.

`bot check` prints a `design` row saying which of these is in effect.

Standalone installs outside the container need the `openscad` binary on the
machine (the container image includes it); with design enabled and no
`openscad` on PATH, `bot check` fails that row and design turns report it.

## The sandbox, in plain language

The model writes the part, but it never gets to run anything general:

- The generated file may not use `import`, `include`, `use` or `surface` —
  the statements that could read files off the machine. A file containing
  one is refused before OpenSCAD ever runs.
- Rendering runs with `--hardwarnings` (any warning is a failure, so a
  design that silently lost a piece cannot slip through), in the design's
  own folder, with a near-empty environment, a CPU/memory limit and a
  wall-clock timeout (`[design] timeout_s`, 180 s by default).
- If OpenSCAD rejects the file, the exact error goes back to the model for
  a repair, up to `[design] repair_attempts` times (3 by default). If it
  still fails, the turn says so and shows the last error — nothing is
  handed to intake.

## Honest limits

- Each turn is a real model call plus a real render: expect seconds to a
  couple of minutes per turn, and model cost per turn. Sessions are kept
  under the cache directory (`design-sessions/`) for 14 days.
- The preview and measurements are of the rendered STL: dimensions, volume,
  shell count and whether the mesh is watertight and manifold. A design
  that renders to nothing is rejected, not posted.
- Stage 1 creates designs from text. Editing a file you drop, or "design
  this" without the command, comes later (#388).
