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
    ANY_HUB,
    HUB_ID_PATTERN,
    MAX_SEGMENT_LENGTH,
    RESERVED_HUB_IDS,
    STORE_ACK,
    TELEMETRY_BATCH,
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


BAD_HUB_IDS = [
    "", "+", "#", "a/b", "a/#", "hub+", "+/x", "..", ".hidden", "-lead", "has space", "tab\t",
    "new\nline", "nul\x00", "a" * 65, "caf\u00e9", "zero\u200bwidth", "broadcast", None, 7, b"hub",
]


@pytest.mark.parametrize("hub_id", BAD_HUB_IDS)
def test_bad_hub_ids_are_refused_everywhere(hub_id):
    assert not is_valid_hub_id(hub_id)
    with pytest.raises(ValueError):
        validate_hub_id(hub_id)
    with pytest.raises(ValueError):
        build_topic(TELEMETRY_SYSTEM, hub_id=hub_id, version=1)
    # a hub's own command subscription: "+" as its id must not become "every hub"
    with pytest.raises(ValueError):
        build_subscription(CMD_GENERIC, wildcards=("domain", "action"), hub_id=hub_id, version=1)


def test_hub_id_pattern_and_reserved_ids_are_exported():
    assert "broadcast" in RESERVED_HUB_IDS
    assert HUB_ID_PATTERN.startswith("[A-Za-z0-9]")
    assert MAX_SEGMENT_LENGTH == 128
    assert repr(ANY_HUB) == "ANY_HUB"


@pytest.mark.parametrize(
    "value",
    [
        "", "1/../2", "+", "#", None, True, 1.5, b"1", ["1"],
        "x" * (MAX_SEGMENT_LENGTH + 1),
        "\u00e9" * 65,  # 65 characters but 130 UTF-8 bytes
    ],
)
def test_bad_version_is_refused(value):
    with pytest.raises(ValueError):
        build_topic(TELEMETRY_SYSTEM, hub_id="demo-home-001", version=value)


BAD_LEVELS = [
    "", "a/b", "a+b", "#", "+", "id with space", "id\x00", "id\n", "id\t",
    "a\u200bb",  # zero-width space (Cf)
    "a\u202eb",  # right-to-left override (Cf)
    "a\u0085b",  # C1 control (NEL)
    "a\u009bb",  # C1 control (CSI)
    "a\u2028b",  # line separator
    "a\u00a0b",  # no-break space
    "a\ud800b",  # lone surrogate
    "a\ufeffb",  # byte order mark (Cf)
]


@pytest.mark.parametrize("value", BAD_LEVELS)
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


def test_the_length_limit_is_in_utf8_bytes():
    assert build_topic(BROADCAST_CMD, version=1, command="x" * MAX_SEGMENT_LENGTH)
    assert build_topic(BROADCAST_CMD, version=1, command="\u00e9" * 64)  # 128 bytes
    with pytest.raises(ValueError, match="bytes"):
        build_topic(BROADCAST_CMD, version=1, command="\u00e9" * 64 + "x")


def test_printable_unicode_is_allowed_in_non_hub_levels():
    assert build_topic(BROADCAST_CMD, version=1, command="caf\u00e9") == "hubs/broadcast/v1/cmd/caf\u00e9"


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


@pytest.mark.parametrize(
    "template",
    [
        "hubs/{hub_id:>70}/x",
        "hubs/{hub_id!r}/x",
        "hubs/{hub_id!s:.3}/x",
        "hubs/{hub_id.__class__}/x",
        "hubs/{hub_id[0]}/x",
        "hubs/{}/x",
        "hubs/{0}/x",
        "hubs/{hub_id/x",
        "hubs/}/x",
    ],
)
def test_templates_may_only_use_plain_placeholders(template):
    with pytest.raises(ValueError):
        build_topic(template, hub_id="demo-home-001")
    with pytest.raises(ValueError):
        build_subscription(template, hub_id="demo-home-001")


def test_a_template_must_be_a_string():
    with pytest.raises(ValueError):
        build_topic(None, hub_id="h")  # type: ignore[arg-type]


def test_any_hub_is_not_a_topic_value():
    with pytest.raises(ValueError, match="build_subscription"):
        build_topic(TELEMETRY_SYSTEM, hub_id=ANY_HUB, version=1)


