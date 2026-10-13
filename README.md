# central-core-mqtt-shared

Shared MQTT topic templates and payload schemas for the central-core ecosystem (Vault, Hub, and the Home Assistant addon).

## What we believe

Central Core helps families look after someone living with dementia at home. Dementia care should be care:

1. **Care first.** Every feature has to help a family look after someone better. If it only helps us, it doesn't ship.
2. **Dignity.** No cameras, no microphones, nothing that watches. Sensors notice the rhythm of the day, not the person.
3. **The family stays in control.** They choose who sees what, how alerts work and when to stop. Their data is theirs.
4. **Plain and honest.** We say what the sensors showed, never more. No medical claims, no scare tactics.
5. **Affordable.** The monthly fee stays low, and you pay only for extras you use.
6. **Open.** The code is public, so anyone can check it, run it or improve it.

## Protocol basics
- All hub-scoped topics are versioned: `hubs/{hub_id}/v{version}/...`.
- Use `central_core_mqtt_shared.topics.build_topic()` to render concrete topics. It checks every value: a hub id must match `topics.HUB_ID_PATTERN`; any other level must be a non-empty string or integer of at most 128 UTF-8 bytes, free of `/`, `+`, `#` and control, format or separator characters. Templates may only use plain `{name}` placeholders. Anything else raises `ValueError`.
- Subscriptions with wildcards use `build_subscription(template, wildcards=(...), ...)`, which names the levels that become `+` (each must fill a whole level). A hub subscribes to its own commands with `build_subscription(topics.CMD_GENERIC, wildcards=("domain", "action"), hub_id=<its id>, version=1)`. Only the vault subscribes for every hub, with `hub_id=topics.ANY_HUB`; no string (not even `"+"`) is ever taken as "every hub".
- The Pydantic models bound what arrives off the network; see "What is bounded" below for the exact list.
- Payloads are validated with the Pydantic models in `central_core_mqtt_shared.schemas`.

## MQTT endpoints (topics)
- Telemetry (Hub → Vault)
  - System: `hubs/{hub_id}/v{version}/telemetry/system` (`schemas.SystemTelemetry`)
  - Sensors: `hubs/{hub_id}/v{version}/telemetry/sensors` (`schemas.SensorsTelemetry`)
  - Events: `hubs/{hub_id}/v{version}/telemetry/events` (`schemas.EventTelemetry`)
  - General: `hubs/{hub_id}/v{version}/telemetry/general` (`schemas.GeneralTelemetry`)
- Status / presence (Hub → Vault)
  - Online heartbeat: `hubs/{hub_id}/v{version}/status/online` (`schemas.StatusOnline`)
  - Offline (LWT): `hubs/{hub_id}/v{version}/status/offline` (`schemas.StatusOffline`)
- Commands (Vault → Hub)
  - Config update: `hubs/{hub_id}/v{version}/cmd/config/update` (`schemas.ConfigUpdateCommand`)
  - Firmware update: `hubs/{hub_id}/v{version}/cmd/firmware/update` (`schemas.FirmwareUpdateCommand`)
  - Tunnel control: `hubs/{hub_id}/v{version}/cmd/tunnel/start|stop` (`schemas.TunnelStartCommand` / `schemas.TunnelStopCommand`)
  - Sensor control: `hubs/{hub_id}/v{version}/cmd/sensors/poll|set` (`schemas.SensorsPollCommand` / `schemas.SensorsSetCommand`)
  - Generic command template: `hubs/{hub_id}/v{version}/cmd/{domain}/{action}`
- Acknowledgements (Hub → Vault)
  - Command ack: `hubs/{hub_id}/v{version}/ack/{command_name}/{command_id}` (`schemas.CommandAck`)
- Home Assistant addon namespace
  - Addon telemetry: `hubs/{hub_id}/v{version}/addon/ha/telemetry` (`schemas.HAAddonTelemetry`)
  - Addon status: `hubs/{hub_id}/v{version}/addon/ha/status` (`schemas.HAAddonStatus`)
  - Addon command: `hubs/{hub_id}/v{version}/addon/ha/cmd/{command}` (`schemas.HAAddonCommand`)
- Broadcast (Vault → all hubs)
  - Global commands: `hubs/broadcast/v{version}/cmd/{command}`
- Store and confirm (protocol 1.1, since v1.1.0)
  - Catch-up batch (Hub → Vault): `hubs/{hub_id}/v{version}/telemetry/batch` (`schemas.TelemetryBatch`)
  - Store ack (Vault → Hub): `hubs/{hub_id}/v{version}/ack` (`schemas.StoreAck`, `{"upto": N, "stored": K}`)

## Store and confirm (v1.1.0)

A hub keeps every reading in an on-disk outbox until the vault says it has
stored it. Telemetry payloads gain optional fields (`schemas.OutboxFields`):

| field | meaning |
|---|---|
| `seq` | per-hub sequence number, increasing within one `outbox_id` |
| `event_ts` | when the reading happened (Home Assistant `last_changed`), UTC ISO 8601 |
| `outbox_id` | names the hub's outbox; `(hub, outbox_id, seq)` is the dedupe key |
| `oldest_seq` | oldest `seq` the hub still holds unacknowledged |
| `hub_time` | the hub's clock when it sent the message (clock check) |

After committing readings, the vault publishes `StoreAck` with `upto`, the end
of the unbroken run of stored `seq`s from `oldest_seq`. The hub deletes those
and resends the rest (on reconnect, oldest first, in `TelemetryBatch`es whose
records keep their own `seq` and `event_ts`). The vault stores history at
`event_ts`, so a reading resent hours late lands at the time it happened.

