"""
central_core_mqtt_shared.topics

Canonical MQTT topic templates for the central-core ecosystem.

Vault = central server
Hub   = remote client device connected to Home Assistant
Addon = Home Assistant plugin running inside each Hub

All hub-scoped topics follow:

    hubs/{hub_id}/v{version}/...

Placeholders:
    {hub_id}      : unique hub identifier
    {version}     : protocol/software version
    {domain}      : command domain (sensors, config, firmware, tunnel, etc.)
    {action}      : specific action in a command domain
    {command}     : addon-specific command name
    {command_name}: logical name of the command for acknowledgements
    {command_id}  : unique identifier for a specific command instance

Use `build_topic(TEMPLATE, hub_id="...", version=1, ...)` to generate concrete topics.
"""


# ============================================================
# Telemetry (Hub → Vault)
# ============================================================

TELEMETRY_SYSTEM = "hubs/{hub_id}/v{version}/telemetry/system"
"""System-level telemetry: CPU, RAM, uptime, disk usage, etc."""

TELEMETRY_SENSORS = "hubs/{hub_id}/v{version}/telemetry/sensors"
"""Sensor states from Home Assistant. Used for: basic list, full metadata, and delta updates."""

TELEMETRY_EVENTS = "hubs/{hub_id}/v{version}/telemetry/events"
"""Discrete events such as door motion, notifications, automations, or HA-driven events."""

TELEMETRY_GENERAL = "hubs/{hub_id}/v{version}/telemetry/general"
"""Catch-all telemetry category for user-defined or extension data."""


# ============================================================
# Presence / Lifecycle (Hub → Vault)
# ============================================================

STATUS_ONLINE = "hubs/{hub_id}/v{version}/status/online"
"""Hub heartbeat. Published periodically and on startup."""

STATUS_OFFLINE = "hubs/{hub_id}/v{version}/status/offline"
"""Hub offline LWT message. Should be configured as MQTT Last Will."""


# ============================================================
# Commands (Vault → Hub)
# ============================================================

CMD_CONFIG_UPDATE = "hubs/{hub_id}/v{version}/cmd/config/update"
"""Push new configuration or override values to the hub."""

CMD_FIRMWARE_UPDATE = "hubs/{hub_id}/v{version}/cmd/firmware/update"
"""Trigger OTA firmware update."""

CMD_TUNNEL_START = "hubs/{hub_id}/v{version}/cmd/tunnel/start"
"""Start Cloudflare or SSH reverse tunnel."""

CMD_TUNNEL_STOP = "hubs/{hub_id}/v{version}/cmd/tunnel/stop"
"""Stop Cloudflare or SSH reverse tunnel."""

CMD_SENSORS_POLL = "hubs/{hub_id}/v{version}/cmd/sensors/poll"
"""Request FULL metadata for one or more sensors from HA."""

CMD_SENSORS_SET = "hubs/{hub_id}/v{version}/cmd/sensors/set"
"""Set or override sensor configuration details."""


# ============================================================
# Generic command template
# ============================================================

CMD_GENERIC = "hubs/{hub_id}/v{version}/cmd/{domain}/{action}"
"""
Generic command template.

Example:
    build_topic(
        CMD_GENERIC,
        hub_id="hub123",
        version=1,
        domain="diagnostics",
        action="run",
    )
→ "hubs/hub123/v1/cmd/diagnostics/run"
"""


# ============================================================
# Acknowledgements (Hub → Vault)
# ============================================================

ACK_GENERIC = "hubs/{hub_id}/v{version}/ack/{command_name}/{command_id}"
"""
Hub acknowledges command execution.

Example:
    Command issued with:
        command_name = "config.update"
        command_id   = "abc123"

    Hub replies on:
        hubs/<id>/v1/ack/config.update/abc123
"""


# ============================================================
# Home Assistant Addon Namespace
# ============================================================

ADDON_HA_TELEMETRY = "hubs/{hub_id}/v{version}/addon/ha/telemetry"
"""Telemetry emitted by the Home Assistant addon."""

ADDON_HA_STATUS = "hubs/{hub_id}/v{version}/addon/ha/status"
"""Lifecycle or heartbeat of the HA addon."""

ADDON_HA_CMD = "hubs/{hub_id}/v{version}/addon/ha/cmd/{command}"
"""Commands sent from Vault to Home Assistant addon."""


# ============================================================
# Broadcast (Vault → All Hubs)
# ============================================================

BROADCAST_CMD = "hubs/broadcast/v{version}/cmd/{command}"
"""Vault broadcasts global commands to all hubs."""


# ============================================================
# Helper
# ============================================================

def build_topic(template: str, **kwargs) -> str:
    """
    Render a topic template with the required placeholders.

    Example:
        build_topic(TELEMETRY_SYSTEM, hub_id="hub123", version=1)
    ->  "hubs/hub123/v1/telemetry/system"
    """
    return template.format(**kwargs)


# ============================================================
# Public exports
# ============================================================

__all__ = [
    # Telemetry
    "TELEMETRY_SYSTEM",
    "TELEMETRY_SENSORS",
    "TELEMETRY_EVENTS",
    "TELEMETRY_GENERAL",

    # Status
    "STATUS_ONLINE",
    "STATUS_OFFLINE",

    # Commands
    "CMD_CONFIG_UPDATE",
    "CMD_FIRMWARE_UPDATE",
    "CMD_TUNNEL_START",
    "CMD_TUNNEL_STOP",
    "CMD_SENSORS_POLL",
    "CMD_SENSORS_SET",
    "CMD_GENERIC",

    # Ack
    "ACK_GENERIC",

    # Addon
    "ADDON_HA_TELEMETRY",
    "ADDON_HA_STATUS",
    "ADDON_HA_CMD",

    # Broadcast
    "BROADCAST_CMD",

    # Helper
    "build_topic",
]

