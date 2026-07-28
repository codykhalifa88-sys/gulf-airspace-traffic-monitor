"""Hand-rolled linear pipeline orchestrator -- no Airflow/Step Functions
locally (moto's Step Functions support is metadata-stub only). Calls the
plain run() functions in each pipeline module directly rather than
lambda_client.invoke(), since moto can't execute Lambda code without
Docker. On real AWS, infra/stepfunctions.tf chains the same six functions
via actual Lambda invocations instead.

Usage: python -m orchestrator.run_pipeline
"""
from __future__ import annotations

import argparse
import logging
from datetime import date

from pipeline import s3_io
from pipeline.ingest import gdelt, kinesis_consumer, opensky_states
from pipeline.serving import load_dynamodb
from pipeline.transform import gold, silver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def run(snapshot_date: date | None = None) -> dict:
    snapshot_date = snapshot_date or date.today()

    logger.info("=== Ingest: OpenSky -> Kinesis, GDELT -> bronze ===")
    opensky_states.run()  # puts current state vectors on Kinesis; nothing to consume yet until the next step
    bronze_keys = {
        "opensky_states": kinesis_consumer.run(),  # drains Kinesis -> bronze; None if nothing new
        "gdelt": gdelt.run(),
    }

    logger.info("=== Transform: bronze -> silver ===")
    silver_keys = silver.run(bronze_keys, snapshot_date)

    logger.info("=== Transform: silver -> gold (incl. rolling anomaly detection) ===")
    gold_result = gold.run(silver_keys, snapshot_date)

    logger.info("=== Load: gold -> DynamoDB serving layer ===")
    traffic_df = s3_io.read_parquet(gold_result["gold_traffic_key"]) if gold_result.get("gold_traffic_key") else None
    events_df = (
        s3_io.read_parquet(gold_result["gold_conflict_events_key"]) if gold_result.get("gold_conflict_events_key") else None
    )
    serving_result = load_dynamodb.run(traffic_df, events_df)

    summary = {
        "snapshot_date": snapshot_date.isoformat(),
        "bronze_keys": bronze_keys,
        "silver_keys": silver_keys,
        **gold_result,
        **serving_result,
    }
    logger.info("=== Pipeline complete: %s ===", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    run()
