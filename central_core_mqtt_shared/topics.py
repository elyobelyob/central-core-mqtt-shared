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
Values are validated. Subscriptions with wildcard levels use
`build_subscription(TEMPLATE, wildcards=(...), ...)`: a hub for the domain and
action of its own commands, the vault with `hub_id=ANY_HUB` for every hub.
"""

import re
import string
import unicodedata


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
# Helpers
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

# Longest value accepted for any other topic level (command ids, domains, ...),
# in UTF-8 bytes.
MAX_SEGMENT_LENGTH = 128

# Characters that end or reshape a topic level.
_TOPIC_SEPARATORS = frozenset("/+#")
# Unicode categories never allowed in a level: control (C0, DEL, C1), format
# (zero-width, bidirectional overrides such as U+200B and U+202E), surrogates,
# separators (spaces, line and paragraph separators), and unassigned code
# points including the non-characters U+FDD0-FDEF and U+xFFFE/xFFFF (a broker
# such as mosquitto disconnects a client that sends them).
_BAD_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zs", "Zl", "Zp", "Cn"})

SINGLE_LEVEL_WILDCARD = "+"


class _AnyHub:
    """Marker for "every hub" in `build_subscription` (renders as `+`).

    There is exactly one: copying or pickling it gives the same object back."""

    __slots__ = ()

    def __repr__(self):
        return "ANY_HUB"

    def __reduce__(self):
        return "ANY_HUB"  # pickled as a reference to this module's ANY_HUB

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


ANY_HUB = _AnyHub()
"""Pass it as the hub level's value (`hub_id=ANY_HUB`) to `build_subscription`
to subscribe for every hub (the vault). No string, not even "+", is ever taken
as "every hub"."""


def is_valid_hub_id(hub_id: object) -> bool:
    """True when `hub_id` is a plain `str` that is safe as the hub level of a topic."""
    return (
        type(hub_id) is str
        and _HUB_ID_RE.fullmatch(hub_id) is not None
        and hub_id not in RESERVED_HUB_IDS
    )


def validate_hub_id(hub_id: object) -> str:
    """Return `hub_id` unchanged, or raise ValueError if it is not a valid hub id.

    Only an exact `str` is accepted: a subclass could render differently from
    what was checked."""
    if not is_valid_hub_id(hub_id):
        raise ValueError(f"invalid hub id: {hub_id!r}")
    return hub_id  # type: ignore[return-value]


def _segment(name: str, value: object) -> str:
    """One concrete topic level, checked, as the exact text that will be used.
    Raises ValueError for anything that could change the shape of the topic or
    hide in it."""
    if isinstance(value, str):
        text = str.__str__(value)  # the characters themselves, whatever a subclass overrides
    elif isinstance(value, int) and not isinstance(value, bool):
        text = int.__repr__(value)
    else:
        raise ValueError(f"topic field {name!r} must be a string or integer, not {type(value).__name__}")
    if not text:
        raise ValueError(f"topic field {name!r} is empty")
    for ch in text:
        if ch in _TOPIC_SEPARATORS or unicodedata.category(ch) in _BAD_CATEGORIES:
            raise ValueError(f"topic field {name!r} contains a character not allowed in a topic level")
    # Surrogates were refused above, so this always encodes.
    if len(text.encode("utf-8")) > MAX_SEGMENT_LENGTH:
        raise ValueError(f"topic field {name!r} is longer than {MAX_SEGMENT_LENGTH} bytes")
    return text


def _template_levels(template: object) -> list:
    """The template split into topic levels, each a list of (literal, name)
    pieces. Refuses anything but plain `{name}` placeholders, and any `+` or `#`
    in the template's own text (wildcards come only from wildcard levels)."""
    if type(template) is not str:
        raise ValueError("topic template must be a string")
    levels = []
    for level in template.split("/"):
        try:
            parsed = list(string.Formatter().parse(level))
        except ValueError as exc:
            raise ValueError(f"malformed topic template: {exc}") from None
        pieces = []
        for literal, name, spec, conversion in parsed:
            if "+" in literal or "#" in literal:
                raise ValueError("topic template text may not contain '+' or '#'")
            if name is None:
                pieces.append((literal, None))
                continue
            if not name.isidentifier():
                raise ValueError(f"topic template field {name!r} must be a plain name")
            if spec or conversion:
                raise ValueError(f"topic template field {name!r} may not have a format spec or conversion")
            pieces.append((literal, name))
        levels.append(pieces)
    return levels


