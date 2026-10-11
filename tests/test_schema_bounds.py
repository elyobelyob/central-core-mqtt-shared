"""Upper bounds: numbers, strings and lists that arrive off the network."""
import pytest
from pydantic import ValidationError

from central_core_mqtt_shared import schemas
from central_core_mqtt_shared.schemas import (
    MAX_ACK_MESSAGE_LENGTH,
    MAX_COMMAND_ID_LENGTH,
    MAX_ENTITY_ID_LENGTH,
    MAX_SENSORS,
    MAX_SEQ,
    MAX_TIME_LENGTH,
    BasicSensor,
    CommandAck,
    ConfigUpdateCommand,
    EventTelemetry,
    FirmwareUpdateCommand,
    FullSensor,
    HAAddonCommand,
    HAAddonStatus,
    HAAddonTelemetry,
    OutboxFields,
    OutboxRecord,
    SensorsPollCommand,
    SensorsTelemetry,
    StatusOffline,
    StatusOnline,
    StoreAck,
    TelemetryBatch,
    build_store_ack,
    parse_utc_iso,
)

TS = "2026-10-01T10:00:00Z"


def test_max_seq_is_the_signed_64_bit_limit():
    assert MAX_SEQ == 9223372036854775807


class TestSequenceNumbersAreBounded:
    def test_the_largest_value_is_accepted(self):
        assert OutboxFields(seq=MAX_SEQ, oldest_seq=MAX_SEQ).seq == MAX_SEQ
        assert OutboxRecord(seq=MAX_SEQ, type="system", event_ts=TS).seq == MAX_SEQ
        assert StoreAck(upto=MAX_SEQ, stored=MAX_SEQ).upto == MAX_SEQ

    @pytest.mark.parametrize("field", ["seq", "oldest_seq"])
    def test_outbox_fields_refuse_more_than_64_bit(self, field):
        with pytest.raises(ValidationError):
            OutboxFields(**{field: MAX_SEQ + 1})

    def test_outbox_record_seq_refuses_more_than_64_bit(self):
        with pytest.raises(ValidationError):
            OutboxRecord(seq=MAX_SEQ + 1, type="system", event_ts=TS)
        with pytest.raises(ValidationError):
            OutboxRecord(seq=10**40, type="system", event_ts=TS)

    def test_batch_oldest_seq_refuses_more_than_64_bit(self):
        record = {"seq": 1, "type": "system", "event_ts": TS}
        with pytest.raises(ValidationError):
            TelemetryBatch(hub_time=TS, oldest_seq=MAX_SEQ + 1, records=[record])

    @pytest.mark.parametrize("field", ["upto", "stored"])
    def test_store_ack_refuses_more_than_64_bit(self, field):
        values = {"upto": 1, "stored": 1}
        values[field] = MAX_SEQ + 1
        with pytest.raises(ValidationError):
            StoreAck(**values)
        with pytest.raises(ValidationError):
            build_store_ack(**values)

    def test_store_ack_still_refuses_negatives(self):
        with pytest.raises(ValidationError):
            StoreAck(upto=-1)
        with pytest.raises(ValidationError):
            StoreAck(upto=0, stored=-1)

    def test_config_version_is_bounded(self):
        assert ConfigUpdateCommand(command_id="c1", version=0, config={}).version == 0
        with pytest.raises(ValidationError):
            ConfigUpdateCommand(command_id="c1", version=MAX_SEQ + 1, config={})
        with pytest.raises(ValidationError):
            ConfigUpdateCommand(command_id="c1", version=-1, config={})


class TestTimesAreBounded:
    def test_overlong_time_string_is_refused_before_parsing(self):
        with pytest.raises(ValueError):
            parse_utc_iso("2026-10-01T10:00:00Z" + " " * MAX_TIME_LENGTH + "x")

    def test_overlong_time_is_refused_in_a_message(self):
        with pytest.raises(ValidationError):
            OutboxFields(event_ts="2026-10-01T10:00:00+00:00" + "0" * 100)

    def test_a_normal_time_still_parses(self):
        assert parse_utc_iso("2026-10-01T10:00:00.123456+01:00").hour == 9


