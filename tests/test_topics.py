import pytest

from central_core_mqtt_shared import topics
from central_core_mqtt_shared.topics import (
    ACK_GENERIC,
    ADDON_HA_CMD,
    ADDON_HA_STATUS,
    ADDON_HA_TELEMETRY,
    BROADCAST_CMD,
    CMD_CONFIG_UPDATE,
    CMD_FIRMWARE_UPDATE,
    CMD_GENERIC,
    CMD_SENSORS_POLL,
    CMD_SENSORS_SET,
    CMD_TUNNEL_START,
    CMD_TUNNEL_STOP,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    TELEMETRY_EVENTS,
    TELEMETRY_GENERAL,
    TELEMETRY_SENSORS,
    TELEMETRY_SYSTEM,
    build_topic,
)


class TestBuildTopic:
    def test_renders_hub_id_and_version(self):
        assert (
            build_topic(TELEMETRY_SYSTEM, hub_id="hub123", version=1)
            == "hubs/hub123/v1/telemetry/system"
        )

    def test_renders_generic_cmd_with_domain_and_action(self):
        assert (
            build_topic(CMD_GENERIC, hub_id="h", version=2, domain="diag", action="run")
            == "hubs/h/v2/cmd/diag/run"
        )

    def test_renders_ack_with_command_name_and_id(self):
        assert (
            build_topic(
                ACK_GENERIC,
                hub_id="h",
                version=1,
                command_name="config.update",
                command_id="abc",
            )
            == "hubs/h/v1/ack/config.update/abc"
        )

    def test_renders_broadcast_without_hub_id(self):
        assert (
            build_topic(BROADCAST_CMD, version=1, command="reboot")
            == "hubs/broadcast/v1/cmd/reboot"
        )

    def test_renders_addon_ha_cmd(self):
        assert (
            build_topic(ADDON_HA_CMD, hub_id="h", version=1, command="restart")
            == "hubs/h/v1/addon/ha/cmd/restart"
        )

    def test_missing_placeholder_raises_key_error(self):
        with pytest.raises(KeyError):
            build_topic(TELEMETRY_SYSTEM, hub_id="h")

    def test_extra_kwargs_are_ignored(self):
        assert (
            build_topic(TELEMETRY_SYSTEM, hub_id="h", version=1, extra="x")
            == "hubs/h/v1/telemetry/system"
        )


@pytest.mark.parametrize(
    "template,expected_suffix",
    [
        (TELEMETRY_SYSTEM, "telemetry/system"),
        (TELEMETRY_SENSORS, "telemetry/sensors"),
        (TELEMETRY_EVENTS, "telemetry/events"),
        (TELEMETRY_GENERAL, "telemetry/general"),
        (STATUS_ONLINE, "status/online"),
        (STATUS_OFFLINE, "status/offline"),
        (CMD_CONFIG_UPDATE, "cmd/config/update"),
        (CMD_FIRMWARE_UPDATE, "cmd/firmware/update"),
        (CMD_TUNNEL_START, "cmd/tunnel/start"),
        (CMD_TUNNEL_STOP, "cmd/tunnel/stop"),
        (CMD_SENSORS_POLL, "cmd/sensors/poll"),
        (CMD_SENSORS_SET, "cmd/sensors/set"),
        (ADDON_HA_TELEMETRY, "addon/ha/telemetry"),
        (ADDON_HA_STATUS, "addon/ha/status"),
    ],
)
def test_hub_scoped_templates_have_expected_suffix(template, expected_suffix):
    rendered = build_topic(template, hub_id="h", version=1)
    assert rendered == f"hubs/h/v1/{expected_suffix}"


def test_public_exports_are_importable():
    for name in topics.__all__:
        assert hasattr(topics, name), f"{name} listed in __all__ but not defined"
