"""Ingest: drain Kinesis -> bronze S3. Runs once per orchestrator
invocation and stops (not a long-lived daemon) -- matches the sibling
project's hand-rolled-linear-pipeline philosophy. Per-shard checkpoints
are stored in the manifest table so each run resumes exactly where the
last one left off.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from pipeline import s3_io
from pipeline.aws_clients import kinesis_client
from pipeline.config import KINESIS_STREAM_NAME, S3_BUCKET_NAME
from pipeline.manifest import get_shard_checkpoints, update_shard_checkpoints

logger = logging.getLogger(__name__)

SOURCE_NAME = "opensky_kinesis"


def _shard_iterator(kinesis, shard_id: str, checkpoint: str | None) -> str:
    if checkpoint:
        resp = kinesis.get_shard_iterator(
            StreamName=KINESIS_STREAM_NAME,
            ShardId=shard_id,
            ShardIteratorType="AFTER_SEQUENCE_NUMBER",
            StartingSequenceNumber=checkpoint,
        )
    else:
        resp = kinesis.get_shard_iterator(
            StreamName=KINESIS_STREAM_NAME, ShardId=shard_id, ShardIteratorType="TRIM_HORIZON"
        )
    return resp["ShardIterator"]


def _drain_shard(kinesis, shard_id: str, checkpoint: str | None) -> tuple[list[dict], str | None]:
    """Reads every available record from one shard until GetRecords
    returns nothing new, then stops -- a bounded drain, not a poll loop."""
    records: list[dict] = []
    last_sequence_number = checkpoint
    iterator = _shard_iterator(kinesis, shard_id, checkpoint)

    while iterator:
        resp = kinesis.get_records(ShardIterator=iterator, Limit=1000)
        batch = resp["Records"]
        if not batch:
            break
        for r in batch:
            records.append(json.loads(r["Data"]))
            last_sequence_number = r["SequenceNumber"]
        iterator = resp.get("NextShardIterator")
        if resp.get("MillisBehindLatest", 0) == 0:
            break

    return records, last_sequence_number


def run() -> str | None:
    """Drains all shards, writes everything consumed this run as one
    NDJSON file to bronze, updates shard checkpoints. Returns the S3 key,
    or None if nothing new was in the stream (a real, tested case).
    """
    kinesis = kinesis_client()
    shard_ids = [s["ShardId"] for s in kinesis.list_shards(StreamName=KINESIS_STREAM_NAME)["Shards"]]
    checkpoints = get_shard_checkpoints(SOURCE_NAME)

    all_records: list[dict] = []
    new_checkpoints = dict(checkpoints)
    for shard_id in shard_ids:
        records, last_seq = _drain_shard(kinesis, shard_id, checkpoints.get(shard_id))
        all_records.extend(records)
        if last_seq:
            new_checkpoints[shard_id] = last_seq

    if not all_records:
        logger.info("No new records in Kinesis stream %s", KINESIS_STREAM_NAME)
        return None

    now = datetime.now(timezone.utc)
    s3_key = f"bronze/opensky_states/dt={now:%Y-%m-%d}/{now:%H%M%S}_states_raw.ndjson"
    body = "\n".join(json.dumps(r) for r in all_records).encode()
    s3_io.write_bytes(body, s3_key)

    update_shard_checkpoints(SOURCE_NAME, new_checkpoints)
    logger.info("Drained %d records from Kinesis to s3://%s/%s", len(all_records), S3_BUCKET_NAME, s3_key)
    return s3_key


def handler(event, context) -> dict:
    return {"s3_key": run()}
