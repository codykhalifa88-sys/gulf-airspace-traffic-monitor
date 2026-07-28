"""Small shared S3 read/write helpers used by transform/silver.py,
transform/gold.py, and the orchestrator -- extracted here once it was about
to be duplicated a third time."""
from __future__ import annotations

import io

import pandas as pd

from pipeline.aws_clients import s3_client
from pipeline.config import S3_BUCKET_NAME


def read_bytes(key: str) -> bytes:
    return s3_client().get_object(Bucket=S3_BUCKET_NAME, Key=key)["Body"].read()


def write_bytes(body: bytes, key: str) -> str:
    s3_client().put_object(Bucket=S3_BUCKET_NAME, Key=key, Body=body)
    return key


def read_parquet(key: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(read_bytes(key)))


def write_parquet(df: pd.DataFrame, key: str) -> str:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    s3_client().put_object(Bucket=S3_BUCKET_NAME, Key=key, Body=buf.getvalue())
    return key
