"""Real DynamoDB (against the test moto_server) serving-layer round trip --
specifically the two GSI query patterns that are the whole point of this
project's table design (see docs/data_dictionary.md): "every currently
-flagged region right now" (gulf_traffic_by_region.gsi1_status_ranked) and
"conflict events near region X in the visible time window"
(gulf_conflict_events.gsi1_region_by_time).

Uses obviously-fake region/event codes (never real AIRPORTS codes like DXB)
-- the moto_server + DynamoDB tables here are a session-scoped fixture
shared with every other integration test file, so real airport codes would
leak this test's synthetic rows into e.g. test_s3_bronze_silver_gold.py's
fetch_recent_history() call for that same region, corrupting its rolling-
baseline computation (confirmed: this actually happened during development
-- synthetic tz-naive timestamps under "DXB" mixed with the real pipeline's
tz-aware ones and crashed pandas' sort_values on the combined object-dtype
column)."""
import pandas as pd
from boto3.dynamodb.conditions import Key

from pipeline.aws_clients import dynamodb_resource
from pipeline.config import DYNAMODB_CONFLICT_EVENTS_TABLE, DYNAMODB_TRAFFIC_TABLE
from pipeline.serving.load_dynamodb import fetch_recent_history, upsert_conflict_event_items, upsert_traffic_items


def test_status_gsi_returns_only_warning_or_worse_regions_ranked(aws_env):
    traffic_df = pd.DataFrame(
        {
            "region": ["ZTEST1", "ZTEST2", "ZTEST3", "ZTEST4"],
            "bucket_sk": [pd.Timestamp("2026-01-01T00:00:00", tz="UTC")] * 4,
            "aircraft_count": [50, 5, 40, 45],
            "rolling_mean": [45.0, 20.0, 42.0, 44.0],
            "rolling_std": [3.0, 2.0, 2.0, 1.0],
            "z_score": [1.6, -7.5, -1.0, 1.0],
            "baseline_n": [20, 20, 20, 20],
            "anomaly_status": ["warning", "critical", "normal", "normal"],
            "anomaly_direction": ["spike", "drop", None, None],
        }
    )
    count = upsert_traffic_items(traffic_df)
    assert count == 4

    table = dynamodb_resource().Table(DYNAMODB_TRAFFIC_TABLE)

    # "normal" rows are stored in the base table...
    item = table.get_item(Key={"region_pk": "REGION#ZTEST3", "bucket_sk": "BUCKET#2026-01-01T00:00:00+00:00"}).get("Item")
    assert item is not None
    assert item["anomaly_status"] == "normal"

    # ...but only warning-or-worse rows carry status_gsi_pk, so the ranked
    # alert GSI naturally excludes them without a filter expression.
    critical_resp = table.query(
        IndexName="gsi1_status_ranked",
        KeyConditionExpression=Key("status_gsi_pk").eq("STATUS#critical"),
    )
    assert [i["region_pk"] for i in critical_resp["Items"]] == ["REGION#ZTEST2"]

    warning_resp = table.query(
        IndexName="gsi1_status_ranked",
        KeyConditionExpression=Key("status_gsi_pk").eq("STATUS#warning"),
    )
    assert [i["region_pk"] for i in warning_resp["Items"]] == ["REGION#ZTEST1"]

    normal_resp = table.query(
        IndexName="gsi1_status_ranked",
        KeyConditionExpression=Key("status_gsi_pk").eq("STATUS#normal"),
    )
    assert normal_resp["Items"] == []


def test_fetch_recent_history_reads_back_what_was_upserted(aws_env):
    traffic_df = pd.DataFrame(
        {
            "region": ["ZTEST5", "ZTEST5", "ZTEST5"],
            "bucket_sk": [
                pd.Timestamp("2026-01-01T00:00:00", tz="UTC"),
                pd.Timestamp("2026-01-01T00:05:00", tz="UTC"),
                pd.Timestamp("2026-01-01T00:10:00", tz="UTC"),
            ],
            "aircraft_count": [40, 42, 45],
            "rolling_mean": [None, None, None],
            "rolling_std": [None, None, None],
            "z_score": [None, None, None],
            "baseline_n": [0, 0, 0],
            "anomaly_status": ["insufficient_baseline"] * 3,
            "anomaly_direction": [None, None, None],
        }
    )
    upsert_traffic_items(traffic_df)

    history = fetch_recent_history(["ZTEST5"], lookback_buckets=288)
    assert len(history) == 3
    assert list(history["aircraft_count"]) == [40, 42, 45]  # oldest-first, the preceding-window shape gold.py needs


def test_conflict_events_gsi_supports_region_and_time_query(aws_env):
    events_df = pd.DataFrame(
        {
            "global_event_id": ["ztest-1001", "ztest-1002", "ztest-1003"],
            "nearest_region": ["ZTESTEVT1", "ZTESTEVT1", "ZTESTEVT2"],
            "event_timestamp": ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-01T00:00:00"],
            "action_geo_lat": [33.3, 33.3, 31.9],
            "action_geo_long": [44.4, 44.4, 35.9],
            "quad_class": [4, 3, 3],
            "goldstein_scale": [-9.0, -6.0, -5.0],
            "num_mentions": [50, 10, 5],
            "num_sources": [5, 2, 1],
            "num_articles": [20, 4, 2],
            "actor1_name": ["TESTACTOR1", "TESTACTOR1", "TESTACTOR2"],
            "actor2_name": [None, None, None],
            "event_code": ["190", "180", "172"],
            "source_url": ["http://example.com/1", "http://example.com/2", "http://example.com/3"],
        }
    )
    count = upsert_conflict_event_items(events_df)
    assert count == 3

    table = dynamodb_resource().Table(DYNAMODB_CONFLICT_EVENTS_TABLE)

    # region + time-window query, exactly what the dashboard's GDELT overlay needs
    resp = table.query(
        IndexName="gsi1_region_by_time",
        KeyConditionExpression=Key("region_gsi_pk").eq("REGION#ZTESTEVT1") & Key("event_timestamp").gte("2026-01-01T12:00:00"),
    )
    assert [i["event_pk"] for i in resp["Items"]] == ["EVENT#ztest-1002"]

    # a natural-key (GLOBALEVENTID) re-upsert of the same event dedupes for free
    upsert_conflict_event_items(events_df.iloc[[0]])
    resp = table.query(
        IndexName="gsi1_region_by_time",
        KeyConditionExpression=Key("region_gsi_pk").eq("REGION#ZTESTEVT1"),
    )
    assert len(resp["Items"]) == 2  # still 2, not 3 -- the repeat upsert overwrote, not duplicated