All of it is optional: payloads without `seq` validate and are handled as before.

## Validation (v1.2.0)

v1.2.0 checks what goes into topics and payloads. The wire format is unchanged,
but a consumer moving its pin from v1.1.0 must:

- build every subscription that contains `+` with `build_subscription`, naming
  the wildcard levels (`build_topic` now refuses `+`). The vault subscribes for
  every hub with `hub_id=topics.ANY_HUB`; a hub subscribes to its own commands
  with `wildcards=("domain", "action")`;
- pass only hub ids that match `topics.HUB_ID_PATTERN` (letters, digits, `.`,
  `_`, `-`; up to 64 characters; not `broadcast`) and topic levels without
  `/`, `+`, `#`, control or format characters;
- expect `ValueError` from `build_topic` / `build_subscription`, and
  `ValidationError` for values outside the bounds below.

`SystemTelemetry` also gains two optional fields, `ha_connected` and
`ha_last_event_at` (None from older hubs): whether Home Assistant is feeding
the hub, and when it last sent an event.

v1.3.0 adds a third, `ha_last_message_at` (UTC ISO 8601, None from older hubs):
when anything last came back over the Home Assistant websocket, a ping reply
included. `ha_last_event_at` only moves when a watched sensor changes; this one
keeps moving in a quiet house, so "connected but quiet" differs from "feed dead".

### What is bounded (v1.2.0)

Topics (`topics.py`):

- hub level: an exact `str` matching `HUB_ID_PATTERN` (1-64 characters), not `broadcast`;
- every other level: a non-empty `str` or `int`, at most 128 UTF-8 bytes, without `/`, `+`, `#` or
  Unicode control, format, surrogate, separator or unassigned characters;
- templates: plain `{name}` placeholders only, and no `+` or `#` in their own text.

Payloads (`schemas.py`, constants in brackets):

- sequence numbers and counters (`seq`, `oldest_seq`, `upto`, `stored`, a config `version`): 0 or 1 up to
  2^63-1 (`MAX_SEQ`);
- epoch timestamps: finite, from 0 to before the year 3000 (`MAX_TIMESTAMP`); ISO 8601 times: at most
  64 characters (`MAX_TIME_LENGTH`), with a UTC offset, before the year 3000;
- `SystemTelemetry`: `cpu` and `ram` 0-100, `uptime` 0-100 years (`MAX_UPTIME_S`), `temperature`
  -100 to 250, all finite;
- strings: sensor `id`, `type`, `unit` and a poll's `entity_id` at most 255 characters
  (`MAX_ENTITY_ID_LENGTH`); command ids and add-on actions 1-128 (`MAX_COMMAND_ID_LENGTH`); ack
  `message` 4096 (`MAX_ACK_MESSAGE_LENGTH`); firmware `download_url` 2048 and `checksum` 256;
  add-on `version` 64; status words 32 (`MAX_STATUS_LENGTH`); `outbox_id` 1-64;
- a sensor `state`: at most 4 KB (`MAX_STATE_BYTES`; a string's own UTF-8 bytes, anything else as
  compact JSON in UTF-8);
- free-form objects: at most 10,000 keys (`MAX_DICT_KEYS`) and, as compact JSON in UTF-8 bytes,
  64 KB for one sensor's `attributes` (`MAX_ATTRIBUTES_BYTES`) and 256 KB for any other (`details`,
  `data`, `config`, `metadata`, `settings`, `state`, a record's `payload`; `MAX_FREE_JSON_BYTES`);
- lists: at most 10,000 sensors in one message (`MAX_SENSORS`) and 200 records in one batch
  (`MAX_BATCH_RECORDS`).

How a limit shows depends on the model. Each model refuses a value over its
own limits with a `ValidationError`, but in `SensorsTelemetry` a sensor is
`FullSensor` or else `BasicSensor`: a sensor whose `attributes` or `unit` is too
big is kept as a `BasicSensor` (id, state, type) with those fields dropped,
rather than failing the message. Its `id`, `type` and `state` limits apply
either way. Unknown keys are ignored everywhere (pydantic's default), so a newer
hub's extra fields never fail an older consumer.

Not bounded by the schemas: the total size of a whole message (that is the broker's
`max_packet_size` and each consumer's own limit), and a command's `payload` (the command models
do not describe it).

## Helper usage
```py
from central_core_mqtt_shared import topics, schemas

topic = topics.build_topic(
    topics.CMD_CONFIG_UPDATE,
    hub_id="hub123",
    version=1,
)

payload = schemas.ConfigUpdateCommand(
    command_id="abc123",
    version=1,
    config={"feature_flag": True},
)
```

## Home Assistant discovery

The shared package now exposes `central_core_mqtt_shared.ha` helpers that talk to Home Assistant's REST and websocket APIs, keep the schema authoritative, and work without hard‑coded metadata.

```py
from central_core_mqtt_shared.ha import discover_all_from_environment

# requires HA_REST_URL and HA_TOKEN to be set in the environment before calling
metadata = await discover_all_from_environment()
print("REST base:", metadata.rest.base_url)
print("Websocket URL:", metadata.websocket.websocket_url)
```

Set `HA_REST_URL` to your Home Assistant base URL (e.g., `https://example.local:8123`) and keep `HA_TOKEN` as a long‑lived access token stored outside version control; the helper will read both at runtime. You can also run the discovery CLI directly:

```
HA_REST_URL=https://example.local:8123 HA_TOKEN=secret python -m central_core_mqtt_shared.ha.discovery
```

This prints the cached services/states/config payloads so Vault, Hub, or the addon can reuse them without manual syncs. Always keep the token private—don’t commit it anywhere in the repo.
