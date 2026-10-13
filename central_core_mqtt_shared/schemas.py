from __future__ import annotations
import json
from datetime import datetime, timezone
from pydantic import AfterValidator, BaseModel, Field, field_validator
from typing import Annotated, Optional, Dict, Any, Union, List
from enum import Enum


# ============================================================
# LIMITS
#
# Messages come off the network, so every number and list a schema accepts has
# an upper bound. The bounds are far above what a real hub sends; they only
# keep a forged or broken message from reaching a database as a huge number or
# an enormous list.
# ============================================================

# Largest sequence number or counter: what a signed 64-bit database column holds.
MAX_SEQ = 2**63 - 1

# Longest ISO 8601 time string we will try to parse (real ones are about 35).
MAX_TIME_LENGTH = 64

# Most sensors in one sensors telemetry message.
MAX_SENSORS = 10_000

# Home Assistant entity ids are at most 255 characters.
MAX_ENTITY_ID_LENGTH = 255

# Longest command id (the vault issues 22-character url-safe tokens).
MAX_COMMAND_ID_LENGTH = 128

# Longest free-text message in a command acknowledgement.
MAX_ACK_MESSAGE_LENGTH = 4096

# Most keys in one free-form dict (attributes, details, config, ...).
MAX_DICT_KEYS = 10_000

# Epoch-second timestamps must be finite, not negative, and before the year 3000.
MAX_TIMESTAMP = 32503680000.0  # 3000-01-01T00:00:00Z
MAX_YEAR = 2999

# System telemetry: percentages, an uptime of at most 100 years, a temperature in degrees C.
MAX_UPTIME_S = 100 * 365.25 * 24 * 3600

# Largest free-form value, measured as compact JSON in UTF-8 bytes.
MAX_STATE_BYTES = 4 * 1024  # one sensor state (Home Assistant itself keeps them to 255 characters)
MAX_ATTRIBUTES_BYTES = 64 * 1024  # one sensor's attributes
MAX_FREE_JSON_BYTES = 256 * 1024  # any other free-form object (details, config, payload, ...)

# Longest status word in StatusOnline / StatusOffline.
MAX_STATUS_LENGTH = 32


def _json_bytes_at_most(limit: int):
    """A validator: the value, as compact JSON, is at most `limit` UTF-8 bytes."""

    def check(value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, str):
            size = len(value.encode("utf-8", "surrogatepass"))
        else:
            try:
                text = json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError, RecursionError):
                raise ValueError("not representable as JSON") from None
            # UTF-8 bytes, as documented ("surrogatepass" only so a lone surrogate
            # from a JSON \ud800 escape is measured rather than raising).
            size = len(text.encode("utf-8", "surrogatepass"))
        if size > limit:
            raise ValueError(f"larger than {limit} bytes")
        return value

    return check


Timestamp = Annotated[float, Field(ge=0, lt=MAX_TIMESTAMP, allow_inf_nan=False)]
"""Seconds since the epoch, finite, from 1970 to before the year 3000."""

FreeDict = Annotated[
    Dict[str, Any], Field(max_length=MAX_DICT_KEYS), AfterValidator(_json_bytes_at_most(MAX_FREE_JSON_BYTES))
]
"""A free-form JSON object: at most MAX_DICT_KEYS keys and MAX_FREE_JSON_BYTES as JSON."""

AttributesDict = Annotated[
    Dict[str, Any], Field(max_length=MAX_DICT_KEYS), AfterValidator(_json_bytes_at_most(MAX_ATTRIBUTES_BYTES))
]
"""One sensor's attributes: at most MAX_DICT_KEYS keys and MAX_ATTRIBUTES_BYTES as JSON."""

SensorState = Annotated[Optional[Any], AfterValidator(_json_bytes_at_most(MAX_STATE_BYTES))]
"""One sensor state: at most MAX_STATE_BYTES (a string's own bytes, anything else as JSON)."""


# ============================================================
# TIME HELPERS (protocol 1.1: store and confirm)
# ============================================================

