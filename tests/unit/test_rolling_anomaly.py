import pandas as pd

from pipeline.transform.gold import compute_rolling_baseline_and_anomaly


def _traffic(region: str, counts: list[int], start="2026-01-01T00:00:00Z", freq="5min"):
    bucket_sk = pd.date_range(start=start, periods=len(counts), freq=freq, tz="UTC")
    return pd.DataFrame({"region": region, "bucket_sk": bucket_sk, "aircraft_count": counts})


def test_insufficient_baseline_before_min_buckets():
    # ROLLING_BASELINE_MIN_BUCKETS default is 12 -- with only 5 prior
    # buckets, every row (even the first) must be insufficient_baseline,
    # never a confident status call on too little data.
    df = _traffic("DXB", [10, 11, 9, 10, 12])
    out = compute_rolling_baseline_and_anomaly(df)
    assert (out["anomaly_status"] == "insufficient_baseline").all()
    assert out["z_score"].isna().all()


def test_flat_baseline_then_manufactured_drop_is_critical():
    # 20 flat buckets at count=10 (real baseline), then one bucket that
    # collapses to 0 -- a real "airspace went quiet" scenario.
    counts = [10] * 20 + [0]
    df = _traffic("DXB", counts)
    out = compute_rolling_baseline_and_anomaly(df)
    last = out.iloc[-1]
    assert last["anomaly_status"] == "critical"
    assert last["anomaly_direction"] == "drop"
    assert last["baseline_n"] >= 12


def test_flat_baseline_then_manufactured_spike_is_flagged_as_spike_not_drop():
    counts = [10] * 20 + [40]
    df = _traffic("DXB", counts)
    out = compute_rolling_baseline_and_anomaly(df)
    last = out.iloc[-1]
    assert last["anomaly_direction"] == "spike"
    assert last["z_score"] > 0


def test_normal_fluctuation_within_baseline_is_normal_status():
    counts = [10, 11, 9, 10, 12, 9, 11, 10, 10, 11, 9, 10, 10]
    df = _traffic("DXB", counts)
    out = compute_rolling_baseline_and_anomaly(df)
    assert out.iloc[-1]["anomaly_status"] == "normal"
    assert out.iloc[-1]["anomaly_direction"] is None


def test_std_floor_prevents_false_critical_on_low_variance_low_traffic_airport():
    # MCT/KWI/BAH-style low-traffic airport: baseline is a rock-steady 1
    # aircraft per bucket (std ~0), then a completely ordinary bump to 2.
    # Without a std floor, z = (2-1)/~0 would blow up to "critical" for a
    # perfectly mundane +1 change.
    counts = [1] * 20 + [2]
    df = _traffic("MCT", counts)
    out = compute_rolling_baseline_and_anomaly(df)
    last = out.iloc[-1]
    assert last["anomaly_status"] in ("normal", "warning")
    assert last["anomaly_status"] != "critical"


def test_multiple_regions_are_computed_independently():
    df = pd.concat(
        [
            _traffic("DXB", [10] * 20 + [0]),  # DXB collapses
            _traffic("DOH", [5] * 20 + [5]),  # DOH stays completely normal
        ],
        ignore_index=True,
    )
    out = compute_rolling_baseline_and_anomaly(df)
    dxb_last = out[out["region"] == "DXB"].iloc[-1]
    doh_last = out[out["region"] == "DOH"].iloc[-1]
    assert dxb_last["anomaly_status"] == "critical"
    assert doh_last["anomaly_status"] == "normal"


def test_empty_input_produces_empty_output_with_right_columns():
    empty = pd.DataFrame(columns=["region", "bucket_sk", "aircraft_count"])
    out = compute_rolling_baseline_and_anomaly(empty)
    assert len(out) == 0
    assert "anomaly_status" in out.columns
