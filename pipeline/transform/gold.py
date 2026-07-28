"""Silver -> gold: traffic-volume aggregation and rolling-baseline anomaly
detection -- the actual analytical value of this pipeline. Pure functions
(DataFrame in, DataFrame out); run()/handler() at the bottom do the S3 I/O.
"""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from pipeline import s3_io
from pipeline.config import BUCKET_MINUTES, ROLLING_BASELINE_MAX_BUCKETS, ROLLING_BASELINE_MIN_BUCKETS

logger = logging.getLogger(__name__)

_STD_FLOOR = 1.0  # aircraft-count units -- prevents low-traffic airports' tiny variance from reading as huge z-scores

_STATUS_THRESHOLDS = [
    (1.5, "normal"),
    (2.5, "warning"),
    (3.5, "serious"),
]
_CRITICAL_STATUS = "critical"
_INSUFFICIENT_BASELINE_STATUS = "insufficient_baseline"


def aggregate_traffic_by_region_bucket(states_df: pd.DataFrame, bucket_minutes: int = BUCKET_MINUTES) -> pd.DataFrame:
    """[nearest_region, poll_timestamp] -> [region, bucket_sk, aircraft_count].

    Critical correctness property: a bucket row exists ONLY when a poll
    actually happened and produced data for that region -- this is a plain
    groupby over the real input rows, never a resample/reindex that would
    backfill a "0" for a bucket where the scheduled run was simply missed
    or ran late. Conflating "no data collected" with "genuinely zero
    aircraft observed" would silently manufacture fake traffic-collapse
    anomalies out of ordinary CI/scheduling lag.
    """
    if states_df.empty:
        return pd.DataFrame(columns=["region", "bucket_sk", "aircraft_count"])

    df = states_df.copy()
    ts = pd.to_datetime(df["poll_timestamp"], unit="s", utc=True)
    floor_freq = f"{bucket_minutes}min"
    df["bucket_sk"] = ts.dt.floor(floor_freq)

    grouped = df.groupby(["nearest_region", "bucket_sk"])["icao24"].nunique().reset_index()
    grouped = grouped.rename(columns={"nearest_region": "region", "icao24": "aircraft_count"})
    return grouped.sort_values(["region", "bucket_sk"]).reset_index(drop=True)


def _status_for_z(abs_z: float) -> str:
    for threshold, status in _STATUS_THRESHOLDS:
        if abs_z < threshold:
            return status
    return _CRITICAL_STATUS


def compute_rolling_baseline_and_anomaly(traffic_df: pd.DataFrame) -> pd.DataFrame:
    """Per region, computes a rolling mean/std over the PRECEDING window
    only (never including the current bucket -- shift(1) before rolling),
    then a z-score and a status tier. Regions with fewer than
    ROLLING_BASELINE_MIN_BUCKETS of prior history get
    "insufficient_baseline" rather than a judgment call on too little data.

    anomaly_direction ("spike" vs "drop") is surfaced separately from
    status: a spike (z>0) is often perfectly ordinary (e.g. real seasonal
    demand -- Hajj/Umrah season traffic into JED), while a drop (z<0) is
    the operationally meaningful "possible disruption" signal this
    project's GDELT correlation cares about. Conflating the two would
    treat a legitimate surge as equally suspicious as a collapse.
    """
    if traffic_df.empty:
        return traffic_df.assign(
            rolling_mean=pd.Series(dtype=float),
            rolling_std=pd.Series(dtype=float),
            z_score=pd.Series(dtype=float),
            baseline_n=pd.Series(dtype=int),
            anomaly_status=pd.Series(dtype=object),
            anomaly_direction=pd.Series(dtype=object),
        )

    df = traffic_df.sort_values(["region", "bucket_sk"]).reset_index(drop=True)
    out_frames = []
    for region, group in df.groupby("region"):
        group = group.copy()
        # window must be >= min_periods or pandas rejects it outright; when
        # there's less history than ROLLING_BASELINE_MIN_BUCKETS, using
        # MIN_BUCKETS as the window still correctly yields all-NaN (0
        # windows satisfy min_periods), which baseline_n/has_baseline below
        # turns into "insufficient_baseline" rather than a bogus ValueError.
        window = max(ROLLING_BASELINE_MIN_BUCKETS, min(len(group), ROLLING_BASELINE_MAX_BUCKETS))
        preceding = group["aircraft_count"].shift(1)
        group["rolling_mean"] = preceding.rolling(window=window, min_periods=ROLLING_BASELINE_MIN_BUCKETS).mean()
        group["rolling_std"] = preceding.rolling(window=window, min_periods=ROLLING_BASELINE_MIN_BUCKETS).std()
        group["baseline_n"] = preceding.expanding().count().clip(upper=window)
        out_frames.append(group)

    result = pd.concat(out_frames, ignore_index=True)

    has_baseline = result["baseline_n"] >= ROLLING_BASELINE_MIN_BUCKETS
    std_floor = result["rolling_std"].clip(lower=_STD_FLOOR)
    z = (result["aircraft_count"] - result["rolling_mean"]) / std_floor

    result["z_score"] = z.where(has_baseline)
    result["anomaly_status"] = np.where(
        has_baseline,
        result["z_score"].abs().apply(_status_for_z),
        _INSUFFICIENT_BASELINE_STATUS,
    )
    result["anomaly_direction"] = None
    spike = has_baseline & (result["z_score"] > 0) & (result["anomaly_status"] != "normal")
    drop = has_baseline & (result["z_score"] < 0) & (result["anomaly_status"] != "normal")
    result.loc[spike, "anomaly_direction"] = "spike"
    result.loc[drop, "anomaly_direction"] = "drop"

    return result


