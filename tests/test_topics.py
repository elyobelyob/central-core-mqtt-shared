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


# ------------------------------------------------------------
# Topic validation: a value must never change the shape of a topic
# ------------------------------------------------------------

from central_core_mqtt_shared.topics import (  # noqa: E402
    HUB_ID_PATTERN,
    MAX_SEGMENT_LENGTH,
    RESERVED_HUB_IDS,
    STORE_ACK,
    build_subscription,
    is_valid_hub_id,
    validate_hub_id,
)


@pytest.mark.parametrize(
    "hub_id",
    ["demo-home-001", "abc-001", "h", "1", "hub_1", "Hub.Larkspur", "a" * 64],
)
def test_ordinary_hub_ids_are_accepted(hub_id):
    assert is_valid_hub_id(hub_id)
    assert validate_hub_id(hub_id) == hub_id
    assert build_topic(TELEMETRY_SYSTEM, hub_id=hub_id, version=1) == (
        f"hubs/{hub_id}/v1/telemetry/system"
    )


@pytest.mark.parametrize(
    "hub_id",
    [
        "",
        "+",
        "#",
        "a/b",
        "a/#",
        "hub+",
        "+/x",
        "..",
        ".hidden",
        "-lead",
        "has space",
        "tab\t",
        "new\nline",
        "nul\x00",
        "a" * 65,
        "café",
        "broadcast",
        None,
        7,
        b"hub",
    ],
)
def test_bad_hub_ids_are_refused(hub_id):
    assert not is_valid_hub_id(hub_id)
    with pytest.raises(ValueError):
        validate_hub_id(hub_id)
    with pytest.raises(ValueError):
        build_topic(TELEMETRY_SYSTEM, hub_id=hub_id, version=1)
    if hub_id != "+":  # the vault may subscribe with "+"; nothing else gets through
        with pytest.raises(ValueError):
            build_subscription(TELEMETRY_SYSTEM, hub_id=hub_id, version=1)


def test_hub_id_pattern_and_reserved_ids_are_exported():
    assert "broadcast" in RESERVED_HUB_IDS
    assert HUB_ID_PATTERN.startswith("[A-Za-z0-9]")
    assert MAX_SEGMENT_LENGTH == 128


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", ""),
        ("version", "1/../2"),
        ("version", "+"),
        ("version", "#"),
        ("version", None),
        ("version", "x" * (MAX_SEGMENT_LENGTH + 1)),
    ],
)
def test_bad_version_is_refused(field, value):
    kwargs = {"hub_id": "demo-home-001", "version": 1}
    kwargs[field] = value
    with pytest.raises(ValueError):
        build_topic(TELEMETRY_SYSTEM, **kwargs)


@pytest.mark.parametrize("value", ["", "a/b", "a+b", "#", "+", "id with space", "id\x00", "id\n"])
def test_bad_command_levels_are_refused(value):
    with pytest.raises(ValueError):
        build_topic(CMD_GENERIC, hub_id="demo-home-001", version=1, domain=value, action="run")
    with pytest.raises(ValueError):
        build_topic(CMD_GENERIC, hub_id="demo-home-001", version=1, domain="diag", action=value)
    with pytest.raises(ValueError):
        build_topic(
            ACK_GENERIC,
            hub_id="demo-home-001",
            version=1,
            command_name="config.update",
            command_id=value,
        )
    with pytest.raises(ValueError):
        build_topic(BROADCAST_CMD, version=1, command=value)


def test_vault_style_command_ids_are_accepted():
    # secrets.token_urlsafe() output contains "-" and "_".
    assert (
        build_topic(
            ACK_GENERIC,
            hub_id="demo-home-001",
            version=1,
            command_name="config.update",
            command_id="Ab-_9xYz0123456789abcd",
        )
        == "hubs/demo-home-001/v1/ack/config.update/Ab-_9xYz0123456789abcd"
    )


def test_unused_extra_kwargs_are_not_validated():
    assert (
        build_topic(TELEMETRY_SYSTEM, hub_id="h", version=1, unused="a/b#+")
        == "hubs/h/v1/telemetry/system"
    )


def test_build_topic_still_reports_a_missing_placeholder_as_key_error():
    with pytest.raises(KeyError):
        build_topic(CMD_GENERIC, hub_id="h", version=1, domain="d")


class TestBuildSubscription:
    def test_allows_the_single_level_wildcard_for_the_vault(self):
        assert (
            build_subscription(TELEMETRY_SYSTEM, hub_id="+", version=1)
            == "hubs/+/v1/telemetry/system"
        )
        assert (
            build_subscription(
                ACK_GENERIC, hub_id="+", version=1, command_name="+", command_id="+"
            )
            == "hubs/+/v1/ack/+/+"
        )

    def test_renders_a_concrete_hub_like_build_topic(self):
        assert build_subscription(STORE_ACK, hub_id="demo-home-001", version=1) == (
            build_topic(STORE_ACK, hub_id="demo-home-001", version=1)
        )

    @pytest.mark.parametrize("value", ["#", "hub+", "+x", "a/b", "", "hub/+"])
    def test_still_refuses_everything_else(self, value):
        with pytest.raises(ValueError):
            build_subscription(TELEMETRY_SYSTEM, hub_id=value, version=1)
        with pytest.raises(ValueError):
            build_subscription(TELEMETRY_SYSTEM, hub_id="+", version=value)

    def test_build_topic_never_allows_the_wildcard(self):
        with pytest.raises(ValueError):
            build_topic(TELEMETRY_SYSTEM, hub_id="+", version=1)
