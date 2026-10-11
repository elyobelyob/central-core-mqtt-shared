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
Values are validated; the vault's wildcard subscriptions use `build_subscription`.
"""

import re
import string


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

TELEMETRY_BATCH = "hubs/{hub_id}/v{version}/telemetry/batch"
"""
Catch-up batch (protocol 1.1): readings a hub resends from its outbox, oldest
first, as one `schemas.TelemetryBatch`. Each record keeps its own `seq` and
`event_ts`, so a reading resent hours late is stored at the time it happened.
"""


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
# Store acknowledgement (Vault → Hub), protocol 1.1
# ============================================================

STORE_ACK = "hubs/{hub_id}/v{version}/ack"
"""
The vault has stored (committed) every reading of this hub's outbox up to and
including `upto` (`schemas.StoreAck`). The hub deletes those readings; it keeps
everything else and resends it. Published by the vault at QoS 1.

This topic has no further levels, so it never matches the command-ack template
`ACK_GENERIC` (`.../ack/{command_name}/{command_id}`) and vice versa.
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

# A hub id is one MQTT topic level, so it must never contain `/`, `+` or `#`
# (a `+` would make a hub subscribe to every hub's commands). Real ids look
# like `abc-001`; the pattern also allows upper case, `.` and `_` (an id the
# add-on derived from a host name) and a single character, so ids that hubs
# already use keep working.
HUB_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
_HUB_ID_RE = re.compile(HUB_ID_PATTERN)

# `hubs/broadcast/...` is the broadcast namespace: a hub of that name would
# receive (and could publish) broadcast traffic.
RESERVED_HUB_IDS = frozenset({"broadcast"})

# Longest value accepted for any other topic level (command ids, domains, ...).
MAX_SEGMENT_LENGTH = 128

# Characters that end or reshape a topic level: separators, wildcards, control
# characters (NUL included) and white space.
_BAD_SEGMENT_CHARS = re.compile(r"[/+#\x00-\x1f\x7f\s]")

_SINGLE_LEVEL_WILDCARD = "+"


def is_valid_hub_id(hub_id: object) -> bool:
    """True when `hub_id` is safe to use as the hub level of a topic."""
    return (
        isinstance(hub_id, str)
        and _HUB_ID_RE.fullmatch(hub_id) is not None
        and hub_id not in RESERVED_HUB_IDS
    )


def validate_hub_id(hub_id: object) -> str:
    """Return `hub_id` unchanged, or raise ValueError if it is not a valid hub id."""
    if not is_valid_hub_id(hub_id):
        raise ValueError(f"invalid hub id: {hub_id!r}")
    return str(hub_id)


def _segment(name: str, value: object, allow_wildcard: bool) -> str:
    """One topic level, checked. Raises ValueError for anything that could
    change the shape of the topic."""
    if allow_wildcard and value == _SINGLE_LEVEL_WILDCARD:
        return _SINGLE_LEVEL_WILDCARD
    if name == "hub_id":
        # Strings only: an integer database key is not a hub id.
        return validate_hub_id(value)
    if value is None or isinstance(value, (bytes, bytearray)):
        raise ValueError(f"topic field {name!r} must be a string or number, not {value!r}")
    text = str(value)
    if not text:
        raise ValueError(f"topic field {name!r} is empty")
    if len(text) > MAX_SEGMENT_LENGTH:
        raise ValueError(f"topic field {name!r} is longer than {MAX_SEGMENT_LENGTH} characters")
    if _BAD_SEGMENT_CHARS.search(text):
        raise ValueError(f"topic field {name!r} contains a character not allowed in a topic level")
    return text


def _render(template: str, fields: dict, allow_wildcard: bool) -> str:
    safe = dict(fields)
    for _, name, _, _ in string.Formatter().parse(template):
        # Only plain `{name}` fields are used by our templates; a field that is
        # missing is left for str.format to report as a KeyError.
        if name and name in fields:
            safe[name] = _segment(name, fields[name], allow_wildcard)
    return template.format(**safe)


def build_topic(template: str, **kwargs) -> str:
    """
    Render a topic template with the required placeholders.

    Every placeholder value is checked: a `hub_id` must match `HUB_ID_PATTERN`
    (and not be reserved), any other value must be non-empty and free of `/`,
    `+`, `#`, control characters and white space. A bad value raises
    ValueError, so a stray wildcard can never widen a publish or a
    subscription. A missing placeholder still raises KeyError; extra keyword
    arguments are ignored.

    To subscribe with a `+` in a level, use `build_subscription`.

    Example:
        build_topic(TELEMETRY_SYSTEM, hub_id="hub123", version=1)
    ->  "hubs/hub123/v1/telemetry/system"
    """
    return _render(template, kwargs, allow_wildcard=False)


def build_subscription(template: str, **kwargs) -> str:
    """
    Like `build_topic`, but a level may be the single-level wildcard `+`.

    For the vault's subscriptions (for example `hub_id="+"` to hear every
    hub). The multi-level `#` and any `+` mixed into other text are still
    refused. Hubs must use `build_topic`, never this.

    Example:
        build_subscription(TELEMETRY_SYSTEM, hub_id="+", version=1)
    ->  "hubs/+/v1/telemetry/system"
    """
    return _render(template, kwargs, allow_wildcard=True)


# ============================================================
# Public exports
# ============================================================

__all__ = [
    # Telemetry
    "TELEMETRY_SYSTEM",
    "TELEMETRY_SENSORS",
    "TELEMETRY_EVENTS",
    "TELEMETRY_GENERAL",
    "TELEMETRY_BATCH",

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
    "STORE_ACK",

    # Addon
    "ADDON_HA_TELEMETRY",
    "ADDON_HA_STATUS",
    "ADDON_HA_CMD",

    # Broadcast
    "BROADCAST_CMD",

    # Helpers
    "build_topic",
    "build_subscription",
    "validate_hub_id",
    "is_valid_hub_id",
    "HUB_ID_PATTERN",
    "RESERVED_HUB_IDS",
    "MAX_SEGMENT_LENGTH",
]