def _hub_level_name(levels: list) -> object:
    """The placeholder that is the hub level (`hubs/{name}/...`), whatever it is called."""
    if len(levels) >= 2 and levels[0] == [("hubs", None)] and len(levels[1]) == 1 and levels[1][0][0] == "":
        return levels[1][0][1]
    return None


def _render(template: str, fields: dict, wildcards: frozenset, allow_any_hub: bool) -> str:
    levels = _template_levels(template)
    names = {name for level in levels for _literal, name in level if name}
    hub_level = _hub_level_name(levels)
    hub_names = {"hub_id"} & names
    if hub_level is not None:
        hub_names.add(hub_level)
    unknown = wildcards - names
    if unknown:
        raise ValueError(f"wildcard levels not in the template: {sorted(unknown)}")
    if wildcards & hub_names:
        raise ValueError("subscribe for every hub with ANY_HUB as the hub level's value, not a wildcard")
    for name in wildcards:
        for level in levels:
            if any(n == name for _literal, n in level) and level != [("", name)]:
                raise ValueError(f"a wildcard must fill a whole topic level: {name!r}")
    safe = {}
    for name in names:
        if name in wildcards:
            value = fields.get(name, SINGLE_LEVEL_WILDCARD)
            if type(value) is not str or value != SINGLE_LEVEL_WILDCARD:
                raise ValueError(f"topic field {name!r} is a wildcard level; leave it out or pass '+'")
            safe[name] = SINGLE_LEVEL_WILDCARD
        elif name not in fields:
            raise KeyError(name)
        elif fields[name] is ANY_HUB:
            if not allow_any_hub:
                raise ValueError("ANY_HUB is only for build_subscription")
            if name != hub_level:
                raise ValueError(f"ANY_HUB is only for the hub level, not {name!r}")
            safe[name] = SINGLE_LEVEL_WILDCARD
        elif name in hub_names:
            safe[name] = validate_hub_id(fields[name])
        else:
            safe[name] = _segment(name, fields[name])
    return template.format(**safe)


def build_topic(template: str, **kwargs) -> str:
    """
    Render a topic template with the required placeholders.

    Every placeholder value is checked. The hub level (`hubs/{hub_id}/...`, or
    any placeholder named `hub_id`) must be an exact `str` matching
    `HUB_ID_PATTERN` and not reserved. Any other value must be a non-empty
    string or integer of at most MAX_SEGMENT_LENGTH UTF-8 bytes, free of `/`,
    `+`, `#` and of control, format, separator, surrogate and unassigned
    characters. The template may only use plain `{name}` placeholders and
    may not contain `+` or `#` itself. A bad value or template raises
    ValueError, so a stray wildcard can never widen a publish or a
    subscription. A missing placeholder raises KeyError; extra keyword
    arguments are ignored.

    For a subscription with wildcard levels, use `build_subscription`.

    Example:
        build_topic(TELEMETRY_SYSTEM, hub_id="hub123", version=1)
    ->  "hubs/hub123/v1/telemetry/system"
    """
    return _render(template, kwargs, frozenset(), allow_any_hub=False)


def build_subscription(template: str, wildcards=(), **kwargs) -> str:
    """
    Render a subscription topic: like `build_topic`, but the levels named in
    `wildcards` become the single-level wildcard `+`.

    Every occurrence of a wildcard level must fill a whole level of the
    template (`v{version}` cannot be one), and its value is either left out or
    "+". Every other level is checked exactly as in `build_topic`, so "+"
    there is an error. The hub level is never named in `wildcards`: subscribe
    for every hub by passing ANY_HUB as its value (`hub_id=ANY_HUB`, the vault).
    The multi-level `#` is never produced.

    Examples:
        # a hub, its own commands:
        build_subscription(CMD_GENERIC, wildcards=("domain", "action"), hub_id="hub123", version=1)
    ->  "hubs/hub123/v1/cmd/+/+"
        # the vault, every hub's acknowledgements:
        build_subscription(ACK_GENERIC, wildcards=("command_name", "command_id"), hub_id=ANY_HUB, version=1)
    ->  "hubs/+/v1/ack/+/+"
    """
    if wildcards is None or isinstance(wildcards, (str, bytes)):
        raise ValueError("wildcards must be a sequence of level names")
    wild = frozenset(wildcards)
    if not all(type(name) is str for name in wild):
        raise ValueError("wildcards must be a sequence of level names")
    return _render(template, kwargs, wild, allow_any_hub=True)


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
    "ANY_HUB",
    "SINGLE_LEVEL_WILDCARD",
    "validate_hub_id",
    "is_valid_hub_id",
    "HUB_ID_PATTERN",
    "RESERVED_HUB_IDS",
    "MAX_SEGMENT_LENGTH",
]

