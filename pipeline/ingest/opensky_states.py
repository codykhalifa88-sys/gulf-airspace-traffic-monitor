"""Ingest: OpenSky Network live state vectors -> Kinesis. Thin handler wraps
a plain, directly-callable, directly-testable run() -- same pattern as the
ev-charging-gap-analysis sibling.

Response field order confirmed against a real captured API response during
planning (tests/fixtures/opensky_states_gulf_sample.json), matching
OpenSky's documented schema exactly: 17 fields per state vector, no
optional trailing "category" field in practice.
"""
from __future__ import annotations

import json
import logging
import time

import requests

from pipeline.aws_clients import kinesis_client
from pipeline.config import (
    GULF_BBOX,
    KINESIS_STREAM_NAME,
    OPENSKY_AUTH_URL,
    OPENSKY_BASE_URL,
    OPENSKY_CLIENT_ID,
    OPENSKY_CLIENT_SECRET,
)

logger = logging.getLogger(__name__)

# Index positions in each raw state-vector array, per OpenSky's documented
# schema and confirmed against a real response.
_ICAO24, _CALLSIGN, _ORIGIN_COUNTRY, _TIME_POSITION, _LAST_CONTACT = 0, 1, 2, 3, 4
_LONGITUDE, _LATITUDE, _BARO_ALTITUDE, _ON_GROUND, _VELOCITY = 5, 6, 7, 8, 9
_TRUE_TRACK, _VERTICAL_RATE, _GEO_ALTITUDE = 10, 11, 13

_token_cache: dict = {}


def _oauth_token() -> str | None:
    """OAuth2 client-credentials token, cached in-memory for its expiry.
    Basic auth was retired by OpenSky in March 2026 -- not implemented.
    Anonymous access (no token) works fine without this, just at a lower
    rate-limit ceiling."""
    if not OPENSKY_CLIENT_ID or not OPENSKY_CLIENT_SECRET:
        return None
    if _token_cache.get("expires_at", 0) > time.time():
        return _token_cache["access_token"]

    resp = requests.post(
        OPENSKY_AUTH_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": OPENSKY_CLIENT_ID,
            "client_secret": OPENSKY_CLIENT_SECRET,
        },
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    _token_cache["access_token"] = payload["access_token"]
    _token_cache["expires_at"] = time.time() + payload.get("expires_in", 1800) - 30
    return _token_cache["access_token"]


def fetch_states() -> dict:
    headers = {}
    token = _oauth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(f"{OPENSKY_BASE_URL}/states/all", params=GULF_BBOX, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()


def states_to_records(response: dict) -> list[dict]:
    """Raw OpenSky JSON -> one flat dict per state vector, ready to put on
    Kinesis. Drops rows with a null icao24 (shouldn't happen, but that's
    the partition key) -- null lat/lon rows are kept here and dropped
    downstream in transform/silver.py, since "missing position" is itself
    meaningful telemetry at the bronze layer.
    """
    poll_time = response.get("time")
    records = []
    for s in response.get("states") or []:
        if not s or not s[_ICAO24]:
            continue
        records.append(
            {
                "icao24": s[_ICAO24],
                "callsign": (s[_CALLSIGN] or "").strip() or None,
                "origin_country": s[_ORIGIN_COUNTRY],
                "longitude": s[_LONGITUDE],
                "latitude": s[_LATITUDE],
                "baro_altitude": s[_BARO_ALTITUDE],
                "on_ground": s[_ON_GROUND],
                "velocity": s[_VELOCITY],
                "true_track": s[_TRUE_TRACK],
                "vertical_rate": s[_VERTICAL_RATE],
                "geo_altitude": s[_GEO_ALTITUDE],
                "poll_timestamp": poll_time,
            }
        )
    return records


def run() -> int:
    """Fetches current Gulf-region state vectors and puts them on Kinesis.
    Always fresh -- unlike the static-file sources, every poll is
    deliberately new (no ETag-skip). Returns the number of records sent.
    """
    response = fetch_states()
    records = states_to_records(response)
    if not records:
        logger.info("No aircraft currently in the Gulf bbox")
        return 0

    kinesis = kinesis_client()
    for i in range(0, len(records), 500):  # PutRecords batch limit
        batch = records[i : i + 500]
        kinesis.put_records(
            StreamName=KINESIS_STREAM_NAME,
            Records=[{"Data": json.dumps(r).encode(), "PartitionKey": r["icao24"]} for r in batch],
        )
    logger.info("Put %d state vectors to Kinesis stream %s", len(records), KINESIS_STREAM_NAME)
    return len(records)


def handler(event, context) -> dict:
    return {"records_sent": run()}
