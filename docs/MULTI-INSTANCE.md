# More than one printer: one instance per printer (the isolation alternative)

[Documentation home](README.md) · [Docker](DOCKER.md) · Issue [#257](https://github.com/catduckgnaf/print-buddy/issues/257)

Since Stage 2 of [#257](https://github.com/catduckgnaf/print-buddy/issues/257) shipped, **one
Print Buddy instance serves a whole roster of printers**: a `[[printers]]` list in the config
file, channel-per-printer routing, per-printer state and leases, and one listener per
Moonraker printer — see [SETTINGS.md — Printers list](SETTINGS.md#printers-list) and the
[Multi-printer design](MULTI-PRINTER-DESIGN.md). For most households that is the answer, and
it is the only setup this page is *not* about.

This page is the alternative that remains: **one instance per printer**, for households
that want hard process isolation between printers — separate processes, separate data
directories, separately revocable bot tokens, and a failure in one instance that cannot
touch another. Each instance is an ordinary single-printer install; what matters is what
must be kept separate, and the one thing that is designed to be shared: Spoolman.

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

**One Discord bot token may serve every instance.** That is safe because of how the bot
scopes itself, not because of the token: the bot core drops every message and every button
press whose channel is not its configured `discord.chat_id`, and within that channel it
acts for everyone in the channel by default, or only for users in its own
`discord.allowed_user_ids` when a whitelist is set. Two instances logged in as the
same bot therefore cannot see, answer or approve anything in each other's channels — each
one only ever reads its own. (Both instances register the same slash commands at start-up,
which is harmless: the command set is identical.) The hard minimum per instance is a
separate channel **and** a separate approval user, because prompts, approvals and "send
the files here" delivery are all scoped to the configured channel and approval user.

The scoping is per channel, so the inverse is the hazard: **never let two instances serve
the same channel on one token.** Both receive every message in that channel and both act —
a leftover instance (an old Hermes profile on another host, a forgotten container) doing
this looks exactly like random bot misbehaviour, including slicing failures from an
outdated code path. The standalone bot logs a warning when Discord hands it a second
READY on a live session, one sign that another process logged in with the same token.

A **separate bot (token) per printer** is still the cleaner form where you can: each
printer gets its own bot name in the member list, and a token can be revoked or rotated
for one printer without touching the others. But it is the channel scoping above, not the
token, that keeps instances apart — never let two instances share a channel, whichever
token arrangement you choose. The same applies per platform: a separate Telegram chat or
Matrix room per instance, never one chat watched by two instances.

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

## A worked example: a Bambu A1 next to a Flashforge AD5X

The motivating mixed household, end to end — the same pair the roster shape serves in
[the design walkthrough](MULTI-PRINTER-DESIGN.md), here as two instances. Two Compose
stacks from this repository's Compose file, one standalone Spoolman (Option A above),
one Discord server:

| | Instance A | Instance B |
| --- | --- | --- |
| Compose project | `print-buddy-a1` | `print-buddy-ad5x` |
| Printer | `bambulab.a1`, name `Garage A1` | `flashforge.ad5x`, name `Workshop AD5X` |
| Connection | `[bambu] lan_host` set; `services.moonraker_url` stays empty | `services.moonraker_url` set to the AD5X |
| Channel | `#a1-prints` | `#ad5x-prints` |
| Data | Its own `PRINT_BUDDY_DATA` (for example `./data-a1`) | Its own `PRINT_BUDDY_DATA` (for example `./data-ad5x`) |
| Spoolman | Bundled disabled; URL = the shared standalone Spoolman | Bundled disabled; URL = the shared standalone Spoolman |
| Container children | The bot only — **no Moonraker listener runs** for a Bambu connection, and the bundled Spoolman is disabled | The Moonraker listener and the bot (bundled Spoolman disabled) |

The last row is the [Which processes run](DOCKER.md#which-processes-run) table applied: the
supervisor starts the listener only where the configured connection is Moonraker (#256),
so instance A has no listener to keep healthy and instance B does — neither needs any
per-instance process tuning. The two instances may use the same Discord bot token (see
Chat separation): an approval tapped in `#a1-prints` can only ever start the A1, because
instance B never reads that channel and instance A only acts there. Filament questions in
either channel resolve against the one shared Spoolman inventory, so a spool moved from
the A1 to the AD5X keeps its identity and remaining weight.

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

- One bot serving two printers or a combined status view — that is exactly what the
  roster in one instance gives you (per-printer listeners, a combined health report and
  the roster on the status page); this recipe trades it for process isolation.
- Cross-printer job routing: deliberately not a feature in either shape. A channel is
  bound to one printer and approvals in a channel can never start another printer.
- Shared job history or records: each instance keeps its own archive and records, by
  design (rule 1). (In the roster shape, history lives side by side under
  `state/printers/<id>/` in the one instance.)
- Any change to print safety: every instance keeps its own confirmation, readiness,
  lease and bed-clear gates for its own printer, unchanged.