class TestTextAndListsAreBounded:
    def test_sensor_ids_are_bounded(self):
        BasicSensor(id="s" * MAX_ENTITY_ID_LENGTH)
        FullSensor(id="s" * MAX_ENTITY_ID_LENGTH, unit="u" * MAX_ENTITY_ID_LENGTH)
        for model in (BasicSensor, FullSensor):
            with pytest.raises(ValidationError):
                model(id="s" * (MAX_ENTITY_ID_LENGTH + 1))
            with pytest.raises(ValidationError):
                model(id="ok", type="t" * (MAX_ENTITY_ID_LENGTH + 1))
        with pytest.raises(ValidationError):
            FullSensor(id="ok", unit="u" * (MAX_ENTITY_ID_LENGTH + 1))

    def test_sensor_list_is_bounded(self):
        sensors = [{"id": "binary_sensor.a"}] * MAX_SENSORS
        assert len(SensorsTelemetry(partial=True, timestamp=1.0, sensors=sensors).sensors) == MAX_SENSORS
        with pytest.raises(ValidationError):
            SensorsTelemetry(partial=True, timestamp=1.0, sensors=sensors + [{"id": "x"}])

    def test_command_ids_are_bounded_and_not_empty(self):
        long_id = "c" * (MAX_COMMAND_ID_LENGTH + 1)
        for make in (
            lambda cid: SensorsPollCommand(command_id=cid, entity_id="sensor.a"),
            lambda cid: HAAddonCommand(command_id=cid, action="restart"),
            lambda cid: CommandAck(command_id=cid, status="success", timestamp=1.0),
        ):
            make("c" * MAX_COMMAND_ID_LENGTH)
            make("Ab-_9xYz0123456789abcd")  # what secrets.token_urlsafe(16) gives
            for bad in ("", long_id):
                with pytest.raises(ValidationError):
                    make(bad)

    def test_command_fields_are_bounded(self):
        with pytest.raises(ValidationError):
            SensorsPollCommand(command_id="c", entity_id="e" * (MAX_ENTITY_ID_LENGTH + 1))
        with pytest.raises(ValidationError):
            FirmwareUpdateCommand(command_id="c", download_url="h" * 2049, checksum="x")
        with pytest.raises(ValidationError):
            FirmwareUpdateCommand(command_id="c", download_url="https://example.test/f", checksum="x" * 257)
        with pytest.raises(ValidationError):
            HAAddonCommand(command_id="c", action="a" * (MAX_COMMAND_ID_LENGTH + 1))
        with pytest.raises(ValidationError):
            HAAddonStatus(online=True, version="v" * 65, timestamp=1.0)

    def test_ack_message_is_bounded(self):
        CommandAck(command_id="c", status="error", message="m" * MAX_ACK_MESSAGE_LENGTH, timestamp=1.0)
        with pytest.raises(ValidationError):
            CommandAck(
                command_id="c", status="error", message="m" * (MAX_ACK_MESSAGE_LENGTH + 1), timestamp=1.0
            )


class TestTimestampsAreFinite:
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_timestamps_are_refused(self, bad):
        with pytest.raises(ValidationError):
            SensorsTelemetry(partial=True, timestamp=bad, sensors=[])
        with pytest.raises(ValidationError):
            EventTelemetry(event_type="door", timestamp=bad)
        with pytest.raises(ValidationError):
            StatusOnline(timestamp=bad)
        with pytest.raises(ValidationError):
            StatusOffline(timestamp=bad)
        with pytest.raises(ValidationError):
            HAAddonTelemetry(timestamp=bad)
        with pytest.raises(ValidationError):
            HAAddonStatus(online=True, version="1", timestamp=bad)
        with pytest.raises(ValidationError):
            CommandAck(command_id="c", status="success", timestamp=bad)

    def test_ordinary_timestamps_are_accepted(self):
        assert StatusOnline(timestamp=1760000000.5).timestamp == 1760000000.5


