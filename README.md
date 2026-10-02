# central-core-mqtt-shared

Shared MQTT topic templates and payload schemas for the central-core ecosystem (Vault, Hub, and the Home Assistant addon).

## Protocol basics
- All hub-scoped topics are versioned: `hubs/{hub_id}/v{version}/...`.
- Use `central_core_mqtt_shared.topics.build_topic()` to render concrete topics.
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
