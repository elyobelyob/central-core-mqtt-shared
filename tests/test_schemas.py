import pytest
from pydantic import ValidationError

from central_core_mqtt_shared.schemas import (
    AckStatus,
    BasicSensor,
    CommandAck,
    CommandName,
    ConfigUpdateCommand,
    EventTelemetry,
    EventType,
    FirmwareUpdateCommand,
    FullSensor,
    GeneralTelemetry,
    HAAddonCommand,
    HAAddonStatus,
    HAAddonTelemetry,
    SensorsPollCommand,
    SensorsSetCommand,
    SensorsTelemetry,
    StatusOffline,
    StatusOnline,
    SystemTelemetry,
    TunnelStartCommand,
    TunnelStopCommand,
)


class TestEnums:
    def test_ack_status_values(self):
        assert AckStatus.SUCCESS.value == "success"
        assert AckStatus.ERROR.value == "error"

    def test_event_type_members(self):
        assert {e.value for e in EventType} == {
            "door",
            "motion",
            "button",
            "power",
            "other",
        }

    def test_command_name_values(self):
        assert CommandName.CONFIG_UPDATE.value == "config.update"
        assert CommandName.ADDON_HA.value == "addon.ha"


class TestBasicSensor:
    def test_requires_id(self):
        with pytest.raises(ValidationError):
            BasicSensor()

    def test_defaults_state_and_type_to_none(self):
        s = BasicSensor(id="sensor.foo")
        assert s.state is None
        assert s.type is None

    def test_accepts_any_state_value(self):
        assert BasicSensor(id="x", state=42).state == 42
        assert BasicSensor(id="x", state="on").state == "on"


class TestFullSensor:
    def test_defaults_attributes_to_empty_dict(self):
        s = FullSensor(id="sensor.foo")
        assert s.attributes == {}
        assert s.unit is None

    def test_preserves_attributes(self):
        s = FullSensor(id="s", attributes={"device_class": "temperature"})
        assert s.attributes["device_class"] == "temperature"

    def test_accepts_basic_shaped_payload(self):
        s = FullSensor.model_validate({"id": "s", "state": "on", "type": "binary"})
        assert s.state == "on"
        assert s.type == "binary"


class TestSensorsTelemetry:
    def test_full_sensor_preferred_over_basic_in_union(self):
        st = SensorsTelemetry.model_validate(
            {
                "partial": False,
                "timestamp": 1.0,
                "sensors": [
                    {"id": "s", "state": 1, "attributes": {"device_class": "temp"}}
                ],
            }
        )
        sensor = st.sensors[0]
        assert isinstance(sensor, FullSensor)
        assert sensor.attributes == {"device_class": "temp"}

    def test_partial_flag_required(self):
        with pytest.raises(ValidationError):
            SensorsTelemetry(timestamp=1.0, sensors=[])

    def test_accepts_basic_sensor_instance(self):
        st = SensorsTelemetry(
            partial=True, timestamp=1.0, sensors=[BasicSensor(id="s")]
        )
        assert len(st.sensors) == 1


class TestSystemTelemetry:
    def test_requires_cpu_ram_uptime(self):
        with pytest.raises(ValidationError):
            SystemTelemetry(cpu=1.0, ram=2.0)

    def test_temperature_optional(self):
        t = SystemTelemetry(cpu=1.0, ram=2.0, uptime=3.0)
        assert t.temperature is None


class TestEventTelemetry:
    def test_event_type_coerced_from_string(self):
        e = EventTelemetry(event_type="door", timestamp=1.0)
        assert e.event_type == EventType.DOOR

    def test_invalid_event_type_rejected(self):
        with pytest.raises(ValidationError):
            EventTelemetry(event_type="invalid", timestamp=1.0)

    def test_details_defaults_empty(self):
        assert EventTelemetry(event_type="motion", timestamp=1.0).details == {}


def test_general_telemetry_defaults():
    assert GeneralTelemetry().data == {}


class TestStatus:
    def test_status_online_default(self):
        s = StatusOnline(timestamp=1.0)
        assert s.status == "online"

    def test_status_offline_default(self):
        s = StatusOffline(timestamp=1.0)
        assert s.status == "offline"


class TestCommands:
    def test_config_update(self):
        c = ConfigUpdateCommand(command_id="c1", version=3, config={"a": 1})
        assert c.version == 3

    def test_firmware_update(self):
        c = FirmwareUpdateCommand(
            command_id="c1", download_url="https://x", checksum="abc"
        )
        assert c.checksum == "abc"

    def test_tunnel_start_metadata_default(self):
        assert TunnelStartCommand(command_id="c1").metadata == {}

    def test_tunnel_stop_metadata_default(self):
        assert TunnelStopCommand(command_id="c1").metadata == {}

    def test_sensors_poll_requires_entity_id(self):
        with pytest.raises(ValidationError):
            SensorsPollCommand(command_id="c1")

    def test_sensors_set_settings_default(self):
        assert SensorsSetCommand(command_id="c1").settings == {}

    def test_command_requires_command_id(self):
        with pytest.raises(ValidationError):
            ConfigUpdateCommand(version=1, config={})


class TestHAAddon:
    def test_telemetry_defaults(self):
        t = HAAddonTelemetry(timestamp=1.0)
        assert t.state == {}

    def test_status_fields(self):
        s = HAAddonStatus(online=True, version="1.2.3", timestamp=1.0)
        assert s.online is True

    def test_command(self):
        c = HAAddonCommand(command_id="c1", action="restart")
        assert c.action == "restart"
        assert c.data == {}


class TestCommandAck:
    def test_success(self):
        a = CommandAck(command_id="c1", status="success", timestamp=1.0)
        assert a.status == AckStatus.SUCCESS
        assert a.message is None

    def test_error_with_message(self):
        a = CommandAck(
            command_id="c1", status=AckStatus.ERROR, message="boom", timestamp=1.0
        )
        assert a.message == "boom"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            CommandAck(command_id="c1", status="maybe", timestamp=1.0)
