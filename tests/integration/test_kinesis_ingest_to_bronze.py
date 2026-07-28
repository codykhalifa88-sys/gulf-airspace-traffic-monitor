"""Real Kinesis (against the test moto_server) put -> consume -> bronze
round trip, including the idempotent no-op-on-second-drain case that's
central to this project's "run once, then stop" consumer design."""
import json

from pipeline import s3_io
from pipeline.aws_clients import kinesis_client
from pipeline.config import KINESIS_STREAM_NAME
from pipeline.ingest import kinesis_consumer


def _put_test_records(n: int) -> None:
    kinesis = kinesis_client()
    records = [
        {"Data": json.dumps({"icao24": f"test{i:03d}", "latitude": 25.0, "longitude": 55.0}).encode(), "PartitionKey": f"test{i:03d}"}
        for i in range(n)
    ]
    kinesis.put_records(StreamName=KINESIS_STREAM_NAME, Records=records)


def test_drain_writes_all_records_to_bronze_and_checkpoints(aws_env):
    _put_test_records(5)

    s3_key = kinesis_consumer.run()
    assert s3_key is not None
    assert s3_key.startswith("bronze/opensky_states/")

    body = s3_io.read_bytes(s3_key)
    lines = [json.loads(l) for l in body.decode().splitlines() if l.strip()]
    assert len(lines) == 5
    assert {r["icao24"] for r in lines} == {f"test{i:03d}" for i in range(5)}


def test_draining_again_with_nothing_new_is_a_clean_noop(aws_env):
    _put_test_records(2)
    first_key = kinesis_consumer.run()
    assert first_key is not None

    second_key = kinesis_consumer.run()
    assert second_key is None


def test_a_second_batch_after_a_noop_is_picked_up_correctly(aws_env):
    _put_test_records(1)
    kinesis_consumer.run()
    assert kinesis_consumer.run() is None  # no-op, confirms checkpoint advanced

    _put_test_records(3)
    third_key = kinesis_consumer.run()
    assert third_key is not None
    body = s3_io.read_bytes(third_key)
    lines = [json.loads(l) for l in body.decode().splitlines() if l.strip()]
    # only the 3 NEW records from this batch, not the earlier one already consumed
    assert len(lines) == 3