def _gold_traffic(silver_keys: dict[str, str], snapshot: str) -> str | None:
    """The rolling baseline needs prior history, which lives in DynamoDB
    (the per-region time series store) rather than in this run's isolated
    batch -- a single ingest cycle typically produces only one bucket per
    region, never enough on its own for ROLLING_BASELINE_MIN_BUCKETS. So
    this reads recent history via serving.load_dynamodb.fetch_recent_history,
    combines it with this run's new bucket(s), computes anomaly stats over
    the combined series, and writes out only the NEW rows (existing
    history rows already have their own stats from when they were new).
    """
    opensky_key = silver_keys.get("opensky_states")
    if not opensky_key:
        logger.info("No new silver OpenSky data to aggregate this run")
        return None

    states = s3_io.read_parquet(opensky_key)
    new_buckets = aggregate_traffic_by_region_bucket(states)
    if new_buckets.empty:
        logger.info("No traffic buckets produced this run")
        return None

    from pipeline.serving.load_dynamodb import fetch_recent_history  # local import avoids a transform<->serving import cycle at module load time

    regions = new_buckets["region"].unique().tolist()
    history = fetch_recent_history(regions, ROLLING_BASELINE_MAX_BUCKETS)
    combined = new_buckets if history.empty else pd.concat([history, new_buckets], ignore_index=True)
    combined = combined.drop_duplicates(subset=["region", "bucket_sk"], keep="last")
    combined_with_anomaly = compute_rolling_baseline_and_anomaly(combined)

    new_keys = set(zip(new_buckets["region"], new_buckets["bucket_sk"]))
    is_new = combined_with_anomaly.apply(lambda r: (r["region"], r["bucket_sk"]) in new_keys, axis=1)
    new_rows = combined_with_anomaly[is_new].reset_index(drop=True)

    gold_key = f"gold/traffic_by_region/dt={snapshot}/traffic_by_region.parquet"
    s3_io.write_parquet(new_rows, gold_key)
    logger.info(
        "Wrote %d new traffic-by-region rows (with %d rows of history considered) to %s",
        len(new_rows), len(history), gold_key,
    )
    return gold_key


def _gold_conflict_events(silver_keys: dict[str, str], snapshot: str) -> str | None:
    """Near-passthrough of the already Gulf-bbox/QuadClass-filtered and
    region-joined silver conflict table -- no further aggregation needed,
    just promotion to a stable gold schema for serving."""
    gdelt_key = silver_keys.get("gdelt_events")
    if not gdelt_key:
        logger.info("No new silver GDELT data to promote this run")
        return None

    events = s3_io.read_parquet(gdelt_key)
    if events.empty:
        logger.info("No Gulf-region conflict events this run")
        return None

    gold_key = f"gold/conflict_events/dt={snapshot}/conflict_events.parquet"
    s3_io.write_parquet(events, gold_key)
    logger.info("Wrote %d conflict-event rows to %s", len(events), gold_key)
    return gold_key


def run(silver_keys: dict[str, str], snapshot_date: date | None = None) -> dict[str, str]:
    """silver_keys: {"opensky_states": key, "gdelt_events": key} (as
    returned by transform.silver.run() -- either or both may be absent if
    that source had nothing new this run). Returns whichever gold keys
    were actually written.
    """
    snapshot = (snapshot_date or date.today()).isoformat()
    result = {}

    traffic_key = _gold_traffic(silver_keys, snapshot)
    if traffic_key:
        result["gold_traffic_key"] = traffic_key

    conflict_key = _gold_conflict_events(silver_keys, snapshot)
    if conflict_key:
        result["gold_conflict_events_key"] = conflict_key

    return result


def handler(event, context) -> dict:
    return run(silver_keys=event["silver_keys"])
