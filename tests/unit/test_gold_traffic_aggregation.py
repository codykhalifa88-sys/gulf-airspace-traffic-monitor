import pandas as pd

from pipeline.transform.gold import aggregate_traffic_by_region_bucket


def _states(rows):
    return pd.DataFrame(rows, columns=["icao24", "nearest_region", "poll_timestamp"])


def test_counts_distinct_aircraft_per_region_and_bucket():
    # All timestamps within the same 5-min bucket (epoch seconds)
    states = _states(
        [
            ("aaa111", "DXB", 1_700_000_000),
            ("bbb222", "DXB", 1_700_000_010),
            ("aaa111", "DXB", 1_700_000_020),  # same aircraft seen twice -> counted once
            ("ccc333", "DOH", 1_700_000_000),
        ]
    )
    out = aggregate_traffic_by_region_bucket(states, bucket_minutes=5)
    dxb = out[out["region"] == "DXB"].iloc[0]
    assert dxb["aircraft_count"] == 2
    doh = out[out["region"] == "DOH"].iloc[0]
    assert doh["aircraft_count"] == 1


def test_a_bucket_row_only_exists_when_a_poll_actually_happened():
    # Only one poll, for one region -- must NOT fabricate rows for other
    # regions or other time buckets. This is the single most important
    # correctness guard in the whole anomaly system (see gold.py docstring):
    # conflating "no data collected" with "zero aircraft observed" would
    # manufacture fake traffic-collapse anomalies out of ordinary missed runs.
    states = _states([("aaa111", "DXB", 1_700_000_000)])
    out = aggregate_traffic_by_region_bucket(states)
    assert len(out) == 1
    assert set(out["region"]) == {"DXB"}
    assert "DOH" not in set(out["region"])
    assert "OTHER" not in set(out["region"])


def test_empty_input_produces_empty_output_with_right_columns():
    out = aggregate_traffic_by_region_bucket(_states([]))
    assert list(out.columns) == ["region", "bucket_sk", "aircraft_count"]
    assert len(out) == 0


def test_timestamps_in_the_same_bucket_are_merged():
    # 5-minute bucket: :00 and :04 fall in the same bucket, :06 does not
    states = _states(
        [
            ("aaa111", "DXB", 1_700_000_000),  # :00
            ("bbb222", "DXB", 1_700_000_000 + 4 * 60),  # :04, same bucket
            ("ccc333", "DXB", 1_700_000_000 + 6 * 60),  # :06, next bucket
        ]
    )
    out = aggregate_traffic_by_region_bucket(states, bucket_minutes=5)
    assert len(out) == 2
    assert sorted(out["aircraft_count"]) == [1, 2]
