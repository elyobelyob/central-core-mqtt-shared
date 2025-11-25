from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Union, List
from enum import Enum


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
# SENSOR DATA MODELS
# ============================================================

class BasicSensor(BaseModel):
    """
    Minimal sensor representation from Home Assistant.
    Appears in:
    - full basic discovery list
    - delta updates
    """
    id: str
    state: Optional[Any] = None
    type: Optional[str] = None


class FullSensor(BaseModel):
    """
    Full sensor metadata returned by HA on poll or change event.
    Contains extended information from HA's entity registry + attributes.
    """
    id: str
    state: Optional[Any]
    type: Optional[str]
    unit: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)


class SensorsTelemetry(BaseModel):
    """
    Wrapper for both basic and full sensor data.
    partial = True  -> basic lists or delta updates
    partial = False -> full metadata dump
    """
    partial: bool
    timestamp: float
    sensors: List[Union[BasicSensor, FullSensor]]


# ============================================================
# TELEMETRY — SYSTEM + EVENTS + GENERAL
# ============================================================

class SystemTelemetry(BaseModel):
    cpu: float = Field(..., description="CPU usage percentage")
    ram: float = Field(..., description="RAM usage percentage")
    uptime: float = Field(..., description="Uptime in seconds")
    temperature: Optional[float] = Field(None, description="System temperature")


class EventTelemetry(BaseModel):
    event_type: EventType
    timestamp: float
    details: Dict[str, Any] = Field(default_factory=dict)


class GeneralTelemetry(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# STATUS MODELS
# ============================================================

class StatusOnline(BaseModel):
    status: str = "online"
    timestamp: float


class StatusOffline(BaseModel):
    status: str = "offline"
    timestamp: float


# ============================================================
# COMMAND PAYLOADS (Vault → Hub)
# ============================================================

class CommandBase(BaseModel):
    command_id: str


class ConfigUpdateCommand(CommandBase):
    version: int
    config: Dict[str, Any]


class FirmwareUpdateCommand(CommandBase):
    download_url: str
    checksum: str


class TunnelStartCommand(CommandBase):
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TunnelStopCommand(CommandBase):
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SensorsPollCommand(CommandBase):
    """
    Vault requests full metadata for ONE sensor.
    entity_id must match e.g. sensor.kitchen_temp
    """
    entity_id: str


class SensorsSetCommand(CommandBase):
    """
    Push sensor configuration updates.
    """
    settings: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# ADDON (Home Assistant) PAYLOADS
# ============================================================

class HAAddonTelemetry(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float


class HAAddonStatus(BaseModel):
    online: bool
    version: str
    timestamp: float


class HAAddonCommand(CommandBase):
    action: str
    data: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# COMMAND ACKNOWLEDGEMENTS (Hub → Vault)
# ============================================================

class CommandAck(BaseModel):
    command_id: str
    status: AckStatus
    message: Optional[str] = None
    timestamp: float


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


# ============================================================
# UNIVERSAL PAYLOAD TYPE (For Routers)
# ============================================================

Payload = Union[
    TelemetryPayload,
    StatusPayload,
    CommandPayload,
    AckPayload,
]