def test_limits_are_module_level_constants():
    assert schemas.MAX_SENSORS == 10_000


# ------------------------------------------------------------
# Times, system readings and free-form dicts (v1.2.0)
# ------------------------------------------------------------

from central_core_mqtt_shared.schemas import (  # noqa: E402
    MAX_DICT_KEYS,
    MAX_TIMESTAMP,
    MAX_UPTIME_S,
    ConfigUpdateCommand as _Config,
    GeneralTelemetry,
    SystemTelemetry,
    TunnelStartCommand,
)


@pytest.mark.parametrize(
    "value",
    [
        "9999-12-31T23:59:59-05:00",  # overflows when moved to UTC
        "0001-01-01T00:00:00+05:00",
        "3000-01-01T00:00:00Z",
        "2999-12-31T23:00:00-02:00",  # the year 3000 in UTC
    ],
)
def test_times_out_of_range_are_a_validation_error_not_an_overflow(value):
    with pytest.raises(ValueError):
        parse_utc_iso(value)
    with pytest.raises(ValidationError):
        OutboxFields(event_ts=value)


def test_the_last_year_is_accepted():
    assert parse_utc_iso("2999-12-31T23:59:59Z").year == 2999


@pytest.mark.parametrize("bad", [-1.0, MAX_TIMESTAMP, 1e300])
def test_epoch_timestamps_are_bounded(bad):
    with pytest.raises(ValidationError):
        StatusOnline(timestamp=bad)
    with pytest.raises(ValidationError):
        CommandAck(command_id="c", status="success", timestamp=bad)


def test_epoch_timestamp_edges():
    assert StatusOnline(timestamp=0).timestamp == 0
    assert StatusOnline(timestamp=MAX_TIMESTAMP - 1).timestamp == MAX_TIMESTAMP - 1


GOOD_SYSTEM = {"cpu": 12.5, "ram": 40.0, "uptime": 3600.0, "temperature": 48.0}


def test_ordinary_system_readings_are_accepted():
    assert SystemTelemetry(**GOOD_SYSTEM).cpu == 12.5
    assert SystemTelemetry(cpu=0, ram=100, uptime=0).temperature is None


@pytest.mark.parametrize(
    "field,bad",
    [
        ("cpu", -0.1), ("cpu", 100.1), ("cpu", float("nan")), ("cpu", float("inf")),
        ("ram", -1), ("ram", 101), ("ram", float("nan")),
        ("uptime", -1), ("uptime", MAX_UPTIME_S + 1), ("uptime", float("inf")),
        ("temperature", -101), ("temperature", 251), ("temperature", float("nan")),
    ],
)
def test_system_readings_out_of_range_are_refused(field, bad):
    with pytest.raises(ValidationError):
        SystemTelemetry(**dict(GOOD_SYSTEM, **{field: bad}))


def test_free_form_dicts_are_capped():
    big = {f"k{i}": i for i in range(MAX_DICT_KEYS + 1)}
    ok = {f"k{i}": i for i in range(MAX_DICT_KEYS)}
    assert len(FullSensor(id="sensor.a", attributes=ok).attributes) == MAX_DICT_KEYS
    for make in (
        lambda d: FullSensor(id="sensor.a", attributes=d),
        lambda d: EventTelemetry(event_type="door", timestamp=1.0, details=d),
        lambda d: GeneralTelemetry(data=d),
        lambda d: _Config(command_id="c", version=1, config=d),
        lambda d: TunnelStartCommand(command_id="c", metadata=d),
        lambda d: HAAddonTelemetry(timestamp=1.0, state=d),
        lambda d: HAAddonCommand(command_id="c", action="a", data=d),
        lambda d: OutboxRecord(seq=1, type="system", event_ts=TS, payload=d),
    ):
        with pytest.raises(ValidationError):
            make(big)
