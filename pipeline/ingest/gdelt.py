"""Ingest: GDELT Event Database v2 bulk export -> bronze. Real, free,
unauthenticated, updated every 15 minutes, no rate limit on the bulk file
(unlike the separate DOC 2.0 query API, which is rate-limited to 1 req/5s
and was hit during planning -- this project deliberately avoids it).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from pipeline.aws_clients import s3_client
from pipeline.config import GDELT_LASTUPDATE_URL, S3_BUCKET_NAME
from pipeline.manifest import stored_etag, update_manifest

logger = logging.getLogger(__name__)

SOURCE_NAME = "gdelt"


def latest_export_url() -> str:
    """lastupdate.txt lists 3 lines, one per product type (export/mentions/
    gkg) for the current 15-min timestamp -- picking the wrong one is a
    real gotcha, confirmed by actually inspecting a real response during
    planning. We want the "export" (raw event) file specifically.
    """
    resp = requests.get(GDELT_LASTUPDATE_URL, timeout=15)
    resp.raise_for_status()
    for line in resp.text.strip().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2].endswith(".export.CSV.zip"):
            return parts[2]
    raise ValueError(f"No .export.CSV.zip line found in {GDELT_LASTUPDATE_URL}")


def run(force: bool = False) -> str:
    """Downloads the latest export zip if it's new (GDELT's own filename
    timestamp doubles as the etag -- no separate hash needed), writes it
    to bronze as-is (unzip happens in transform/silver.py). Safe to run
    every 5 minutes for free -- returns the (possibly unchanged) S3 key.
    """
    url = latest_export_url()
    filename = url.rsplit("/", 1)[-1]

    if not force and filename == stored_etag(SOURCE_NAME):
        logger.info("GDELT export %s already processed, skipping", filename)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"bronze/{SOURCE_NAME}/dt={today}/{filename}"

    logger.info("Downloading %s", url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    s3_key = f"bronze/{SOURCE_NAME}/dt={today}/{filename}"
    s3_client().put_object(Bucket=S3_BUCKET_NAME, Key=s3_key, Body=resp.content)
    update_manifest(SOURCE_NAME, filename, s3_key, "success")
    logger.info("Wrote %d bytes to s3://%s/%s", len(resp.content), S3_BUCKET_NAME, s3_key)
    return s3_key


def handler(event, context) -> dict:
    return {"s3_key": run()}