class TestBuildSubscription:
    def test_a_hub_subscribes_to_its_own_commands(self):
        assert (
            build_subscription(CMD_GENERIC, wildcards=("domain", "action"), hub_id="demo-home-001", version=1)
            == "hubs/demo-home-001/v1/cmd/+/+"
        )
        # wildcard levels may also be given as "+"
        assert (
            build_subscription(
                CMD_GENERIC, wildcards=["domain", "action"], hub_id="demo-home-001", version=1,
                domain="+", action="+",
            )
            == "hubs/demo-home-001/v1/cmd/+/+"
        )

    def test_the_vault_subscribes_for_every_hub_only_with_any_hub(self):
        assert build_subscription(TELEMETRY_SYSTEM, hub_id=ANY_HUB, version=1) == "hubs/+/v1/telemetry/system"
        assert (
            build_subscription(ACK_GENERIC, wildcards=("command_name", "command_id"), hub_id=ANY_HUB, version=1)
            == "hubs/+/v1/ack/+/+"
        )
        assert build_subscription(TELEMETRY_BATCH, hub_id=ANY_HUB, version=1) == "hubs/+/v1/telemetry/batch"

    def test_without_wildcards_it_renders_a_concrete_topic(self):
        assert build_subscription(STORE_ACK, hub_id="demo-home-001", version=1) == (
            build_topic(STORE_ACK, hub_id="demo-home-001", version=1)
        )

    def test_a_plus_in_a_level_not_named_as_a_wildcard_is_refused(self):
        with pytest.raises(ValueError):
            build_subscription(CMD_GENERIC, wildcards=("domain",), hub_id="h", version=1, action="+")
        with pytest.raises(ValueError):
            build_subscription(TELEMETRY_SYSTEM, hub_id="+", version=1)
        with pytest.raises(ValueError):
            build_subscription(ACK_GENERIC, hub_id=ANY_HUB, version=1, command_name="+", command_id="+")

    def test_hub_id_is_never_a_named_wildcard(self):
        with pytest.raises(ValueError, match="ANY_HUB"):
            build_subscription(TELEMETRY_SYSTEM, wildcards=("hub_id",), version=1)

    def test_a_wildcard_must_fill_a_whole_level(self):
        with pytest.raises(ValueError, match="whole"):
            build_subscription(TELEMETRY_SYSTEM, wildcards=("version",), hub_id="h")  # would give "v+"
        assert build_subscription("{a}/x/{b}", wildcards=("a", "b")) == "+/x/+"
        with pytest.raises(ValueError, match="whole"):
            build_subscription("x{a}/y", wildcards=("a",))
        with pytest.raises(ValueError, match="whole"):
            build_subscription("x/{a}y", wildcards=("a",))

    def test_a_wildcard_level_cannot_be_given_another_value(self):
        with pytest.raises(ValueError, match="wildcard level"):
            build_subscription(CMD_GENERIC, wildcards=("domain", "action"), hub_id="h", version=1, domain="x")

    def test_unknown_wildcard_names_are_refused(self):
        with pytest.raises(ValueError, match="not in the template"):
            build_subscription(TELEMETRY_SYSTEM, wildcards=("domain",), hub_id="h", version=1)

    def test_wildcards_must_be_a_sequence_of_names(self):
        with pytest.raises(ValueError, match="sequence"):
            build_subscription(CMD_GENERIC, wildcards="domain", hub_id="h", version=1, action="a")

    @pytest.mark.parametrize("value", ["#", "hub+", "+x", "a/b", "", "hub/+", "\u202e"])
    def test_still_refuses_bad_values(self, value):
        with pytest.raises(ValueError):
            build_subscription(TELEMETRY_SYSTEM, hub_id=value, version=1)
        with pytest.raises(ValueError):
            build_subscription(TELEMETRY_SYSTEM, hub_id=ANY_HUB, version=value)

    def test_build_topic_never_allows_the_wildcard(self):
        with pytest.raises(ValueError):
            build_topic(TELEMETRY_SYSTEM, hub_id="+", version=1)
        with pytest.raises(ValueError):
            build_topic(CMD_GENERIC, hub_id="h", version=1, domain="+", action="+")


# ------------------------------------------------------------
# Hardening (second review)
# ------------------------------------------------------------


@pytest.mark.parametrize("ch", ["￾", "￿", "﷐", "﷯", "\U0010ffff", "͸"])
def test_non_characters_and_unassigned_code_points_are_refused(ch):
    with pytest.raises(ValueError):
        build_topic(BROADCAST_CMD, version=1, command=f"a{ch}b")


