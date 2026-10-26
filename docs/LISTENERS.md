# Listener domains

[Documentation home](README.md) · [Docker](DOCKER.md)

A **listener** watches one printer continuously and reports what happens —
status changes, progress, completion, errors — so the bot can post about a
print without anyone asking. Print Buddy splits listeners by **domain**: the
configured printer's connection / firmware type. The domain selects the
listener *type*; each configured printer gets its own listener *instance*,
supervised and healthchecked independently, so one printer's listener
failing can never take down the bot, Spoolman, or another printer's
listener (#256, #299).

## The registry

`print_buddy/listeners.py` is the single registry: connection → listener
domain. The supervisor's gate (`python3 -m print_buddy.listener_gate`), the
container healthcheck and the registry launcher (`python3 -m
print_buddy.listeners`) all consult it — adding a domain listener means
registering the module and implementing the contract below, with no
supervisor or healthcheck edits.

| Domain (connection) | Listener | Transport |
|---|---|---|
| `moonraker` | implemented: `print_buddy.hermes.moonraker_event_listener` | Moonraker websocket |
| `bambulab_lan` | implemented: `print_buddy.printers.bambulab.listener` | Bambu LAN MQTT, long-lived |
| `prusalink` | planned (#299 Stage C) | PrusaLink HTTP polling |
| `elegoo_sdcp` | planned (#299 Stage C) | Elegoo SDCP websocket |
| `octoprint` | planned (evaluated in Stage C) | OctoPrint HTTP |
| `flashforge_stock` | planned (evaluated in Stage C) | Stock Flashforge LAN |
| `offline` | none, by definition | Print Buddy never contacts the printer |

A domain with no listener yet is a normal state, not an error: the
supervisor starts nothing for it and a configuration with no children at all
idles instead of exiting. A configuration that cannot be resolved at all is
different — the supervisor stops with the settings error rather than
guessing which children to run.

## The normalised contract

Every domain listener reports through the one shape the printer adapters'
`normalize_status` already returns. Consumers — Discord status and
completion posts, the camera watchdog, timelapse (#246) — subscribe to this
shape and never need to know which domain produced it.

**Status fields**

| Field | Meaning |
|---|---|
| `state` | Normalised state string (`printing`, `paused`, `complete`, `error`, `unknown`, …) |
| `filename` | Current job's file name, or `""` |
| `progress` | 0..1, or `None` when the domain cannot know yet |
| `hotend_c`, `bed_c` | Current temperatures, or `None` |
| `hotend_target_c`, `bed_target_c` | Target temperatures when the protocol reports them |
| `remaining_min`, `layer`, `total_layer` | Optional, when the protocol reports them |

A domain may add its own extra fields (for example SDCP's `status_code`);
core consumers read only the fields above. `print_buddy.listeners.validate_status`
pins the core shape in tests.

**Event kinds**

| Kind | Meaning |
|---|---|
| `status` | A fresh status snapshot in the shape above |
| `completion` | A print finished |
| `error` | The printer reports an error. The payload keeps the domain's raw representation alongside the normalised state — for Bambu that includes its HMS entries — so no diagnostic detail is lost in normalisation |
| `snapshot_available` | A camera snapshot can be fetched for this printer now |

**Liveness.** A running listener writes the listener heartbeat
(`listener_health.json`, see `print_buddy.healthcheck`) under its domain's
registered runtime identity. The container healthcheck requires that
heartbeat exactly when the registry says the configured instance's domain
is implemented, and reports "not required for this printer connection"
otherwise.

## The Bambu domain listener (#299 Stage B)

`print_buddy/printers/bambulab/listener.py` holds one Bambu LAN MQTT
session open and merges the printer's delta pushes into a persistent
state, normalising through the Bambu adapter. Its discipline comes from
the #298 audit of Bambuddy (protocol facts only, no code copied):

- `get_version` + `pushall` on every (re)connect, keepalive 30 s — and no
  periodic pushall; the one extra request is at layer 1 when the layer
  total is still unknown.
- Only `push_status` frames (or frames with no `print.command`) are
  telemetry; command acknowledgements never update state.
- 60 s without a message is stale: the session is torn down and rebuilt
  with a fresh MQTT client (hard reset, so a publish queued on the dead
  client can never replay) after a 30 s reconnect cooldown.
- Read-only: the only payloads it publishes are its own
  `get_version`/`pushall` requests.
- Events: gcode_state transitions become `status` events
  (started/paused/resumed/cancelled), FINISH becomes `completion`, FAILED
  becomes `error` with the decoded HMS entries attached, and the first
  complete snapshot of a session emits `snapshot_available` when the
  model has a verified camera protocol.

With `[bambu] lan_host`/`lan_serial` unset, the Bambu listener starts but
idles — heartbeat alive, `printer_connected=False`, no network contact —
so an offline Bambu configuration behaves exactly as it did before the
domain had a listener. See [Bambu Lab printers](BAMBU-LAB.md#lan-status-read-only-opt-in).

## Instances

Today one container serves one printer (see [More than one
printer](MULTI-INSTANCE.md)), so one listener instance runs at most. The
registry, gate and supervisor already speak of the *configured printer
instance's* listener rather than a single global listener, so the
multi-printer work in #257 adds instances per printer without redesigning
this layer.
