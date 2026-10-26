# More than one printer: run one Print Buddy instance per printer

[Documentation home](README.md) · [Docker](DOCKER.md) · Issue [#257](https://github.com/catduckgnaf/print-buddy/issues/257)

Print Buddy is **one printer per instance** today: `[printer] model` is singular, and the
hardware record, launch lease, job state, listener and approval flow all assume exactly one
machine. True multi-printer support in a single instance is Stage 2 of
[#257](https://github.com/catduckgnaf/print-buddy/issues/257) and is not implemented.

The supported pattern for a mixed household — a Bambu Lab next to a Klipper machine, say —
is **one instance per printer**. This page is that recipe (Stage 0 of #257). Each instance is
an ordinary single-printer install; what matters is what must be kept separate, and the one
thing that is designed to be shared: Spoolman.

## The two rules

1. **Never share a state directory.** An instance's data directory holds its printer's
   hardware record, launch-lease database, print claims and job archives. Two instances on
   one directory can approve, lease and record against the wrong printer.
2. **Never share an approval channel.** Prompts and print approvals are scoped to the
   configured chat. Two instances watching one channel can answer each other's prompts and
   approve each other's prints.

Everything below follows from those two rules.

## What each instance gets of its own

| Per instance | Docker (Compose) | Native install |
| --- | --- | --- |
| Project / container name | A distinct Compose project (`-p print-buddy-a1`, `-p print-buddy-ad5x`, or `COMPOSE_PROJECT_NAME` in each stack's `.env`) | A distinct systemd service name per instance |
| Configuration | Its own `.env` and its own config file (`PRINT_BUDDY_CONFIG`, or a mounted override) | Its own `PRINT_BUDDY_CONFIG` file |
| Data / state | Its own `PRINT_BUDDY_DATA` directory (the `hermes`, `archive`, `records` and `cache` volumes live under it) | Its own `[paths]` state, archive and cache directories |
| Printer identity | Its own `[printer] model` **and** `[printer] name` (for example `Garage A1`) — the name is what messages use, so approvals say which printer they mean | Same |
| Printer connection | Its own LAN host settings (`[bambu] lan_host`, `[prusa] link_host`, `services.moonraker_url`, …) and camera URL | Same |
| Chat | Its own Discord channel **and** approval user (below) — or its own Telegram chat / Matrix room | Same |
| Spoolman data | Shared — see the next section. Only one instance (or none) runs a bundled Spoolman against the shared inventory | Same |

The default Compose stack publishes no host ports, so two stacks do not collide. If you
publish a port yourself (for a shared Spoolman, below), each published port belongs to
exactly one instance.

### Chat separation

Use a **separate Discord bot (token) per printer** where you can — it is the cleanest form
of rule 2. The minimum is a separate channel **and** a separate approval user per instance,
because prompts, approvals and "send the files here" delivery are all scoped to the
configured channel and approval user. The same applies per platform: a separate Telegram
chat or Matrix room per instance, never one chat watched by two instances.

## Sharing Spoolman (the one shared piece)

Spoolman is the natural single inventory for the whole household: one list of spools, seen
by every instance. Run **one** Spoolman for all instances and point every instance at it:

**Option A — a standalone Spoolman (recommended).** Run Spoolman as its own container or
service (its usual port is 7912). In every Print Buddy instance set:

```bash
PRINT_BUDDY_BUNDLED_SPOOLMAN=false
PRINT_BUDDY__SERVICES__SPOOLMAN_URL=http://<spoolman-host>:7912
```

With the bundled Spoolman disabled, the container supervisor refuses to start unless the
configured Spoolman URL is external (not loopback) — a loopback URL there is a
configuration error, not a fallback.

**Option B — share one instance's bundled Spoolman.** Keep the bundled Spoolman enabled in
one instance and set `SPOOLMAN_HOST=0.0.0.0` there, publishing its port 8000, then point the
other instances at `http://<that-host>:8000` with their own bundled Spoolman disabled, as
in Option A. The bundled Spoolman binds loopback by default on purpose: Spoolman has no
authentication, so publishing it is a deliberate exposure — do it only on a trusted LAN,
exactly as for the SDCP warning in [the Elegoo guide](ELEGOO.md).

However you share it:

- **One Spoolman data directory, owned by one Spoolman process.** Never point two bundled
  Spoolmans at the same data directory.
- **A spool is loaded on one printer at a time.** Each instance records its own printer's
  loaded spool in its own state. Do not record the same physical spool as loaded on two
  printers; two printers printing concurrently from *different* spools is the normal case
  the shared inventory is for.

## Unraid

Install the template once per printer and rename each container (Unraid container names
must be unique). Give each instance its own appdata path — for example
`/mnt/user/appdata/print-buddy-a1` and `/mnt/user/appdata/print-buddy-ad5x` — for every
path the template maps, and its own channel, printer name and LAN settings in that
instance's variables. The shared-Spoolman settings above go in each template the same way
as in Compose.

## Checking a two-instance setup (offline)

Before starting either bot:

1. Load each instance's configuration the way the instance will (its own
   `PRINT_BUDDY_CONFIG`) and confirm the printer model, printer name, chat id and state
   paths differ between the two and match the printer each is for.
2. Start **one** instance and post a model link in its channel: the preview names that
   instance's printer, and nothing arrives in the other instance's channel.
3. Stop it, start the second instance, and repeat in the second channel.
4. Only then run both together.

Steps 2–3 are the walkthrough that proves rules 1 and 2 for your setup; keep the
single-instance-at-a-time order, because it makes a crossed configuration visible
immediately instead of during a print approval.

## What this does not give you

- One bot serving two printers, cross-printer job routing, or a combined status view —
  that is #257 Stage 2, which starts from a design spike, not from this recipe.
- Shared job history or records: each instance keeps its own archive and records, by
  design (rule 1).
- Any change to print safety: every instance keeps its own confirmation, readiness,
  lease and bed-clear gates for its own printer, unchanged.