@pytest.mark.parametrize("template", ["hubs/{hub_id}/+/x", "hubs/{hub_id}/#", "hubs/{hub_id}/a+b", "x#/{hub_id}"])
def test_template_text_may_not_contain_wildcards(template):
    with pytest.raises(ValueError, match="may not contain"):
        build_topic(template, hub_id="h")
    with pytest.raises(ValueError, match="may not contain"):
        build_subscription(template, hub_id=ANY_HUB)


def test_the_hub_level_is_found_by_position_not_by_name():
    tpl = "hubs/{hid}/v1/cmd/{domain}/{action}"
    assert build_subscription(tpl, wildcards=("domain", "action"), hid="demo-home-001") == (
        "hubs/demo-home-001/v1/cmd/+/+"
    )
    assert build_subscription(tpl, wildcards=("domain", "action"), hid=ANY_HUB) == "hubs/+/v1/cmd/+/+"
    for bad in ("+", "a/b", "broadcast"):
        with pytest.raises(ValueError):
            build_topic(tpl, hid=bad, domain="d", action="a")
    with pytest.raises(ValueError, match="ANY_HUB"):
        build_subscription(tpl, wildcards=("hid", "domain", "action"))


def test_any_hub_only_fills_the_hub_level():
    with pytest.raises(ValueError, match="only for the hub level"):
        build_subscription(CMD_GENERIC, wildcards=("action",), hub_id="h", version=1, domain=ANY_HUB)
    with pytest.raises(ValueError, match="only for the hub level"):
        build_subscription("x/{hub_id}/y", hub_id=ANY_HUB)  # named hub_id, but not in the hub position


def test_a_hub_id_placeholder_anywhere_is_checked_as_a_hub_id():
    with pytest.raises(ValueError, match="invalid hub id"):
        build_topic("x/{hub_id}/y", hub_id="café")
    assert build_topic("x/{hub_id}/y", hub_id="demo-home-001") == "x/demo-home-001/y"


def test_every_occurrence_of_a_wildcard_must_fill_a_whole_level():
    assert build_subscription("{a}/x/{a}", wildcards=("a",)) == "+/x/+"
    with pytest.raises(ValueError, match="whole"):
        build_subscription("{a}/x/v{a}", wildcards=("a",))
    with pytest.raises(ValueError, match="whole"):
        build_subscription("v{a}/x/{a}", wildcards=("a",))


@pytest.mark.parametrize("wildcards", [None, "domain", b"domain", ("domain", 1), [None]])
def test_wildcards_must_be_names(wildcards):
    with pytest.raises(ValueError, match="sequence of level names"):
        build_subscription(CMD_GENERIC, wildcards=wildcards, hub_id="h", version=1, action="a", domain="d")


def test_a_wildcard_value_must_be_a_plain_plus():
    class Plus(str):
        def __eq__(self, other):
            return True

        __hash__ = str.__hash__

    with pytest.raises(ValueError, match="wildcard level"):
        build_subscription(CMD_GENERIC, wildcards=("domain", "action"), hub_id="h", version=1, domain=Plus("x"))


def test_a_str_subclass_cannot_change_what_was_checked():
    class Sneaky(str):
        def __str__(self):
            return "+"

        def __format__(self, spec):
            return "#"

    # a hub id must be an exact str
    assert not is_valid_hub_id(Sneaky("demo-home-001"))
    with pytest.raises(ValueError):
        build_topic(TELEMETRY_SYSTEM, hub_id=Sneaky("demo-home-001"), version=1)
    # other levels use the characters themselves, never the subclass's rendering
    assert build_topic(BROADCAST_CMD, version=1, command=Sneaky("restart")) == "hubs/broadcast/v1/cmd/restart"


def test_an_int_subclass_renders_as_its_value():
    class Odd(int):
        def __str__(self):
            return "+"

        def __repr__(self):
            return "#"

        def __format__(self, spec):
            return "/"

    assert build_topic(TELEMETRY_SYSTEM, hub_id="h", version=Odd(1)) == "hubs/h/v1/telemetry/system"


def test_any_hub_is_a_singleton_through_copy_and_pickle():
    import copy
    import pickle

    assert copy.copy(ANY_HUB) is ANY_HUB
    assert copy.deepcopy(ANY_HUB) is ANY_HUB
    assert copy.deepcopy({"hub_id": ANY_HUB})["hub_id"] is ANY_HUB
    assert pickle.loads(pickle.dumps(ANY_HUB)) is ANY_HUB
