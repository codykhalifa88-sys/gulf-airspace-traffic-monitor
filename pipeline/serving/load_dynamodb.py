"""Gold DataFrame <-> DynamoDB serving layer. Thin handler wraps plain,
directly-testable functions -- same pattern as the ev-charging-gap-analysis
sibling. Also owns fetch_recent_history(): the rolling anomaly baseline
needs prior history that lives in DynamoDB itself (this table IS the
per-region time series store), so transform/gold.py reads through this
module rather than duplicating DynamoDB access -- a deliberate, documented
cross-layer read, the same pattern a real streaming system uses when a
transform needs its own materialized state.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pandas as pd
from boto3.dynamodb.conditions import Key

from pipeline.aws_clients import dynamodb_resource
from pipeline.config import DYNAMODB_CONFLICT_EVENTS_TABLE, DYNAMODB_TRAFFIC_TABLE

logger = logging.getLogger(__name__)

# warning-or-worse -- anything at or above this qualifies for the
# gsi1_status_ranked alert index. "normal" and "insufficient_baseline" don't.
_ALERT_STATUSES = {"warning", "serious", "critical"}


def _to_decimal_safe(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return Decimal(str(value))


def fetch_recent_history(regions: list[str], lookback_buckets: int) -> pd.DataFrame:
    """Last `lookback_buckets` rows per region from gulf_traffic_by_region,
    oldest first -- the "preceding window" compute_rolling_baseline_and_anomaly
    needs. Empty DataFrame (right shape) if a region has no prior history yet
    (its first-ever run), which is a normal, expected state, not an error.
    """
    table = dynamodb_resource().Table(DYNAMODB_TRAFFIC_TABLE)
    rows = []
    for region in regions:
        resp = table.query(
            KeyConditionExpression=Key("region_pk").eq(f"REGION#{region}"),
            ScanIndexForward=False,
            Limit=lookback_buckets,
        )
        for item in resp["Items"]:
            rows.append(
                {
                    "region": region,
                    "bucket_sk": pd.Timestamp(item["bucket_sk"].replace("BUCKET#", "")),
                    "aircraft_count": int(item["aircraft_count"]),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["region", "bucket_sk", "aircraft_count"])
    return pd.DataFrame(rows).sort_values(["region", "bucket_sk"]).reset_index(drop=True)


def upsert_traffic_items(traffic_df: pd.DataFrame) -> int:
    """Writes one item per (region, bucket). status_gsi_pk is present ONLY
    for warning-or-worse rows -- DynamoDB doesn't index an item into a GSI
    that's missing the GSI's key attribute, so "normal"/"insufficient_baseline"
    rows simply never show up in the ranked-alert query, without needing a
    filter expression at read time.
    """
    table = dynamodb_resource().Table(DYNAMODB_TRAFFIC_TABLE)
    count = 0
    with table.batch_writer() as batch:
        for _, row in traffic_df.iterrows():
            bucket_iso = row["bucket_sk"].isoformat() if isinstance(row["bucket_sk"], pd.Timestamp) else row["bucket_sk"]
            item = {
                "region_pk": f"REGION#{row['region']}",
                "bucket_sk": f"BUCKET#{bucket_iso}",
                "aircraft_count": _to_decimal_safe(row.get("aircraft_count")),
                "rolling_mean": _to_decimal_safe(row.get("rolling_mean")),
                "rolling_std": _to_decimal_safe(row.get("rolling_std")),
                "z_score": _to_decimal_safe(row.get("z_score")),
                "baseline_n": _to_decimal_safe(row.get("baseline_n")),
                "anomaly_status": row.get("anomaly_status"),
                "anomaly_direction": row.get("anomaly_direction") if pd.notna(row.get("anomaly_direction")) else None,
            }
            if row.get("anomaly_status") in _ALERT_STATUSES:
                item["status_gsi_pk"] = f"STATUS#{row['anomaly_status']}"
            item = {k: v for k, v in item.items() if v is not None}
            batch.put_item(Item=item)
            count += 1
    logger.info("Upserted %d traffic-by-region items", count)
    return count


def upsert_conflict_event_items(events_df: pd.DataFrame) -> int:
    """event_pk is GDELT's own GLOBALEVENTID -- a natural key, so repeated
    pulls across overlapping time windows dedupe for free via idempotent
    upserts rather than needing our own dedup logic."""
    table = dynamodb_resource().Table(DYNAMODB_CONFLICT_EVENTS_TABLE)
    count = 0
    with table.batch_writer() as batch:
        for _, row in events_df.iterrows():
            item = {
                "event_pk": f"EVENT#{row['global_event_id']}",
                "region_gsi_pk": f"REGION#{row['nearest_region']}",
                "event_timestamp": row["event_timestamp"],
                "action_geo_lat": _to_decimal_safe(row.get("action_geo_lat")),
                "action_geo_long": _to_decimal_safe(row.get("action_geo_long")),
                "quad_class": _to_decimal_safe(row.get("quad_class")),
                "goldstein_scale": _to_decimal_safe(row.get("goldstein_scale")),
                "num_mentions": _to_decimal_safe(row.get("num_mentions")),
                "num_sources": _to_decimal_safe(row.get("num_sources")),
                "num_articles": _to_decimal_safe(row.get("num_articles")),
                "actor1_name": row.get("actor1_name") or None,
                "actor2_name": row.get("actor2_name") or None,
                "event_code": row.get("event_code"),
                "source_url": row.get("source_url"),
            }
            item = {k: v for k, v in item.items() if v is not None}
            batch.put_item(Item=item)
            count += 1
    logger.info("Upserted %d conflict-event items", count)
    return count


def run(traffic_df: pd.DataFrame | None, events_df: pd.DataFrame | None = None) -> dict:
    result = {}
    if traffic_df is not None and not traffic_df.empty:
        result["traffic_items"] = upsert_traffic_items(traffic_df)
    if events_df is not None and not events_df.empty:
        result["conflict_event_items"] = upsert_conflict_event_items(events_df)
    return result


def handler(event, context) -> dict:
    """Real-AWS entrypoint. Not exercised locally -- orchestrator.run_pipeline
    calls run() directly with in-memory DataFrames (moto can't execute
    Lambda code without Docker) -- but this reads from S3 like a genuine
    deployment would, not a stub."""
    from pipeline import s3_io

    traffic_df = s3_io.read_parquet(event["gold_traffic_key"]) if event.get("gold_traffic_key") else None
    events_df = s3_io.read_parquet(event["gold_conflict_events_key"]) if event.get("gold_conflict_events_key") else None
    return run(traffic_df, events_df)
