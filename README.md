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