def parse_utc_iso(value: Any) -> datetime:
    """Parse an ISO 8601 time that carries an offset into an aware UTC datetime.

    A trailing "Z" is accepted. A time without an offset is refused: the
    receiver cannot know which zone it was in, and guessing puts a reading in
    the wrong hour (or, across a month end, the wrong history partition).
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        if len(value) > MAX_TIME_LENGTH:
            raise ValueError("not an ISO 8601 time: too long")
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"not an ISO 8601 time: {value!r}") from exc
    else:
        raise ValueError(f"not an ISO 8601 time: {value!r}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"time has no UTC offset: {value!r}")
    try:
        utc = dt.astimezone(timezone.utc)
    except OverflowError:  # e.g. year 9999 with a negative offset, or year 1 with a positive one
        raise ValueError(f"time out of range: {value!r}") from None
    if utc.year > MAX_YEAR:
        raise ValueError(f"time out of range: {value!r}")
    return utc


def to_utc_iso(value: Any) -> str:
    """Canonical wire form of a time: UTC, ISO 8601, ending in "Z"."""
    return parse_utc_iso(value).isoformat().replace("+00:00", "Z")


def _optional_utc_iso(value: Any) -> Optional[str]:
    return None if value is None else to_utc_iso(value)


# ============================================================
# ENUMS
# ============================================================

class AckStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class EventType(str, Enum):
    DOOR = "door"
    MOTION = "motion"
    BUTTON = "button"
    POWER = "power"
    OTHER = "other"


class CommandName(str, Enum):
    CONFIG_UPDATE = "config.update"
    FIRMWARE_UPDATE = "firmware.update"
    TUNNEL_START = "tunnel.start"
    TUNNEL_STOP = "tunnel.stop"
    SENSORS_POLL = "sensors.poll"
    SENSORS_SET = "sensors.set"
    ADDON_HA = "addon.ha"


# ============================================================
# OUTBOX FIELDS (protocol 1.1, all optional)
# ============================================================

class OutboxFields(BaseModel):
    """Store-and-confirm fields a hub adds to a telemetry message (protocol 1.1).

    All optional: a message from an older hub has none of them and is handled
    as before. When `seq` is present the message is in the hub's outbox and
    stays there until the vault acknowledges it on `topics.STORE_ACK`.

    - `seq`: per-hub sequence number, strictly increasing for one `outbox_id`
      (it survives restarts; a new outbox, for example after a reinstall,
      gets a new `outbox_id`).
    - `event_ts`: when the reading happened (Home Assistant's `last_changed`
      for a state change), UTC ISO 8601. The vault stores history at this
      time, never at the time the message arrived.
    - `outbox_id`: identifies one outbox on the hub (dedupe key with `seq`).
    - `oldest_seq`: the oldest `seq` the hub still holds unacknowledged, so
      the vault knows where the unbroken run it acknowledges starts.
    - `hub_time`: the hub's clock when it sent the message (clock check).
    """
    seq: Optional[int] = Field(None, ge=1, le=MAX_SEQ)
    event_ts: Optional[str] = None
    outbox_id: Optional[str] = Field(None, min_length=1, max_length=64)
    oldest_seq: Optional[int] = Field(None, ge=1, le=MAX_SEQ)
    hub_time: Optional[str] = None

    @field_validator("event_ts", "hub_time", mode="before")
    @classmethod
    def _utc_times(cls, value: Any) -> Optional[str]:
        return _optional_utc_iso(value)


# ============================================================
# SENSOR DATA MODELS
# ============================================================

class BasicSensor(BaseModel):
    """
    Minimal sensor representation from Home Assistant.
    Appears in:
    - full basic discovery list
    - delta updates
    """
    id: str = Field(..., max_length=MAX_ENTITY_ID_LENGTH)
    state: SensorState = None
    type: Optional[str] = Field(None, max_length=MAX_ENTITY_ID_LENGTH)


class FullSensor(BaseModel):
    """
    Full sensor metadata returned by HA on poll or change event.
    Contains extended information from HA's entity registry + attributes.

    All fields except `id` have defaults so Basic-shaped payloads
    (`{id, state}` or `{id, state, type}`) validate against FullSensor too.
    """
    id: str = Field(..., max_length=MAX_ENTITY_ID_LENGTH)
    state: SensorState = None
    type: Optional[str] = Field(None, max_length=MAX_ENTITY_ID_LENGTH)
    unit: Optional[str] = Field(None, max_length=MAX_ENTITY_ID_LENGTH)
    attributes: AttributesDict = Field(default_factory=dict)


class SensorsTelemetry(OutboxFields):
    """
    Wrapper for both basic and full sensor data.
    partial = True  -> basic lists or delta updates
    partial = False -> full metadata dump

    `sensors` is `Union[FullSensor, BasicSensor]` with FullSensor FIRST —
    Pydantic's left-to-right Union resolution picks FullSensor, so
    `attributes` / `device_class` are preserved on incoming dicts. The
    BasicSensor arm stays for backwards compatibility with callers that
    construct BasicSensor instances directly (test suites, legacy code).
    """
    partial: bool
    timestamp: Timestamp
    sensors: List[Union[FullSensor, BasicSensor]] = Field(..., max_length=MAX_SENSORS)


# ============================================================
# TELEMETRY — SYSTEM + EVENTS + GENERAL
# ============================================================

class SystemTelemetry(OutboxFields):
    cpu: float = Field(..., ge=0, le=100, allow_inf_nan=False, description="CPU usage percentage")
    ram: float = Field(..., ge=0, le=100, allow_inf_nan=False, description="RAM usage percentage")
    uptime: float = Field(..., ge=0, le=MAX_UPTIME_S, allow_inf_nan=False, description="Uptime in seconds")
    temperature: Optional[float] = Field(
        None, ge=-100, le=250, allow_inf_nan=False, description="System temperature in degrees C"
    )
    # Since v1.2.0, optional (None from older hubs): is Home Assistant feeding
    # the hub? A hub whose Home Assistant websocket is down still sends
    # heartbeats, but no door or motion changes reach the vault.
    ha_connected: Optional[bool] = Field(None, description="Home Assistant websocket connected")
    ha_last_event_at: Optional[str] = Field(None, description="Last event from Home Assistant, UTC ISO 8601")
    # Since v1.3.0, optional (None from older hubs): the last time ANY message
    # (a ping reply, a result or an event) came back over the Home Assistant
    # websocket. Unlike ha_last_event_at it keeps moving in a quiet house, so
    # "connected but quiet" can be told from "feed dead".
    ha_last_message_at: Optional[str] = Field(
        None, description="Last message of any kind from Home Assistant, UTC ISO 8601"
    )

    @field_validator("ha_last_event_at", "ha_last_message_at", mode="before")
    @classmethod
    def _ha_times_utc(cls, value: Any) -> Optional[str]:
        return _optional_utc_iso(value)


class EventTelemetry(OutboxFields):
    event_type: EventType
    timestamp: Timestamp
    details: FreeDict = Field(default_factory=dict)


class GeneralTelemetry(OutboxFields):
    data: FreeDict = Field(default_factory=dict)


# ============================================================
# STATUS MODELS
# ============================================================

class StatusOnline(BaseModel):
    status: str = Field("online", max_length=MAX_STATUS_LENGTH)
    timestamp: Timestamp


class StatusOffline(BaseModel):
    status: str = Field("offline", max_length=MAX_STATUS_LENGTH)
    timestamp: Timestamp


# ============================================================
# COMMAND PAYLOADS (Vault → Hub)
# ============================================================

class CommandBase(BaseModel):
    command_id: str = Field(..., min_length=1, max_length=MAX_COMMAND_ID_LENGTH)


class ConfigUpdateCommand(CommandBase):
    version: int = Field(..., ge=0, le=MAX_SEQ)
    config: FreeDict


class FirmwareUpdateCommand(CommandBase):
    download_url: str = Field(..., max_length=2048)
    checksum: str = Field(..., max_length=256)


class TunnelStartCommand(CommandBase):
    metadata: FreeDict = Field(default_factory=dict)


class TunnelStopCommand(CommandBase):
    metadata: FreeDict = Field(default_factory=dict)


class SensorsPollCommand(CommandBase):
    """
    Vault requests full metadata for ONE sensor.
    entity_id must match e.g. sensor.kitchen_temp
    """
    entity_id: str = Field(..., max_length=MAX_ENTITY_ID_LENGTH)


class SensorsSetCommand(CommandBase):
    """
    Push sensor configuration updates.
    """
    settings: FreeDict = Field(default_factory=dict)


# ============================================================
# ADDON (Home Assistant) PAYLOADS
# ============================================================

class HAAddonTelemetry(OutboxFields):
    state: FreeDict = Field(default_factory=dict)
    timestamp: Timestamp


class HAAddonStatus(BaseModel):
    online: bool
    version: str = Field(..., max_length=64)
    timestamp: Timestamp


class HAAddonCommand(CommandBase):
    action: str = Field(..., max_length=MAX_COMMAND_ID_LENGTH)
    data: FreeDict = Field(default_factory=dict)


# ============================================================
# COMMAND ACKNOWLEDGEMENTS (Hub → Vault)
# ============================================================

class CommandAck(BaseModel):
    command_id: str = Field(..., min_length=1, max_length=MAX_COMMAND_ID_LENGTH)
    status: AckStatus
    message: Optional[str] = Field(None, max_length=MAX_ACK_MESSAGE_LENGTH)
    timestamp: Timestamp


# ============================================================
# STORE AND CONFIRM (protocol 1.1)
# ============================================================

# Telemetry types an outbox record can carry (the last level of the telemetry topic).
OUTBOX_RECORD_TYPES = ("sensors", "system", "events", "general")

# Most records in one catch-up batch. Keeps a batch well under any broker
# message limit and lets the vault commit (and acknowledge) it in one go.
MAX_BATCH_RECORDS = 200


class OutboxRecord(BaseModel):
    """One reading from a hub's outbox, as resent in a `TelemetryBatch`.

    `payload` is exactly what the hub published live on
    `hubs/<id>/v1/telemetry/<type>` (it may repeat `seq` and `event_ts`).
    `queued_at` is when the hub stored the reading, which is not when it
    happened (`event_ts`).
    """
    seq: int = Field(..., ge=1, le=MAX_SEQ)
    type: str
    event_ts: str
    queued_at: Optional[str] = None
    payload: FreeDict = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in OUTBOX_RECORD_TYPES:
            raise ValueError(f"unknown record type {value!r}")
        return value

    @field_validator("event_ts", mode="before")
    @classmethod
    def _event_ts_utc(cls, value: Any) -> str:
        return to_utc_iso(value)

    @field_validator("queued_at", mode="before")
    @classmethod
    def _queued_at_utc(cls, value: Any) -> Optional[str]:
        return _optional_utc_iso(value)


class TelemetryBatch(BaseModel):
    """Readings a hub resends from its outbox (`topics.TELEMETRY_BATCH`).

    Records are oldest first. `hub_time` is the hub's clock when it sent the
    batch, so the vault can tell when the hub's clock is wrong.
    """
    hub_time: str
    outbox_id: Optional[str] = Field(None, min_length=1, max_length=64)
    oldest_seq: Optional[int] = Field(None, ge=1, le=MAX_SEQ)
    records: List[OutboxRecord] = Field(..., min_length=1, max_length=MAX_BATCH_RECORDS)

    @field_validator("hub_time", mode="before")
    @classmethod
    def _hub_time_utc(cls, value: Any) -> str:
        return to_utc_iso(value)


class StoreAck(BaseModel):
    """The vault stored this hub's readings up to `upto` (`topics.STORE_ACK`).

    `upto` is the end of the unbroken run of stored `seq`s (everything up to
    and including it is committed); the hub deletes those. `stored` is how
    many readings the vault stored (or found already stored) since its last
    acknowledgement, for logs. `outbox_id`, when given, names the outbox the
    acknowledgement is for: a hub ignores an acknowledgement for another one.
    """
    upto: int = Field(..., ge=0, le=MAX_SEQ)
    stored: int = Field(0, ge=0, le=MAX_SEQ)
    outbox_id: Optional[str] = Field(None, min_length=1, max_length=64)


def build_store_ack(upto: int, stored: int = 0, outbox_id: Optional[str] = None) -> Dict[str, Any]:
    """A validated `StoreAck` payload, ready for json.dumps (no None fields)."""
    return StoreAck(upto=upto, stored=stored, outbox_id=outbox_id).model_dump(exclude_none=True)


def build_outbox_record(seq: int, record_type: str, event_ts: Any, payload: Dict[str, Any],
                        queued_at: Any = None) -> Dict[str, Any]:
    """A validated `OutboxRecord` dict (times normalised to UTC "Z")."""
    return OutboxRecord(seq=seq, type=record_type, event_ts=event_ts, payload=payload,
                        queued_at=queued_at).model_dump(exclude_none=True)


def build_telemetry_batch(records: List[Dict[str, Any]], hub_time: Any, outbox_id: Optional[str] = None,
                          oldest_seq: Optional[int] = None) -> Dict[str, Any]:
    """A validated `TelemetryBatch` payload, ready for json.dumps (no None fields)."""
    return TelemetryBatch(records=records, hub_time=hub_time, outbox_id=outbox_id,
                          oldest_seq=oldest_seq).model_dump(exclude_none=True)


# ============================================================
# UNION TYPES
# ============================================================

TelemetryPayload = Union[
    SensorsTelemetry,
    SystemTelemetry,
    EventTelemetry,
    GeneralTelemetry,
    HAAddonTelemetry,
]

StatusPayload = Union[
    StatusOnline,
    StatusOffline,
]

CommandPayload = Union[
    ConfigUpdateCommand,
    FirmwareUpdateCommand,
    TunnelStartCommand,
    TunnelStopCommand,
    SensorsPollCommand,
    SensorsSetCommand,
    HAAddonCommand,
]

AckPayload = CommandAck

StoreAckPayload = StoreAck


# ============================================================
# UNIVERSAL PAYLOAD TYPE (For Routers)
# ============================================================

Payload = Union[
    TelemetryPayload,
    StatusPayload,
    CommandPayload,
    AckPayload,
]

