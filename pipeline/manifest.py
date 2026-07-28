"""Idempotency/watermark tracking shared by ingest modules -- avoids
re-processing a source that hasn't changed since the last run. Reused
unchanged from the ev-charging-gap-analysis sibling for the static-file
sources (GDELT's own filename timestamp doubles as an etag). The Kinesis
consumer needs a genuinely different shape -- per-shard sequence-number
checkpoints, not a single etag -- added below as shard_checkpoints
functions rather than overloading stored_etag/update_manifest for a shape
they were never designed for."""
from __future__ import annotations

from datetime import datetime, timezone

from pipeline.aws_clients import dynamodb_resource
from pipeline.config import DYNAMODB_MANIFEST_TABLE


def stored_etag(source_name: str) -> str | None:
    table = dynamodb_resource().Table(DYNAMODB_MANIFEST_TABLE)
    item = table.get_item(Key={"source_name": source_name}).get("Item")
    return item.get("source_etag_or_hash") if item else None


def update_manifest(source_name: str, etag: str | None, s3_key: str, status: str) -> None:
    table = dynamodb_resource().Table(DYNAMODB_MANIFEST_TABLE)
    table.put_item(
        Item={
            "source_name": source_name,
            "source_etag_or_hash": etag or "",
            "last_fetched_at": datetime.now(timezone.utc).isoformat(),
            "last_s3_key": s3_key,
            "last_run_status": status,
        }
    )


def get_shard_checkpoints(source_name: str) -> dict[str, str]:
    """Per-shard sequence-number checkpoints (a Map attribute), so the
    Kinesis consumer resumes each shard from where it last left off rather
    than re-reading the whole stream or losing its place."""
    table = dynamodb_resource().Table(DYNAMODB_MANIFEST_TABLE)
    item = table.get_item(Key={"source_name": source_name}).get("Item")
    return item.get("shard_checkpoints", {}) if item else {}


def update_shard_checkpoints(source_name: str, checkpoints: dict[str, str]) -> None:
    table = dynamodb_resource().Table(DYNAMODB_MANIFEST_TABLE)
    table.update_item(
        Key={"source_name": source_name},
        UpdateExpression="SET shard_checkpoints = :c, last_fetched_at = :t, last_run_status = :s",
        ExpressionAttributeValues={
            ":c": checkpoints,
            ":t": datetime.now(timezone.utc).isoformat(),
            ":s": "success",
        },
    )
