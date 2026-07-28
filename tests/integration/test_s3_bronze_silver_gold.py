"""Real S3 (against the test moto_server) bronze -> silver -> gold
round-trip, using the same real fixtures as the unit tests -- exercises
the actual I/O, not just the pure transform logic already covered in
tests/unit/."""
import json

from pipeline import s3_io
from pipeline.ingest.opensky_states import states_to_records
from pipeline.transform import gold, silver


def _seed_opensky_bronze() -> str:
    with open("tests/fixtures/opensky_states_gulf_sample.json") as f:
        response = json.load(f)
    records = states_to_records(response)
    body = "\n".join(json.dumps(r) for r in records).encode()
    return s3_io.write_bytes(body, "bronze/opensky_states/dt=test/states_raw.ndjson")


def _seed_gdelt_bronze() -> str:
    with open("tests/fixtures/gdelt_export_sample.CSV.zip", "rb") as f:
        raw = f.read()
    return s3_io.write_bytes(raw, "bronze/gdelt/dt=test/export.CSV.zip")


def test_silver_and_gold_round_trip_through_real_s3(aws_env):
    bronze_keys = {
        "opensky_states": _seed_opensky_bronze(),
        "gdelt": _seed_gdelt_bronze(),
    }

    silver_keys = silver.run(bronze_keys)
    assert silver_keys["opensky_states"].startswith("silver/opensky_states/")
    assert silver_keys["gdelt_events"].startswith("silver/gdelt_events/")

    states_df = s3_io.read_parquet(silver_keys["opensky_states"])
    assert len(states_df) > 0
    assert "nearest_region" in states_df.columns

    events_df = s3_io.read_parquet(silver_keys["gdelt_events"])
    assert len(events_df) == 4  # the 4 real Middle East-bbox, QuadClass>=3 rows in this fixture

    gold_result = gold.run(silver_keys)
    assert "gold_traffic_key" in gold_result
    assert "gold_conflict_events_key" in gold_result

    traffic_df = s3_io.read_parquet(gold_result["gold_traffic_key"])
    assert len(traffic_df) > 0
    assert (traffic_df["anomaly_status"] == "insufficient_baseline").all()  # first-ever run, no history yet

    conflict_df = s3_io.read_parquet(gold_result["gold_conflict_events_key"])
    assert len(conflict_df) == 4


def test_gold_run_with_no_new_silver_data_returns_empty_result(aws_env):
    assert gold.run({}) == {}
