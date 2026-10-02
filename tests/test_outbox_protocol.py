"""Store and confirm (protocol 1.1): outbox fields, catch-up batches, store acks."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from central_core_mqtt_shared import schemas, topics
from central_core_mqtt_shared.schemas import (
    MAX_BATCH_RECORDS,
    OutboxRecord,
    SensorsTelemetry,
    StoreAck,
    SystemTelemetry,
    TelemetryBatch,
    build_outbox_record,
    build_store_ack,
    build_telemetry_batch,
    parse_utc_iso,
    to_utc_iso,
)


class TestTopics:
    def test_store_ack_topic(self):
        assert topics.build_topic(topics.STORE_ACK, hub_id="h1", version=1) == "hubs/h1/v1/ack"

    def test_batch_topic_is_under_telemetry_so_existing_subscriptions_see_it(self):
        assert (
            topics.build_topic(topics.TELEMETRY_BATCH, hub_id="h1", version=1)
            == "hubs/h1/v1/telemetry/batch"
        )

    def test_store_ack_never_matches_the_command_ack_template(self):
        # The vault subscribes to hubs/+/v1/ack/+/+ for command acks; the
        # store ack has no further levels, so neither sees the other.
        store = topics.build_topic(topics.STORE_ACK, hub_id="h", version=1).split("/")
        cmd = topics.build_topic(
            topics.ACK_GENERIC, hub_id="h", version=1, command_name="+", command_id="+"
        ).split("/")
        assert len(store) == 4 and len(cmd) == 6

    def test_new_topics_are_exported(self):
        assert "STORE_ACK" in topics.__all__
        assert "TELEMETRY_BATCH" in topics.__all__


class TestTimes:
    def test_parse_converts_offsets_to_utc(self):
        dt = parse_utc_iso("2026-10-25T01:30:00+01:00")
        assert dt == datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)

    def test_parse_accepts_z_and_datetimes(self):
        assert parse_utc_iso("2026-01-01T00:00:00Z").tzinfo is timezone.utc
        aware = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2)))
        assert parse_utc_iso(aware) == datetime(2025, 12, 31, 22, tzinfo=timezone.utc)

    @pytest.mark.parametrize("bad", ["2026-01-01T00:00:00", "yesterday", "", None, 12,
                                     datetime(2026, 1, 1)])
    def test_parse_refuses_times_without_offset_or_garbage(self, bad):
        with pytest.raises(ValueError):
            parse_utc_iso(bad)

    def test_to_utc_iso_ends_in_z(self):
        assert to_utc_iso("2026-06-01T12:00:00.123456+01:00") == "2026-06-01T11:00:00.123456Z"


class TestOutboxFieldsAreOptional:
    def test_old_sensor_payload_without_seq_still_validates(self):
        t = SensorsTelemetry(partial=True, timestamp=1.0, sensors=[{"id": "x", "state": "on"}])
        assert t.seq is None and t.event_ts is None and t.outbox_id is None

    def test_old_system_payload_without_seq_still_validates(self):
        t = SystemTelemetry(cpu=1, ram=2, uptime=3)
        assert t.seq is None and t.hub_time is None

    def test_sensor_payload_with_outbox_fields(self):
        t = SensorsTelemetry(
            partial=True, timestamp=1.0, sensors=[], seq=7, event_ts="2026-03-29T00:59:59+00:00",
            outbox_id="ob-1", oldest_seq=3, hub_time="2026-03-29T02:00:00+01:00",
        )
        assert t.seq == 7
        assert t.event_ts == "2026-03-29T00:59:59Z"
        assert t.hub_time == "2026-03-29T01:00:00Z"

    @pytest.mark.parametrize("field,value", [("seq", 0), ("seq", -1), ("oldest_seq", 0),
                                             ("event_ts", "2026-01-01T00:00:00"),
                                             ("outbox_id", ""), ("outbox_id", "x" * 65)])
    def test_bad_outbox_fields_are_refused(self, field, value):
        with pytest.raises(ValidationError):
            SensorsTelemetry(partial=True, timestamp=1.0, sensors=[], **{field: value})

    def test_unknown_fields_are_still_ignored(self):
        # A newer hub may add fields; an older reader must not fail on them.
        t = SystemTelemetry(cpu=1, ram=2, uptime=3, some_future_field=True)
        assert not hasattr(t, "some_future_field")


class TestRecordsAndBatches:
    def test_record_normalises_times_and_keeps_payload(self):
        r = OutboxRecord(seq=1, type="sensors", event_ts="2026-01-01T01:00:00+01:00",
                         queued_at="2026-01-01T00:00:05Z", payload={"data": {"a": "on"}})
        assert r.event_ts == "2026-01-01T00:00:00Z"
        assert r.payload == {"data": {"a": "on"}}

    def test_record_requires_event_ts_and_known_type(self):
        with pytest.raises(ValidationError):
            OutboxRecord(seq=1, type="sensors", payload={})
        with pytest.raises(ValidationError):
            OutboxRecord(seq=1, type="cmd", event_ts="2026-01-01T00:00:00Z")

    def test_batch_needs_records_and_hub_time(self):
        with pytest.raises(ValidationError):
            TelemetryBatch(hub_time="2026-01-01T00:00:00Z", records=[])
        with pytest.raises(ValidationError):
            TelemetryBatch(records=[{"seq": 1, "type": "system", "event_ts": "2026-01-01T00:00:00Z"}])

    def test_batch_is_capped(self):
        rec = {"seq": 1, "type": "system", "event_ts": "2026-01-01T00:00:00Z"}
        TelemetryBatch(hub_time="2026-01-01T00:00:00Z", records=[rec] * MAX_BATCH_RECORDS)
        with pytest.raises(ValidationError):
            TelemetryBatch(hub_time="2026-01-01T00:00:00Z", records=[rec] * (MAX_BATCH_RECORDS + 1))

    def test_builders_round_trip(self):
        rec = build_outbox_record(5, "sensors", "2026-01-01T00:00:00+00:00", {"data": {}},
                                  queued_at="2026-01-01T00:00:01Z")
        batch = build_telemetry_batch([rec], hub_time="2026-01-01T00:10:00Z",
                                      outbox_id="ob", oldest_seq=5)
        again = TelemetryBatch.model_validate(batch)
        assert again.records[0].seq == 5
        assert again.records[0].event_ts == "2026-01-01T00:00:00Z"
        assert batch["oldest_seq"] == 5 and batch["outbox_id"] == "ob"

    def test_batch_builder_leaves_out_missing_optional_fields(self):
        rec = build_outbox_record(1, "system", "2026-01-01T00:00:00Z", {})
        batch = build_telemetry_batch([rec], hub_time="2026-01-01T00:00:00Z")
        assert "outbox_id" not in batch and "oldest_seq" not in batch
        assert "queued_at" not in batch["records"][0]


class TestStoreAck:
    def test_build_store_ack(self):
        assert build_store_ack(10, 3) == {"upto": 10, "stored": 3}
        assert build_store_ack(10, 3, "ob")["outbox_id"] == "ob"

    def test_store_ack_defaults_stored_to_zero(self):
        assert StoreAck(upto=0).stored == 0

    @pytest.mark.parametrize("payload", [{"upto": -1}, {"upto": 1, "stored": -1}, {}])
    def test_bad_store_acks_are_refused(self, payload):
        with pytest.raises(ValidationError):
            StoreAck(**payload)

    def test_store_ack_is_exposed_as_a_payload_type(self):
        assert schemas.StoreAckPayload is StoreAck
